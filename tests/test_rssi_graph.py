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
