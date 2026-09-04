from datetime import datetime, timedelta

from ui.main_window import MainWindow


def test_selected_mmsi_cleared_when_its_vessel_times_out(qapp):

    # Found in review: selected_mmsi was never cleared when its vessel
    # dropped out of the registry (timeout expiry) — update_target_tree()'s
    # selected-vessel refresh found nothing and no-op'd, leaving the details
    # panel frozen on the timed-out vessel's last values forever.
    window = MainWindow()

    window.settings["vessel_timeout"] = "10"

    now = datetime.now()
    window.replay.current_time = now

    vessel = window.registry.get_or_create(111222333)
    vessel.last_seen = now - timedelta(minutes=20)

    window.selected_mmsi = 111222333
    window.show_vessel_details(vessel)

    assert window.detail_mmsi.text() == "111222333"

    window.check_vessel_timeouts()

    assert window.selected_mmsi is None
    assert window.detail_mmsi.text() == "-"


def test_selected_mmsi_survives_when_a_different_vessel_times_out(qapp):

    window = MainWindow()

    window.settings["vessel_timeout"] = "10"

    now = datetime.now()
    window.replay.current_time = now

    selected = window.registry.get_or_create(111)
    selected.last_seen = now

    expiring = window.registry.get_or_create(222)
    expiring.last_seen = now - timedelta(minutes=20)

    window.selected_mmsi = 111
    window.show_vessel_details(selected)

    window.check_vessel_timeouts()

    assert window.selected_mmsi == 111
    assert window.detail_mmsi.text() == "111"
    assert window.registry.get(222) is None


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
