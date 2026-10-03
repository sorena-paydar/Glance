from glance.config import Settings
from glance.engine import SwitchEngine

LOOK_0 = [1.0, 0.0, 0.0]
LOOK_1 = [0.0, 1.0, 0.0]
LOOK_2 = [0.0, 0.0, 1.0]
NEVER = -1e9  # no manual input yet


def make_engine(**overrides) -> SwitchEngine:
    settings = Settings(
        smoothing=1.0, dwell_ms=300, cooldown_ms=500, manual_grace_ms=800, **overrides
    )
    return SwitchEngine(settings)


def feed(engine, start, end, probs, cursor, last_manual=NEVER, step=0.05, busy=False):
    """Feed identical samples from start to end; return (time, target) of first jump."""
    t = start
    while t <= end + 1e-9:
        target = engine.update(t, probs, cursor, last_manual, busy)
        if target is not None:
            return t, target
        t = round(t + step, 6)
    return None


def test_jumps_after_dwell():
    engine = make_engine()
    hit = feed(engine, 0.0, 2.0, LOOK_1, cursor=0)
    assert hit is not None
    t, target = hit
    assert target == 1
    assert t >= 0.3


def test_no_jump_when_looking_at_cursor_monitor():
    engine = make_engine()
    assert feed(engine, 0.0, 2.0, LOOK_0, cursor=0) is None


def test_brief_glance_does_not_jump():
    engine = make_engine()
    assert feed(engine, 0.0, 0.2, LOOK_1, cursor=0) is None
    assert feed(engine, 0.25, 2.0, LOOK_0, cursor=0) is None


def test_manual_input_blocks_gaze():
    engine = make_engine()
    # User keeps moving the trackpad: every sample sees fresh manual input.
    t = 0.0
    while t < 3.0:
        assert engine.update(t, LOOK_1, 0, last_manual_input=t) is None
        t += 0.05


def test_drag_blocks_gaze():
    engine = make_engine()
    assert feed(engine, 0.0, 3.0, LOOK_1, cursor=0, busy=True) is None


def test_respects_manual_choice_until_gaze_moves():
    engine = make_engine()
    # User moves the cursor on monitor 0 while reading monitor 1.
    assert feed(engine, 0.0, 1.0, LOOK_1, cursor=0, last_manual=1.0) is None
    # Hands off: they are still reading monitor 1, the cursor must stay put.
    assert feed(engine, 1.85, 4.0, LOOK_1, cursor=0, last_manual=1.0) is None
    # They glance at monitor 2: that is a new gaze target, so it moves.
    hit = feed(engine, 4.05, 6.0, LOOK_2, cursor=0, last_manual=1.0)
    assert hit is not None and hit[1] == 2


def test_manual_choice_can_be_disabled():
    engine = make_engine(respect_manual_choice=False)
    assert feed(engine, 0.0, 1.0, LOOK_1, cursor=0, last_manual=1.0) is None
    hit = feed(engine, 1.85, 4.0, LOOK_1, cursor=0, last_manual=1.0)
    assert hit is not None and hit[1] == 1


def test_low_confidence_does_not_jump():
    engine = make_engine()
    assert feed(engine, 0.0, 2.0, [0.4, 0.35, 0.25], cursor=2) is None


def test_switch_margin_required():
    engine = make_engine(min_confidence=0.4, switch_margin=0.2)
    assert feed(engine, 0.0, 2.0, [0.45, 0.5, 0.05], cursor=0) is None


def test_face_lost_resets_dwell():
    engine = make_engine()
    assert feed(engine, 0.0, 0.2, LOOK_1, cursor=0) is None
    assert engine.update(0.25, None, 0, NEVER) is None
    # Dwell restarts from scratch once the face is back.
    t, target = feed(engine, 0.3, 2.0, LOOK_1, cursor=0)
    assert target == 1
    assert t >= 0.6


def test_cooldown_between_jumps():
    engine = make_engine()
    t1, _ = feed(engine, 0.0, 2.0, LOOK_1, cursor=0)
    t2, target = feed(engine, t1 + 0.05, 4.0, LOOK_2, cursor=1)
    assert target == 2
    assert t2 - t1 >= 0.5


def test_smoothing_filters_single_noisy_frame():
    engine = SwitchEngine(Settings(smoothing=0.3, dwell_ms=0, cooldown_ms=0))
    for i in range(20):
        engine.update(i * 0.05, LOOK_0, 0, NEVER)
    assert engine.update(1.0, LOOK_1, 0, NEVER) is None
