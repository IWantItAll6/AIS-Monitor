from collections import deque
from datetime import datetime, timedelta

from ui.main_window import MainWindow


def test_trim_track_removes_only_stale_points_from_the_front(qapp):

    # Regression test for a real perf bug: trim_track used to rebuild the
    # whole track by rescanning every point on every call (measured 93M+
    # total_seconds() calls replaying one real field log once tracks grew
    # into the thousands of points) instead of just dropping the stale run
    # at the front.
    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now

    track = deque([
        (now - timedelta(minutes=10), 1.0, 1.0),
        (now - timedelta(minutes=8), 1.0, 1.0),
        (now - timedelta(minutes=2), 1.0, 1.0),
        (now, 1.0, 1.0),
    ])

    window.trim_track(track, 5 * 60)

    assert len(track) == 2
    assert track[0][0] == now - timedelta(minutes=2)
    assert track[-1][0] == now


def test_trim_own_track_respects_unlimited_setting(qapp):

    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now
    window.settings["track_length"] = "Unlimited"

    window.own_track = deque([(now - timedelta(hours=5), 1.0, 1.0)])

    window.trim_own_track()

    assert len(window.own_track) == 1


def test_trim_vessel_tracks_does_nothing_without_a_replay_time_reference(qapp):

    window = MainWindow()

    assert window.replay.current_time is None

    vessel = window.registry.get_or_create(123)
    vessel.track = deque([(datetime.now() - timedelta(hours=5), 1.0, 1.0)])

    window.trim_vessel_tracks()

    assert len(vessel.track) == 1
