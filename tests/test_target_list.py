from ui.main_window import MainWindow


def test_range_and_bearing_reset_when_gnss_fix_is_lost(qapp):

    # Found in review: vessel.range/bearing were only ever assigned while
    # own_position["fix"] was true — once the fix dropped, the displayed
    # cell correctly went blank, but the underlying fields kept their
    # last-known value forever. Both the tree's own Range-column sort
    # (main_window.py) and MapPanel's map-label placement priority
    # (map_panel.py) read vessel.range directly, so both would keep
    # silently ranking by stale data instead of treating it as unknown.
    window = MainWindow()

    vessel = window.registry.get_or_create(111222333)
    vessel.lat = 50.1
    vessel.lon = -2.5

    window.own_position["fix"] = True
    window.own_position["lat"] = 50.0
    window.own_position["lon"] = -2.5

    window.update_target_tree()

    assert vessel.range is not None
    assert vessel.bearing is not None

    window.own_position["fix"] = False

    window.update_target_tree()

    assert vessel.range is None
    assert vessel.bearing is None
