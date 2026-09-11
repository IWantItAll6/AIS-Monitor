from PySide6.QtCore import QPointF

from ui.rssi_graph import RssiGraphWidget


def test_compute_scale_uses_the_round_default_when_data_is_within_it():

    # -95 to -85 is well inside the -110..-80 default — no widening needed.
    scale_min, scale_max = RssiGraphWidget.compute_scale(-95, -85)

    assert scale_min == RssiGraphWidget.DEFAULT_MIN_RSSI
    assert scale_max == RssiGraphWidget.DEFAULT_MAX_RSSI


def test_compute_scale_widens_for_a_strong_signal_above_the_default_max():

    # A strong signal (e.g. -70) is above the -80 default ceiling — the
    # scale must stretch to include it rather than clipping it off-screen.
    scale_min, scale_max = RssiGraphWidget.compute_scale(-95, -70)

    assert scale_min == RssiGraphWidget.DEFAULT_MIN_RSSI
    assert scale_max == -70


def test_compute_scale_widens_for_a_weak_signal_below_the_default_min():

    scale_min, scale_max = RssiGraphWidget.compute_scale(-130, -85)

    assert scale_min == -130
    assert scale_max == RssiGraphWidget.DEFAULT_MAX_RSSI


def test_compute_scale_never_returns_a_zero_span():

    # A flat-line history (min == max), even one sitting exactly on a
    # default boundary, must never produce a zero span (draw_graph divides
    # by it).
    scale_min, scale_max = RssiGraphWidget.compute_scale(-80, -80)

    assert scale_max > scale_min


def test_compute_stats_is_none_for_empty_history():

    assert RssiGraphWidget.compute_stats([]) is None


def test_compute_stats_returns_min_max_avg():

    history = [(0, -90), (1, -80), (2, -100)]

    rssi_min, rssi_max, rssi_avg = RssiGraphWidget.compute_stats(history)

    assert rssi_min == -100
    assert rssi_max == -80
    assert rssi_avg == -90.0


def test_marked_point_indices_empty_when_all_gaps_are_narrow():

    # A uniformly fast-reporting vessel — no single gap crosses the
    # threshold, so nothing should be marked.
    points = [QPointF(x, 0) for x in range(0, 20, 2)]

    assert RssiGraphWidget.marked_point_indices(points) == set()


def test_marked_point_indices_marks_both_ends_of_a_wide_gap():

    points = [QPointF(0, 0), QPointF(5, 0), QPointF(30, 0), QPointF(35, 0)]

    # Only the 5->30 gap (25px) clears MIN_MARKER_GAP (14) — both its
    # endpoints (indices 1 and 2) get marked, the narrow gaps' points don't.
    assert RssiGraphWidget.marked_point_indices(points) == {1, 2}


def test_marked_point_indices_handles_a_mixed_rate_vessel():

    # Mostly fast (narrow gaps), with one real gap in the middle — only
    # the real gap's endpoints should be marked, not an average verdict
    # over the whole line.
    points = [QPointF(0, 0), QPointF(2, 0), QPointF(4, 0), QPointF(30, 0), QPointF(32, 0)]

    assert RssiGraphWidget.marked_point_indices(points) == {2, 3}


def test_visible_history_returns_everything_with_no_window_start(qapp):

    widget = RssiGraphWidget()
    history = [(i, -90) for i in range(5)]
    widget.set_history(history, 4)

    assert widget.visible_history() == history


def test_visible_history_filters_to_window_start_without_discarding_stored_history(qapp):

    widget = RssiGraphWidget()
    history = [(i, -90) for i in range(10)]
    widget.set_history(history, 9, window_start=5)

    assert widget.visible_history() == [(i, -90) for i in range(5, 10)]
    # Zooming only changes what's displayed, not what's retained.
    assert widget.history == history
