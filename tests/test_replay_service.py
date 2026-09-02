from datetime import datetime

from services.replay_service import ReplayService


def test_extract_timestamp_parses_real_log_format():

    service = ReplayService()

    line = "[2026-06-18 12:55:43.319] !AIVDM,1,1,,,dummy,0*00"

    assert service.extract_timestamp(line) == datetime(2026, 6, 18, 12, 55, 43, 319000)


def test_extract_timestamp_returns_none_for_unmatched_line():

    service = ReplayService()

    assert service.extract_timestamp("no timestamp on this line") is None


def test_speed_up_and_slow_down_adjust_interval():

    service = ReplayService()

    assert service.speed == 1

    service.speed_up()
    assert service.speed == 2
    assert service.interval_ms(100) == 50

    service.slow_down()
    assert service.speed == 1

    # Never drops below 1x.
    service.slow_down()
    assert service.speed == 1


def test_next_batch_groups_lines_sharing_a_timestamp():

    service = ReplayService()

    service.lines = [
        "[2026-01-01 08:00:00.000] LINE_A\n",
        "[2026-01-01 08:00:00.000] LINE_B\n",
        "[2026-01-01 08:00:05.000] LINE_C\n",
    ]

    batch = service.next_batch()

    assert batch == [
        "[2026-01-01 08:00:00.000] LINE_A",
        "[2026-01-01 08:00:00.000] LINE_B",
    ]

    assert service.next_batch() == ["[2026-01-01 08:00:05.000] LINE_C"]
    assert service.next_batch() == []


def test_time_until_next_ms_reflects_real_elapsed_gap():

    service = ReplayService()

    service.lines = [
        "[2026-01-01 08:00:00.000] LINE_A\n",
        "[2026-01-01 08:00:05.500] LINE_B\n",
    ]

    service.next_batch()
    service.current_time = service.extract_timestamp("[2026-01-01 08:00:00.000] LINE_A")

    assert service.time_until_next_ms() == 5500


def test_time_until_next_ms_falls_back_to_zero_without_a_reference_time():

    # current_time is only set once a line has actually been processed
    # (see MainWindow.process_sentence -> update_time) — before that, or if
    # a line's timestamp fails to parse, there's nothing to measure a gap
    # against, so replay should proceed immediately rather than stall.
    service = ReplayService()

    service.lines = ["[2026-01-01 08:00:00.000] LINE_A\n"]

    assert service.time_until_next_ms() == 0
