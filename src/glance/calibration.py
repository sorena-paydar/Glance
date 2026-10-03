"""Interactive calibration: look at targets on each monitor, then fit the model."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from glance.classifier import GazeModel
from glance.displays import Monitor, layout_key
from glance.gaze import GazeTracker
from glance.overlay import Overlay

# Relative target positions on every monitor: centre first, then the corners.
POINTS = ((0.5, 0.5), (0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85))
INTRO_SECONDS = 3.0
SETTLE_SECONDS = 0.9  # time for the eyes to land on a new target
SAMPLE_SECONDS = 1.3
MIN_SAMPLES_PER_POINT = 8
ATTEMPTS_PER_POINT = 3


class CalibrationError(RuntimeError):
    pass


@dataclass
class CalibrationReport:
    model: GazeModel
    samples_per_monitor: list[int]
    # Accuracy when each target is predicted by a model trained without it.
    accuracy_per_monitor: list[float]


def run_calibration(
    tracker: GazeTracker,
    monitors: Sequence[Monitor],
    overlay: Overlay,
    log: Callable[[str], None] = print,
) -> CalibrationReport:
    if not monitors:
        raise CalibrationError("no monitors detected")

    _show_for(
        overlay,
        monitors[0],
        INTRO_SECONDS,
        "Look at each red dot until it moves. Turn your head naturally.",
    )

    features: list[np.ndarray] = []
    labels: list[int] = []
    groups: list[int] = []
    for mi, monitor in enumerate(monitors):
        log(f"Calibrating {monitor.label()}...")
        for rel in POINTS:
            samples = _collect_point(tracker, overlay, monitor, rel)
            features += samples
            labels += [mi] * len(samples)
            groups += [len(set(groups))] * len(samples)
    overlay.close()

    keys = [m.key for m in monitors]
    model = GazeModel.fit(features, labels, keys, layout_key(monitors), groups=groups)
    accuracy = leave_one_point_out_accuracy(features, labels, groups, keys)
    counts = np.bincount(labels, minlength=len(monitors)).tolist()
    return CalibrationReport(model, counts, accuracy)


def leave_one_point_out_accuracy(
    features: Sequence[np.ndarray],
    labels: Sequence[int],
    groups: Sequence[int],
    monitor_keys: list[str],
) -> list[float]:
    """Per-monitor accuracy predicting each target from a model fitted without it."""
    x, y, g = np.asarray(features), np.asarray(labels), np.asarray(groups)
    correct = np.zeros(len(monitor_keys))
    total = np.zeros(len(monitor_keys))
    for group in np.unique(g):
        held = g == group
        train_labels = y[~held]
        if len(set(train_labels.tolist())) < len(monitor_keys):
            continue  # can't train without every monitor
        model = GazeModel.fit(x[~held], train_labels, monitor_keys, "", groups=g[~held])
        for feature, label in zip(x[held], y[held], strict=True):
            probs = model.predict_proba(feature)
            total[label] += 1
            if probs is not None and int(probs.argmax()) == label:
                correct[label] += 1
    return [float(c / t) if t else float("nan") for c, t in zip(correct, total, strict=True)]


def _show_for(overlay: Overlay, monitor: Monitor, seconds: float, text: str) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        overlay.show(monitor, 0.5, 0.5, text, 0.0)
        overlay.pump(0.02)


def _collect_point(
    tracker: GazeTracker,
    overlay: Overlay,
    monitor: Monitor,
    rel: tuple[float, float],
) -> list[np.ndarray]:
    text = ""
    for _ in range(ATTEMPTS_PER_POINT):
        samples: list[np.ndarray] = []
        start = time.monotonic()
        collect_from = start + SETTLE_SECONDS
        end = collect_from + SAMPLE_SECONDS
        last_ts = 0.0
        while (now := time.monotonic()) < end:
            progress = max(0.0, (now - collect_from) / SAMPLE_SECONDS)
            overlay.show(monitor, rel[0], rel[1], text, progress)
            overlay.pump(0.015)
            sample = tracker.latest()
            if sample is None or sample.timestamp <= max(last_ts, collect_from):
                continue
            last_ts = sample.timestamp
            if sample.features is not None:
                samples.append(sample.features)
        if len(samples) >= MIN_SAMPLES_PER_POINT:
            return samples
        text = "Face not detected - face the camera and look at the dot"
    raise CalibrationError("could not see your face; check lighting and that the camera faces you")
