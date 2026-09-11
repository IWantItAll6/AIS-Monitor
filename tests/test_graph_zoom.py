from datetime import datetime, timedelta

from ui.main_window import MainWindow

NOW = datetime(2026, 1, 1, 12, 0, 0)


def test_unzoomed_graph_window_matches_the_full_track_window(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    assert window.graph_zoom_seconds is None
    assert window.graph_window_start(NOW) == window.track_window_start(NOW)
    assert window.graph_window_start(NOW) == NOW - timedelta(minutes=10)


def test_zooming_in_narrows_the_graph_window_without_affecting_track_window_start(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    window.adjust_graph_zoom(1 / window.GRAPH_ZOOM_STEP)

    assert window.graph_window_start(NOW) > window.track_window_start(NOW)
    # Data retention (trim_vessel_uptime's cutoff) must stay tied to the
    # track length setting, unaffected by the live display zoom.
    assert window.track_window_start(NOW) == NOW - timedelta(minutes=10)


def test_repeated_zoom_in_stops_at_min_graph_zoom_seconds(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    for _ in range(20):
        window.adjust_graph_zoom(1 / window.GRAPH_ZOOM_STEP)

    displayed_seconds = (NOW - window.graph_window_start(NOW)).total_seconds()

    assert displayed_seconds == window.MIN_GRAPH_ZOOM_SECONDS


def test_zooming_out_past_the_full_window_snaps_back_to_unzoomed(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    window.adjust_graph_zoom(1 / window.GRAPH_ZOOM_STEP)
    assert window.graph_zoom_seconds is not None

    for _ in range(20):
        window.adjust_graph_zoom(window.GRAPH_ZOOM_STEP)

    assert window.graph_zoom_seconds is None
    assert window.graph_window_start(NOW) == window.track_window_start(NOW)


def test_reset_graph_zoom_returns_to_full_window(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    window.adjust_graph_zoom(1 / window.GRAPH_ZOOM_STEP)
    assert window.graph_zoom_seconds is not None

    window.reset_graph_zoom()

    assert window.graph_zoom_seconds is None
    assert window.graph_window_start(NOW) == window.track_window_start(NOW)


def test_zoom_works_with_unlimited_track_length(qapp):

    window = MainWindow()
    window.settings["track_length"] = "Unlimited"

    assert window.track_window_start(NOW) is None
    assert window.graph_window_start(NOW) is None

    window.adjust_graph_zoom(1 / window.GRAPH_ZOOM_STEP)

    # No fixed window to narrow from, so the first zoom-in starts from
    # DEFAULT_GRAPH_ZOOM_SECONDS.
    assert window.graph_zoom_seconds is not None
    assert window.graph_window_start(NOW) is not None
    assert window.track_window_start(NOW) is None  # still unaffected


def test_wheel_zoom_in_and_out_adjust_in_opposite_directions(qapp):

    window = MainWindow()
    window.settings["track_length"] = "10"

    window.on_graph_zoom_wheel(1)  # zoom in
    zoomed_in_start = window.graph_window_start(NOW)

    window.on_graph_zoom_wheel(-1)  # zoom back out one step
    zoomed_out_start = window.graph_window_start(NOW)

    assert zoomed_out_start < zoomed_in_start
