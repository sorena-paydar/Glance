"""Smooth cursor paths between points, possibly across monitors."""

from __future__ import annotations

from collections.abc import Sequence

from glance.displays import Monitor, monitor_at

STEP_SECONDS = 1 / 120


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def glide_path(
    start: tuple[float, float],
    end: tuple[float, float],
    monitors: Sequence[Monitor],
    duration: float,
    step_seconds: float = STEP_SECONDS,
) -> list[tuple[float, float]]:
    """Eased points from ``start`` to ``end``, one per step, ending exactly at ``end``.

    Every point is kept on a monitor: the OS clamps a pointer moved into the gap
    between monitors, which would otherwise look like the user moving it.
    """
    steps = max(1, round(duration / step_seconds))
    path = []
    for i in range(1, steps + 1):
        t = ease_out_cubic(i / steps)
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        index = monitor_at(monitors, x, y)
        if index is not None:
            x, y = monitors[index].clamp(x, y)
        point = (round(x, 1), round(y, 1))
        if not path or point != path[-1]:
            path.append(point)
    return path
