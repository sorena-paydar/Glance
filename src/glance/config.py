"""User settings and on-disk locations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_log_dir

APP_NAME = "glance"


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = Path(user_cache_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    path = Path(user_log_dir(APP_NAME)) / "glance.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def recalibrate_request_path() -> Path:
    """Exists while a restart into recalibration is pending (desktop app)."""
    return cache_dir() / "recalibrate-requested"


def calibration_path() -> Path:
    return config_dir() / "calibration.json"


@dataclass
class Settings:
    """Tunable behaviour. Times are in milliseconds."""

    camera_index: int = 0
    # Gaze is ignored for this long after any trackpad/mouse activity.
    manual_grace_ms: int = 800
    # Gaze must rest on another monitor for this long before the cursor jumps.
    dwell_ms: int = 350
    # Minimum smoothed probability for the gazed monitor.
    min_confidence: float = 0.6
    # Gazed monitor must beat the cursor's monitor by this much.
    switch_margin: float = 0.2
    # Exponential smoothing factor for monitor probabilities (0..1, higher = snappier).
    smoothing: float = 0.35
    # Minimum time between two automatic jumps.
    cooldown_ms: int = 600
    # After you move the cursor yourself, don't pull it back to the monitor you were
    # looking at while moving; wait until your gaze actually moves somewhere new.
    respect_manual_choice: bool = True
    # Treat typing like pointer activity: no jumps while you are typing.
    pause_while_typing: bool = True
    # Duration of the smooth cursor glide; 0 jumps instantly.
    glide_ms: int = 200
    # Where the cursor lands on the new monitor: "gaze" (where you are looking),
    # "last" (where you left it) or "center". Falls back gaze -> last -> center.
    jump_to: str = "gaze"
    # Also move the cursor within a monitor when you look far away from it.
    follow_within_monitor: bool = False
    # How far (fraction of the monitor's diagonal) gaze must be from the cursor.
    follow_distance: float = 0.3
    # Global hotkey that pauses/resumes Glance (pynput syntax).
    hotkey: str = "<ctrl>+<alt>+g"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or settings_path()
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> Path:
        path = path or settings_path()
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path
