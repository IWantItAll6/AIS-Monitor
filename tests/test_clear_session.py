from ui.main_window import MainWindow

SAMPLE_LOG = "resources/sample_replay.log"


def test_clear_does_not_rewind_an_active_replay(qapp):

    # Found during a manual review: clear_action stays enabled during an
    # active replay (unlike start/pause/stop), and clear_clicked() used to
    # also call self.replay.reset() — silently rewinding the replay's
    # position without stopping its still-pending timer, so it would keep
    # ticking and immediately restart playback from the beginning right
    # after a Clear mid-replay.
    window = MainWindow()

    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    for line in window.replay.next_batch():
        window.process_sentence(line)

    index_before_clear = window.replay.index
    assert index_before_clear > 0

    window.clear_clicked()

    assert window.replay.index == index_before_clear
    assert window.replay.current_time is not None


def test_clear_keeps_pinned_vessel_seen_on_replays_own_clock(qapp):

    # Found alongside the above: Vessel.last_seen defaults to real
    # wall-clock time, but reset_vessel_data() (which a pinned vessel goes
    # through on Clear) never overrode that — so immediately after Clear,
    # a survived pinned vessel's last_seen (real "now") was being compared
    # against replay.current_time (a simulated clock that can be months
    # away), producing a bogus "Seen" reading rather than a sensible one.
    window = MainWindow()

    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    while window.registry.get(999000001) is None and window.replay.has_next():
        for line in window.replay.next_batch():
            window.process_sentence(line)

    vessel = window.registry.get(999000001)
    vessel.pinned = True

    window.clear_clicked()

    survived = window.registry.get(999000001)

    assert survived is not None
    assert survived.pinned is True
    assert survived.last_seen == window.replay.current_time
    assert window.format_seen(survived) == "0s"


def test_clear_resets_a_stale_gnss_fix(qapp):

    # Found in review: own_position was never reset on Clear (or on
    # loading a new replay file, which also goes through reset_session()),
    # so a GNSS fix from before the reset kept being reported as the
    # current position — range/bearing to every vessel and the map's own-
    # ship marker silently used stale real-world coordinates.
    window = MainWindow()

    window.own_position = {"lat": 50.0, "lon": -2.5, "fix": True}

    window.clear_clicked()

    assert window.own_position == {"lat": None, "lon": None, "fix": False}
