from glance.displays import Monitor
from glance.motion import glide_path

LEFT = Monitor(0, 0, 1000, 800)
RIGHT = Monitor(1000, -500, 800, 400)  # offset: the straight line crosses a gap


def test_path_ends_exactly_at_target():
    path = glide_path((100, 100), (900, 700), [LEFT], duration=0.2)
    assert path[-1] == (900, 700)
    assert len(path) > 10


def test_path_eases_out():
    path = glide_path((0, 0), (999, 0), [LEFT], duration=0.2)
    first_step = path[1][0] - path[0][0]
    last_step = path[-1][0] - path[-2][0]
    assert first_step > last_step


def test_path_stays_on_monitors():
    path = glide_path((500, 400), (1400, -300), [LEFT, RIGHT], duration=0.2)
    for x, y in path:
        assert LEFT.contains(x, y) or RIGHT.contains(x, y), (x, y)
    assert path[-1] == (1400, -300)


def test_zero_duration_is_a_single_jump():
    assert glide_path((0, 0), (500, 500), [LEFT], duration=0) == [(500, 500)]
