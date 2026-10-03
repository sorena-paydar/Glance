"""Pointer control and manual-input detection.

Manual activity is detected two ways so that it is never missed:
  * a global listener for moves, clicks, drags and scrolls (needs Accessibility /
    Input Monitoring permission on macOS);
  * polling the pointer position, which catches movement we did not cause even
    when the listener receives nothing.
Our own warps are recognised and never counted as manual input.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Sequence

from pynput import mouse

# Pointer events within this distance of a warp target count as the warp itself.
SYNTHETIC_TOLERANCE = 2.0
# How long after a warp its echo events may still arrive.
SYNTHETIC_WINDOW = 0.25


class Pointer:
    def __init__(self) -> None:
        self._mouse = mouse.Controller()
        self._lock = threading.Lock()
        self._buttons_down = 0
        # Recent warp targets (x, y, deadline): a glide makes many in quick succession.
        self._synthetic: deque[tuple[float, float, float]] = deque(maxlen=64)
        self.last_manual = -math.inf
        self._last_seen = self.position()
        self._listener = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll
        )

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def position(self) -> tuple[float, float]:
        x, y = self._mouse.position
        return float(x), float(y)

    @property
    def busy(self) -> bool:
        """True while a mouse button is held down (clicking or dragging)."""
        return self._buttons_down > 0

    def poll(self) -> tuple[float, float]:
        """Read the pointer; movement we did not cause counts as manual input."""
        pos = self.position()
        with self._lock:
            if _distance(pos, self._last_seen) > SYNTHETIC_TOLERANCE:
                if not self._is_synthetic(pos, time.monotonic()):
                    self.last_manual = time.monotonic()
                self._last_seen = pos
        return pos

    def warp(self, x: float, y: float) -> bool:
        """Move the pointer, unless the user moved it since the last poll."""
        with self._lock:
            now = time.monotonic()
            pos = self.position()
            if _distance(pos, self._last_seen) > SYNTHETIC_TOLERANCE and not self._is_synthetic(
                pos, now
            ):
                self.last_manual = now
                self._last_seen = pos
                return False
            self._synthetic.append((x, y, now + SYNTHETIC_WINDOW))
            self._mouse.position = (x, y)
            self._last_seen = (x, y)
            return True

    def glide(self, path: Sequence[tuple[float, float]], step_seconds: float) -> bool:
        """Move along ``path`` one point per step. Stops as soon as the user moves.

        Returns True if the whole path was travelled.
        """
        for i, (x, y) in enumerate(path):
            if i:
                time.sleep(step_seconds)
            if not self.warp(x, y):
                return False
        return True

    def _is_synthetic(self, pos: tuple[float, float], now: float) -> bool:
        while self._synthetic and self._synthetic[0][2] < now:
            self._synthetic.popleft()
        return any(_distance(pos, (sx, sy)) <= SYNTHETIC_TOLERANCE for sx, sy, _ in self._synthetic)

    def _mark_manual(self) -> None:
        self.last_manual = time.monotonic()

    def _on_move(self, x: float, y: float) -> None:
        with self._lock:
            if self._is_synthetic((x, y), time.monotonic()):
                return
            self._mark_manual()

    def _on_click(self, x: float, y: float, button: mouse.Button, pressed: bool) -> None:
        with self._lock:
            self._buttons_down = max(0, self._buttons_down + (1 if pressed else -1))
            self._mark_manual()

    def _on_scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        with self._lock:
            self._mark_manual()


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
