"""Monitor layout in global desktop coordinates.

Coordinates use the same space as the pointer: origin at the top-left of the
primary display, y growing downwards. On macOS these are points (not pixels).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    name: str = ""
    is_primary: bool = False
    # OS display identifier (CGDirectDisplayID on macOS); not stable across reboots.
    native_id: int = 0

    @property
    def key(self) -> str:
        """Identifier that is stable for a given physical arrangement."""
        return f"{self.width}x{self.height}@{self.x},{self.y}"

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height

    def clamp(self, px: float, py: float) -> tuple[float, float]:
        cx = min(max(px, self.x), self.x + self.width - 1)
        cy = min(max(py, self.y), self.y + self.height - 1)
        return cx, cy

    def label(self) -> str:
        role = "primary" if self.is_primary else "secondary"
        name = self.name or "Display"
        return f"{name} ({self.width}x{self.height}, {role})"


def monitor_at(monitors: Sequence[Monitor], px: float, py: float) -> int | None:
    """Index of the monitor containing the point, or the nearest one."""
    for i, m in enumerate(monitors):
        if m.contains(px, py):
            return i
    if not monitors:
        return None

    def distance(m: Monitor) -> float:
        cx, cy = m.clamp(px, py)
        return (cx - px) ** 2 + (cy - py) ** 2

    return min(range(len(monitors)), key=lambda i: distance(monitors[i]))


def layout_key(monitors: Sequence[Monitor]) -> str:
    return "|".join(m.key for m in monitors)


def get_monitors(with_names: bool = True) -> list[Monitor]:
    """Current monitors, ordered left-to-right then top-to-bottom.

    Pass ``with_names=False`` off the main thread: on macOS, names come from AppKit.
    """
    if sys.platform == "darwin":
        monitors = _macos_monitors(with_names)
    else:
        monitors = _screeninfo_monitors()
    return sorted(monitors, key=lambda m: (m.x, m.y))


def _macos_monitors(with_names: bool) -> list[Monitor]:
    import Quartz

    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    if err:
        raise RuntimeError(f"CGGetActiveDisplayList failed with error {err}")
    names = _macos_display_names() if with_names else {}
    main = Quartz.CGMainDisplayID()
    monitors = []
    for display_id in ids[:count]:
        bounds = Quartz.CGDisplayBounds(display_id)
        monitors.append(
            Monitor(
                x=int(bounds.origin.x),
                y=int(bounds.origin.y),
                width=int(bounds.size.width),
                height=int(bounds.size.height),
                name=names.get(display_id, ""),
                is_primary=display_id == main,
                native_id=int(display_id),
            )
        )
    return monitors


def _macos_display_names() -> dict[int, str]:
    try:
        from AppKit import NSScreen
    except ImportError:
        return {}
    names = {}
    for screen in NSScreen.screens():
        display_id = screen.deviceDescription().get("NSScreenNumber")
        if display_id is not None:
            names[int(display_id)] = str(screen.localizedName())
    return names


def _screeninfo_monitors() -> list[Monitor]:
    import screeninfo

    return [
        Monitor(
            x=m.x,
            y=m.y,
            width=m.width,
            height=m.height,
            name=m.name or "",
            is_primary=bool(m.is_primary),
        )
        for m in screeninfo.get_monitors()
    ]
