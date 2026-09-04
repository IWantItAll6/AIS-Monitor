import os

import pytest

from ui.main_window import MainWindow

FIELD_LOG_1 = "resources/field_log_1.txt"
RSSI_LOG = "resources/field_log_2.log"


def replay_all(window, replay_file):

    window.replay.load_file(replay_file)
    window.replay.filename = replay_file

    errors = []

    while window.replay.has_next():

        line = window.replay.next_line()

        try:
            window.process_sentence(line)

        except Exception as e:
            errors.append(e)

    return errors


# Module-scoped: each real log is ~17-30K lines and only needs replaying
# once — every test below just asserts something different about the same
# resulting state, rather than each redoing the (slow) replay itself.

@pytest.fixture(scope="module")
def field_log_1_result(qapp):

    # Real field-test logs aren't committed to the repo (they're private,
    # not for public sharing) — skip gracefully rather than error for
    # anyone running the suite without their own copy.
    if not os.path.exists(FIELD_LOG_1):
        pytest.skip(f"{FIELD_LOG_1} not present — real field logs aren't in the repo")

    window = MainWindow()

    # Vessels seen only once early in the file get purged by the default
    # 1-minute vessel_timeout before later tests can inspect them.
    window.settings["vessel_timeout"] = "Unlimited"

    errors = replay_all(window, FIELD_LOG_1)

    return window, errors


@pytest.fixture(scope="module")
def rssi_result(qapp):

    if not os.path.exists(RSSI_LOG):
        pytest.skip(f"{RSSI_LOG} not present — real field logs aren't in the repo")

    window = MainWindow()

    errors = replay_all(window, RSSI_LOG)

    return window, errors


def test_field_log_1_replay_raises_no_errors(field_log_1_result):

    window, errors = field_log_1_result

    assert errors == [], f"{len(errors)} errors replaying {FIELD_LOG_1}: {errors[:5]}"


def test_rssi_replay_raises_no_errors(rssi_result):

    window, errors = rssi_result

    assert errors == [], f"{len(errors)} errors replaying {RSSI_LOG}: {errors[:5]}"


def test_field_log_1_produces_plausible_vessel_count(field_log_1_result):

    window, _ = field_log_1_result

    assert len(window.registry.vessels) >= 20


def test_field_log_1_own_position_resolves_within_expected_region(field_log_1_result):

    window, _ = field_log_1_result

    assert window.own_position["fix"] is True
    assert 50.0 < window.own_position["lat"] < 52.0
    assert -5.0 < window.own_position["lon"] < -2.0


def test_field_log_1_callsigns_and_ship_types_extracted(field_log_1_result):

    window, _ = field_log_1_result

    with_callsign = [v for v in window.registry.vessels.values() if v.callsign]
    with_type = [v for v in window.registry.vessels.values() if v.type]

    assert len(with_callsign) >= 10
    assert len(with_type) >= 10


def test_rssi_log_attaches_rssi_to_vessels(rssi_result):

    window, _ = rssi_result

    with_rssi = [v for v in window.registry.vessels.values() if v.rssi is not None]

    assert len(with_rssi) >= 1


def test_tree_item_count_stays_in_sync_with_registry(field_log_1_result):

    window, _ = field_log_1_result

    assert window.target_tree.topLevelItemCount() == len(window.registry.vessels)
    assert len(window.tree_items) == len(window.registry.vessels)
