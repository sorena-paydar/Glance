"""Webcam gaze features using MediaPipe Face Landmarker.

Each frame becomes a feature vector combining head pose (where the face points),
head position, iris position within each eye, and MediaPipe's eye-look
blendshapes. Head pose alone usually separates monitors; the eye features
help when you look with your eyes without turning your head.
"""

from __future__ import annotations

import math
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from glance.config import cache_dir

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

EYE_BLENDSHAPES = (
    "eyeLookInLeft",
    "eyeLookOutLeft",
    "eyeLookUpLeft",
    "eyeLookDownLeft",
    "eyeLookInRight",
    "eyeLookOutRight",
    "eyeLookUpRight",
    "eyeLookDownRight",
)

# Face mesh landmark indices: (outer corner, inner corner, iris centre).
RIGHT_EYE = (33, 133, 468)
LEFT_EYE = (263, 362, 473)

FEATURE_NAMES = (
    "yaw",
    "pitch",
    "roll",
    "head_x",
    "head_y",
    "head_z",
    "right_iris_h",
    "right_iris_v",
    "left_iris_h",
    "left_iris_v",
    *EYE_BLENDSHAPES,
)


class CameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class GazeSample:
    timestamp: float
    features: np.ndarray | None  # None when no face is visible
    frame: np.ndarray | None = None  # BGR frame, only when requested


def ensure_model() -> Path:
    """Download the Face Landmarker model on first use."""
    path = cache_dir() / "face_landmarker.task"
    if not path.exists():
        print("Downloading face landmark model (~4 MB)...", file=sys.stderr)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.replace(path)
    return path


def head_pose(matrix: np.ndarray) -> tuple[float, float, float]:
    """Yaw, pitch, roll in degrees from a 4x4 facial transformation matrix."""
    r = matrix[:3, :3]
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r[2, 0]))))
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


def iris_offset(points: np.ndarray, eye: tuple[int, int, int]) -> tuple[float, float]:
    """Iris position relative to the eye corners.

    Horizontal: 0 at the inner corner, 1 at the outer corner.
    Vertical: signed distance from the corner line, in eye widths.
    """
    outer, inner, iris = points[eye[0]], points[eye[1]], points[eye[2]]
    axis = outer - inner
    width_sq = float(axis @ axis) or 1e-9
    rel = iris - inner
    horizontal = float(rel @ axis) / width_sq
    vertical = float(axis[0] * rel[1] - axis[1] * rel[0]) / width_sq
    return horizontal, vertical


def extract_features(result) -> np.ndarray | None:
    """Feature vector from a FaceLandmarkerResult, or None if no face."""
    if not result.face_landmarks:
        return None
    landmarks = result.face_landmarks[0]
    if len(landmarks) <= max(LEFT_EYE[2], RIGHT_EYE[2]):
        return None
    points = np.array([(lm.x, lm.y) for lm in landmarks])

    matrix = np.asarray(result.facial_transformation_matrixes[0])
    yaw, pitch, roll = head_pose(matrix)
    head_x, head_y, head_z = (float(v) for v in matrix[:3, 3])

    scores = {c.category_name: c.score for c in result.face_blendshapes[0]}
    blend = [float(scores.get(name, 0.0)) for name in EYE_BLENDSHAPES]

    return np.array(
        [
            yaw,
            pitch,
            roll,
            head_x,
            head_y,
            head_z,
            *iris_offset(points, RIGHT_EYE),
            *iris_offset(points, LEFT_EYE),
            *blend,
        ]
    )


class GazeTracker:
    """Reads the webcam on a background thread and keeps the latest sample."""

    def __init__(self, camera_index: int = 0, keep_frames: bool = False) -> None:
        self.camera_index = camera_index
        self.keep_frames = keep_frames
        self._latest: GazeSample | None = None
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._landmarker = None

    def start(self) -> None:
        import cv2
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker,
            FaceLandmarkerOptions,
            RunningMode,
        )

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model())),
            running_mode=RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = FaceLandmarker.create_from_options(options)

        # Open the camera on the calling (main) thread: macOS asks for camera
        # permission there.
        backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.camera_index, backend)
        if not capture.isOpened():
            raise CameraError(
                f"cannot open camera {self.camera_index}; check that it exists and that "
                "this terminal/app has camera permission"
            )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._capture = capture

        self._running.set()
        self._thread = threading.Thread(target=self._run, name="glance-gaze", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
        if self._capture is not None:
            self._capture.release()
        if self._landmarker is not None:
            self._landmarker.close()

    def latest(self) -> GazeSample | None:
        with self._lock:
            return self._latest

    def _run(self) -> None:
        import cv2
        import mediapipe as mp

        last_ts = 0
        failures = 0
        while self._running.is_set():
            ok, frame = self._capture.read()
            if not ok:
                failures += 1
                if failures > 50:
                    print("Camera stopped delivering frames.", file=sys.stderr)
                    self._running.clear()
                time.sleep(0.02)
                continue
            failures = 0

            now = time.monotonic()
            ts = max(int(now * 1000), last_ts + 1)  # must strictly increase
            last_ts = ts
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect_for_video(image, ts)

            sample = GazeSample(
                timestamp=now,
                features=extract_features(result),
                frame=frame if self.keep_frames else None,
            )
            with self._lock:
                self._latest = sample
