"""The running Glance service: gaze in, cursor jumps out."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from glance.classifier import GazeModel
from glance.config import Settings
from glance.displays import Monitor, get_monitors, layout_key, monitor_at
from glance.engine import SwitchEngine
from glance.gaze import GazeTracker
from glance.motion import STEP_SECONDS, glide_path
from glance.pointer import Pointer

TICK_SECONDS = 1 / 30
# Gaze samples older than this are treated as "no face".
STALE_SAMPLE_SECONDS = 0.5
LAYOUT_CHECK_SECONDS = 2.0
# Gaze point predictions average the samples from this window, to reduce jitter.
GAZE_POINT_WINDOW = 0.3


class LayoutChangedError(RuntimeError):
    pass


class GlanceApp:
    def __init__(
        self,
        settings: Settings,
        model: GazeModel,
        monitors: list[Monitor],
        log: Callable[[str], None] = print,
        pointer: Pointer | None = None,
        tracker: GazeTracker | None = None,
    ) -> None:
        if model.layout != layout_key(monitors):
            raise LayoutChangedError(
                "monitor layout changed since calibration; run `glance calibrate` again"
            )
        self.settings = settings
        self.model = model
        self.monitors = monitors
        self.log = log
        self.engine = SwitchEngine(settings)
        self.pointer = pointer or Pointer()
        self.tracker = tracker or GazeTracker(settings.camera_index)
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.last_key = -math.inf
        self._remembered: dict[int, tuple[float, float]] = {}
        self._listeners: list = []
        self._recent: deque[tuple[float, np.ndarray]] = deque(maxlen=60)
        self._follow_since: float | None = None
        self._follow_cooldown = 0.0

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Open the camera and input listeners. Call from the main thread."""
        from pynput import keyboard

        self.tracker.start()
        self.pointer.start()

        # One keyboard listener for both the hotkey and typing detection, started
        # only after it is ready: macOS aborts the process when two threads query
        # the keyboard layout at the same time, which pynput listeners do on start.
        hotkey = keyboard.HotKey(keyboard.HotKey.parse(self.settings.hotkey), self.toggle_pause)

        def on_press(key) -> None:
            if self.settings.pause_while_typing:
                self.last_key = time.monotonic()
            hotkey.press(listener.canonical(key))

        def on_release(key) -> None:
            hotkey.release(listener.canonical(key))

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        listener.wait()
        self._listeners.append(listener)

    def stop(self) -> None:
        self.stopped.set()
        for listener in self._listeners:
            listener.stop()
        self.pointer.stop()
        self.tracker.stop()

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            self.log("Glance resumed")
        else:
            self.paused.set()
            self.engine.reset()
            self.log("Glance paused")

    # -- main loop -----------------------------------------------------------------

    def run(self) -> None:
        """Run until ``stop()`` is called. Blocks the calling thread."""
        next_layout_check = time.monotonic() + LAYOUT_CHECK_SECONDS
        while not self.stopped.is_set():
            started = time.monotonic()
            self.tick(started)
            if started >= next_layout_check:
                next_layout_check = started + LAYOUT_CHECK_SECONDS
                if layout_key(get_monitors(with_names=False)) != self.model.layout:
                    self.log("Monitor layout changed; run `glance calibrate` again.")
                    self.stopped.set()
                    break
            time.sleep(max(0.0, TICK_SECONDS - (time.monotonic() - started)))

    def tick(self, now: float) -> None:
        pos = self.pointer.poll()
        cursor_monitor = monitor_at(self.monitors, *pos)
        if cursor_monitor is not None:
            self._remembered[cursor_monitor] = pos

        if self.paused.is_set():
            return

        probabilities = None
        sample = self.tracker.latest()
        if (
            sample is not None
            and sample.features is not None
            and now - sample.timestamp < STALE_SAMPLE_SECONDS
        ):
            probabilities = self.model.predict_proba(sample.features)
            if not self._recent or self._recent[-1][0] != sample.timestamp:
                self._recent.append((sample.timestamp, sample.features))

        last_manual = self.pointer.last_manual
        if self.settings.pause_while_typing:
            last_manual = max(last_manual, self.last_key)

        target = self.engine.update(
            now,
            None if probabilities is None else probabilities.tolist(),
            cursor_monitor,
            last_manual,
            self.pointer.busy,
        )
        if target is not None:
            self._jump_to(target, now)
        elif self.settings.follow_within_monitor:
            manual = self.pointer.busy or (now - last_manual) * 1000 < self.settings.manual_grace_ms
            self._follow(now, pos, cursor_monitor, manual)

    def gaze_point(self, index: int, now: float) -> tuple[float, float] | None:
        """Where on monitor ``index`` you are looking, from the last few samples."""
        recent = [f for t, f in self._recent if now - t <= GAZE_POINT_WINDOW]
        if not recent:
            return None
        rel = self.model.predict_point(np.mean(recent, axis=0), index)
        if rel is None:
            return None
        m = self.monitors[index]
        return m.x + rel[0] * m.width, m.y + rel[1] * m.height

    def _destination(self, index: int, now: float) -> tuple[float, float]:
        monitor = self.monitors[index]
        dest = None
        if self.settings.jump_to == "gaze":
            dest = self.gaze_point(index, now)
        if dest is None and self.settings.jump_to in ("gaze", "last"):
            dest = self._remembered.get(index)
        return monitor.clamp(*(dest or monitor.center))

    def _move(self, dest: tuple[float, float]) -> bool:
        path = glide_path(self.pointer.poll(), dest, self.monitors, self.settings.glide_ms / 1000)
        return self.pointer.glide(path, STEP_SECONDS)

    def _jump_to(self, index: int, now: float) -> None:
        if self._move(self._destination(index, now)):
            self.log(f"-> {self.monitors[index].label()}")

    def _follow(
        self, now: float, pos: tuple[float, float], cursor_monitor: int | None, manual: bool
    ) -> None:
        """Move within the cursor's monitor when gaze rests far away from it."""
        if (
            manual
            or cursor_monitor is None
            or self.engine.gazed_monitor != cursor_monitor
            or now < self._follow_cooldown
        ):
            self._follow_since = None
            return
        point = self.gaze_point(cursor_monitor, now)
        m = self.monitors[cursor_monitor]
        far = self.settings.follow_distance * math.hypot(m.width, m.height)
        if point is None or math.dist(point, pos) < far:
            self._follow_since = None
            return
        if self._follow_since is None:
            self._follow_since = now
            return
        if (now - self._follow_since) * 1000 >= self.settings.dwell_ms:
            self._follow_since = None
            self._follow_cooldown = now + self.settings.cooldown_ms / 1000
            self._move(m.clamp(*point))
