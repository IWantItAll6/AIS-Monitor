from collections import deque
from datetime import datetime, timedelta

from ui.main_window import MainWindow


def test_trim_vessel_rssi_history_removes_only_stale_points_from_the_front(qapp):

    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now
    window.settings["track_length"] = "5"

    vessel = window.registry.get_or_create(123)
    vessel.rssi_history = deque([
        (now - timedelta(minutes=10), -80),
        (now - timedelta(minutes=8), -78),
        (now - timedelta(minutes=2), -70),
        (now, -65),
    ])

    window.trim_vessel_rssi_history()

    assert len(vessel.rssi_history) == 2
    assert vessel.rssi_history[0] == (now - timedelta(minutes=2), -70)
    assert vessel.rssi_history[-1] == (now, -65)


def test_trim_vessel_rssi_history_respects_unlimited_setting(qapp):

    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now
    window.settings["track_length"] = "Unlimited"

    vessel = window.registry.get_or_create(123)
    vessel.rssi_history = deque([(now - timedelta(hours=5), -80)])

    window.trim_vessel_rssi_history()

    assert len(vessel.rssi_history) == 1


def test_trim_vessel_rssi_history_does_nothing_without_a_replay_time_reference(qapp):

    window = MainWindow()

    assert window.replay.current_time is None

    vessel = window.registry.get_or_create(123)
    vessel.rssi_history = deque([(datetime.now() - timedelta(hours=5), -80)])

    window.trim_vessel_rssi_history()

    assert len(vessel.rssi_history) == 1


def test_psmt_rssi_appends_to_history_not_just_scalar(qapp):

    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now

    window.route_sentence("!AIVDM,1,1,,A,15NPOOPP00o?b=bE`UNv4?w428D;,0*3A")

    assert window.last_ais_mmsi is not None

    window.route_sentence("$PSMT,,,,,,,,,,-72,*00")

    vessel = window.registry.get(window.last_ais_mmsi)

    assert vessel.rssi == -72
    assert vessel.rssi_history[-1] == (now, -72)
