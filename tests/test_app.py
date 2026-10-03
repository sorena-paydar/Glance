import math

import numpy as np

from glance.app import GlanceApp
from glance.classifier import GazeModel
from glance.config import Settings
from glance.displays import Monitor, layout_key
from glance.gaze import GazeSample

MONITORS = [Monitor(0, 0, 1000, 800), Monitor(1000, 0, 1000, 800)]


class FakePointer:
    def __init__(self, pos):
        self.pos = pos
        self.last_manual = -math.inf
        self.busy = False
        self.warps = []
        self.glides = []

    def poll(self):
        return self.pos

    def warp(self, x, y):
        self.warps.append((x, y))
        self.pos = (x, y)
        return True

    def glide(self, path, step_seconds):
        self.glides.append(path)
        return self.warp(*path[-1])


class FakeTracker:
    def __init__(self):
        self.sample = None

    def look(self, monitor, now):
        self.sample = GazeSample(now, np.array([float(monitor) * 10]))

    def latest(self):
        return self.sample


def make_app(pos=(500, 400)):
    model = GazeModel.fit(
        [[0.0], [0.5], [10.0], [10.5]],
        [0, 0, 1, 1],
        [m.key for m in MONITORS],
        layout_key(MONITORS),
        k=1,
    )
    settings = Settings(
        smoothing=1.0, dwell_ms=200, cooldown_ms=0, manual_grace_ms=500, glide_ms=100
    )
    pointer, tracker = FakePointer(pos), FakeTracker()
    app = GlanceApp(settings, model, MONITORS, log=lambda _: None, pointer=pointer, tracker=tracker)
    return app, pointer, tracker


def run(app, tracker, monitor, start, end, step=0.05):
    t = start
    while t <= end:
        tracker.look(monitor, t)
        app.tick(t)
        t = round(t + step, 6)


def test_jumps_to_centre_of_unvisited_monitor():
    app, pointer, tracker = make_app()
    run(app, tracker, 1, 0.0, 1.0)
    assert pointer.warps == [(1500.0, 400.0)]


def test_returns_to_remembered_position():
    app, pointer, tracker = make_app(pos=(1200, 100))
    run(app, tracker, 1, 0.0, 0.5)  # cursor already on monitor 1: remembered there
    pointer.pos = (300, 300)  # user moved to monitor 0 by hand
    pointer.last_manual = 0.5
    run(app, tracker, 0, 0.55, 1.2)  # looked at 0 while moving: no jump
    run(app, tracker, 1, 1.25, 2.0)
    assert pointer.warps == [(1200, 100)]


def test_no_jump_while_dragging():
    app, pointer, tracker = make_app()
    pointer.busy = True
    run(app, tracker, 1, 0.0, 2.0)
    assert pointer.warps == []


def test_no_jump_while_typing():
    app, pointer, tracker = make_app()
    t = 0.0
    while t < 2.0:
        app.last_key = t
        tracker.look(1, t)
        app.tick(t)
        t += 0.05
    assert pointer.warps == []


def test_paused_never_jumps():
    app, pointer, tracker = make_app()
    app.toggle_pause()
    run(app, tracker, 1, 0.0, 2.0)
    assert pointer.warps == []


def test_glides_smoothly_across_monitors():
    app, pointer, tracker = make_app()
    run(app, tracker, 1, 0.0, 1.0)
    assert len(pointer.glides) == 1
    path = pointer.glides[0]
    assert len(path) > 5
    assert path[-1] == (1500.0, 400.0)


def make_gaze_app(pos=(500, 400), **overrides):
    """App whose model knows where on each monitor you look: feature 0 encodes the
    monitor (0 or 10) plus the relative x (0..1); feature 1 is the relative y."""
    features, labels, groups, targets = [], [], [], []
    for m in (0, 1):
        for gi, (x, y) in enumerate([(0.1, 0.1), (0.9, 0.1), (0.5, 0.5), (0.1, 0.9), (0.9, 0.9)]):
            for _ in range(5):
                features.append([m * 10 + x, y])
                labels.append(m)
                groups.append(m * 10 + gi)
                targets.append((x, y))
    model = GazeModel.fit(
        features,
        labels,
        [m.key for m in MONITORS],
        layout_key(MONITORS),
        groups=groups,
        targets=targets,
        k=3,
    )
    settings = Settings(
        smoothing=1.0, dwell_ms=200, cooldown_ms=0, manual_grace_ms=500, glide_ms=100, **overrides
    )
    pointer, tracker = FakePointer(pos), FakeTracker()
    app = GlanceApp(settings, model, MONITORS, log=lambda _: None, pointer=pointer, tracker=tracker)
    return app, pointer, tracker


def look_at(app, tracker, monitor, x, y, start, end, step=0.05):
    t = start
    while t <= end:
        tracker.sample = GazeSample(t, np.array([monitor * 10 + x, y]))
        app.tick(t)
        t = round(t + step, 6)


def test_lands_where_you_look():
    app, pointer, tracker = make_gaze_app()
    look_at(app, tracker, 1, 0.8, 0.2, 0.0, 1.0)
    assert len(pointer.warps) == 1
    x, y = pointer.warps[0]
    assert abs(x - 1800) < 40 and abs(y - 160) < 40


def test_jump_to_last_ignores_gaze_point():
    app, pointer, tracker = make_gaze_app(pos=(1200, 100), jump_to="last")
    look_at(app, tracker, 1, 0.5, 0.5, 0.0, 0.3)  # remembers (1200, 100) on monitor 1
    pointer.pos = (300, 300)
    pointer.last_manual = 0.3
    look_at(app, tracker, 0, 0.3, 0.4, 0.35, 1.0)
    look_at(app, tracker, 1, 0.8, 0.8, 1.05, 2.0)
    assert pointer.warps == [(1200, 100)]


def test_follow_within_monitor_is_off_by_default():
    app, pointer, tracker = make_gaze_app(pos=(100, 100))
    look_at(app, tracker, 0, 0.9, 0.9, 0.0, 2.0)
    assert pointer.warps == []


def test_follows_within_monitor_when_enabled():
    app, pointer, tracker = make_gaze_app(pos=(100, 100), follow_within_monitor=True)
    look_at(app, tracker, 0, 0.9, 0.9, 0.0, 2.0)
    assert len(pointer.warps) == 1
    x, y = pointer.warps[0]
    assert abs(x - 900) < 40 and abs(y - 720) < 40


def test_follow_never_overrides_manual_input():
    app, pointer, tracker = make_gaze_app(pos=(100, 100), follow_within_monitor=True)
    t = 0.0
    while t < 2.0:
        pointer.last_manual = t
        tracker.sample = GazeSample(t, np.array([0.9, 0.9]))
        app.tick(t)
        t += 0.05
    assert pointer.warps == []
