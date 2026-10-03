"""The running Glance service: gaze in, cursor jumps out."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from glance.classifier import GazeModel
from glance.config import Settings
from glance.displays import Monitor, get_monitors, layout_key, monitor_at
from glance.engine import SwitchEngine
from glance.gaze import GazeTracker
from glance.pointer import Pointer

TICK_SECONDS = 1 / 30
# Gaze samples older than this are treated as "no face".
STALE_SAMPLE_SECONDS = 0.5
LAYOUT_CHECK_SECONDS = 2.0


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

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Open the camera and input listeners. Call from the main thread."""
        from pynput import keyboard

        self.tracker.start()
        self.pointer.start()
        hotkeys = keyboard.GlobalHotKeys({self.settings.hotkey: self.toggle_pause})
        hotkeys.start()
        self._listeners.append(hotkeys)
        if self.settings.pause_while_typing:
            typing = keyboard.Listener(on_press=self._on_key)
            typing.start()
            self._listeners.append(typing)

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

    def _on_key(self, key) -> None:
        self.last_key = time.monotonic()

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
            self._jump_to(target)

    def _jump_to(self, index: int) -> None:
        monitor = self.monitors[index]
        dest = monitor.center
        if self.settings.remember_position and index in self._remembered:
            dest = self._remembered[index]
        dest = monitor.clamp(*dest)
        if self.pointer.warp(*dest):
            self.log(f"-> {monitor.label()}")
