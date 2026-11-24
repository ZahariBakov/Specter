from specter.ui.screen import clamp, clamp_point

DESKTOP = (0, 0, 3840, 1200)  # two 1920x1200 monitors side by side


def test_window_inside_is_unchanged():
    assert clamp(100, 50, 300, 200, DESKTOP) == (100, 50)


def test_stops_at_every_outer_edge():
    assert clamp(-40, 50, 300, 200, DESKTOP) == (0, 50)
    assert clamp(100, -9, 300, 200, DESKTOP) == (100, 0)
    assert clamp(3800, 50, 300, 200, DESKTOP) == (3540, 50)
    assert clamp(100, 1100, 300, 200, DESKTOP) == (100, 1000)


def test_can_cross_to_the_next_monitor():
    assert clamp(1900, 50, 300, 200, DESKTOP) == (1900, 50)  # straddles the two screens
    assert clamp(2500, 50, 300, 200, DESKTOP) == (2500, 50)


def test_monitor_left_of_the_primary_has_negative_coordinates():
    desktop = (-1920, 0, 1920, 1080)
    assert clamp(-2500, 10, 300, 200, desktop) == (-1920, 10)
    assert clamp(-1000, 10, 300, 200, desktop) == (-1000, 10)


def test_window_bigger_than_the_desktop_is_pinned_top_left():
    assert clamp(50, 50, 5000, 2000, DESKTOP) == (0, 0)


def test_clamp_point():
    assert clamp_point(-5, 2000, DESKTOP) == (0, 1199)
    assert clamp_point(3840, 5, DESKTOP) == (3839, 5)
