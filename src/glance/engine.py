"""Decides when the cursor should jump to the monitor being looked at.

The engine is pure logic with no I/O, so every rule here is unit-testable.
The guiding rule: manual pointer input always wins over gaze.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from glance.config import Settings


@dataclass
class EngineState:
    smoothed: list[float] | None = None
    candidate: int | None = None
    candidate_since: float = 0.0
    cooldown_until: float = 0.0
    # Monitor that was being looked at while the user moved the pointer by hand.
    suppressed: int | None = None


class SwitchEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = EngineState()

    def reset(self) -> None:
        self.state = EngineState()

    @property
    def gazed_monitor(self) -> int | None:
        """Most likely monitor according to the smoothed probabilities."""
        smoothed = self.state.smoothed
        if not smoothed:
            return None
        top = max(range(len(smoothed)), key=smoothed.__getitem__)
        return top if smoothed[top] >= self.settings.min_confidence else None

    def update(
        self,
        now: float,
        probabilities: Sequence[float] | None,
        cursor_monitor: int | None,
        last_manual_input: float,
        pointer_busy: bool = False,
    ) -> int | None:
        """Feed one gaze sample. Returns a monitor index to jump to, or None.

        Args:
            now: current time in seconds (monotonic).
            probabilities: per-monitor probabilities, or None if no face is seen.
            cursor_monitor: index of the monitor currently holding the cursor.
            last_manual_input: time of the latest manual pointer event (seconds).
            pointer_busy: True while a mouse button is held (e.g. dragging).
        """
        s, cfg = self.state, self.settings

        if probabilities is None:
            s.smoothed = None
            s.candidate = None
            return None

        self._smooth(probabilities)
        gazed = self.gazed_monitor

        manual_active = pointer_busy or (now - last_manual_input) * 1000 < cfg.manual_grace_ms
        if manual_active:
            s.candidate = None
            if cfg.respect_manual_choice:
                s.suppressed = gazed
            return None

        if s.suppressed is not None and gazed != s.suppressed:
            s.suppressed = None

        if gazed is None or gazed == cursor_monitor or gazed == s.suppressed:
            s.candidate = None
            return None

        assert s.smoothed is not None
        if cursor_monitor is not None and cursor_monitor < len(s.smoothed):
            if s.smoothed[gazed] - s.smoothed[cursor_monitor] < cfg.switch_margin:
                s.candidate = None
                return None

        if now < s.cooldown_until:
            return None

        if s.candidate != gazed:
            s.candidate = gazed
            s.candidate_since = now
            return None

        if (now - s.candidate_since) * 1000 < cfg.dwell_ms:
            return None

        s.candidate = None
        s.cooldown_until = now + cfg.cooldown_ms / 1000
        return gazed

    def _smooth(self, probabilities: Sequence[float]) -> None:
        s, alpha = self.state, self.settings.smoothing
        if s.smoothed is None or len(s.smoothed) != len(probabilities):
            s.smoothed = list(probabilities)
            return
        s.smoothed = [alpha * p + (1 - alpha) * q for p, q in zip(probabilities, s.smoothed)]
