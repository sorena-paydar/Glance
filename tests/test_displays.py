from glance.displays import Monitor, layout_key, monitor_at

LAPTOP = Monitor(0, 0, 1512, 982, "Built-in", is_primary=True)
LEFT = Monitor(-1080, -600, 1080, 1920, "Portrait")
RIGHT = Monitor(1512, -200, 1920, 1080, "FHD")
MONITORS = [LEFT, LAPTOP, RIGHT]


def test_monitor_at_inside():
    assert monitor_at(MONITORS, 100, 100) == 1
    assert monitor_at(MONITORS, -500, 1000) == 0
    assert monitor_at(MONITORS, 2000, 0) == 2


def test_monitor_at_edges_are_half_open():
    assert monitor_at(MONITORS, 1511, 0) == 1
    assert monitor_at(MONITORS, 1512, 0) == 2


def test_monitor_at_outside_returns_nearest():
    assert monitor_at(MONITORS, 5000, 0) == 2
    assert monitor_at([], 0, 0) is None


def test_clamp_and_center():
    assert RIGHT.clamp(9999, -9999) == (1512 + 1919, -200)
    assert LAPTOP.center == (756, 491)


def test_layout_key_changes_with_arrangement():
    moved = Monitor(1512, 0, 1920, 1080, "FHD")
    assert layout_key(MONITORS) != layout_key([LEFT, LAPTOP, moved])
