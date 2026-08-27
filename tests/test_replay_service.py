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
