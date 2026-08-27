import pytest

from ui.main_window import MainWindow

# Unlike test_replay_regression.py, this fixture is fully synthetic
# (scripts/generate_sample_log.py) and committed to the repo — this test
# runs for anyone, with no dependency on the author's private field logs.
SAMPLE_LOG = "resources/sample_replay.log"


@pytest.fixture(scope="module")
def sample_result(qapp):

    window = MainWindow()

    errors = []

    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    while window.replay.has_next():

        line = window.replay.next_line()

        try:
            window.process_sentence(line)

        except Exception as e:
            errors.append(e)

    return window, errors


def test_sample_replay_raises_no_errors(sample_result):

    window, errors = sample_result

    assert errors == [], f"{len(errors)} errors: {errors[:5]}"


def test_sample_replay_produces_expected_vessels(sample_result):

    window, _ = sample_result

    # 3 fake vessels plus the synthetic own-ship AIVDO echo.
    assert len(window.registry.vessels) == 4

    names = {v["name"] for v in window.registry.vessels.values() if v["name"]}
    assert names == {"SAMPLE VESSEL ONE", "SAMPLE VESSEL TWO", "SAMPLE TUG THREE"}


def test_sample_replay_extracts_callsign_and_type(sample_result):

    window, _ = sample_result

    vessel = window.registry.get(999000001)

    assert vessel["callsign"] == "ZZ1001"
    assert vessel["type"] == "Cargo"


def test_sample_replay_own_position_resolves(sample_result):

    window, _ = sample_result

    assert window.own_position["fix"] is True
    assert window.own_position["cog"] == 45.0


def test_sample_replay_attaches_rssi(sample_result):

    window, _ = sample_result

    with_rssi = [v for v in window.registry.vessels.values() if v["rssi"] is not None]

    assert len(with_rssi) >= 1


def test_skip_to_end_processes_the_whole_file_without_error(qapp):

    # Uses its own fresh window/replay rather than the shared fixture —
    # skip_to_end_clicked() consumes the replay in one go, unlike the other
    # tests here which step through line by line.
    window = MainWindow()

    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    window.skip_to_end_clicked()

    assert not window.replay.has_next()
    assert window.current_mode == "Stopped"
    assert len(window.registry.vessels) == 4
