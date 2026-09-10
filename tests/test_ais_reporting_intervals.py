import pytest

from services.ais_reporting_intervals import expected_interval_seconds


@pytest.mark.parametrize("speed_kn,expected", [(0, 10), (13.9, 10), (14.1, 6), (23, 6), (23.1, 2), (40, 2)])
def test_class_a_interval_by_speed(speed_kn, expected):

    assert expected_interval_seconds(1, None, speed_kn) == expected
    assert expected_interval_seconds(2, None, speed_kn) == expected
    assert expected_interval_seconds(3, None, speed_kn) == expected


@pytest.mark.parametrize("speed_kn,expected", [(0, 180), (2, 180), (2.1, 30), (14, 30), (14.1, 15), (23, 15), (23.1, 5)])
def test_class_b_sotdma_interval_by_speed(speed_kn, expected):

    # msg_type 18, cs=False -> SOTDMA table.
    assert expected_interval_seconds(18, False, speed_kn) == expected


@pytest.mark.parametrize("speed_kn,expected", [(0, 180), (2, 180), (2.1, 30), (23, 30)])
def test_class_b_cs_interval_by_speed(speed_kn, expected):

    # msg_type 18, cs=True -> CS table (only two tiers, unlike SOTDMA).
    assert expected_interval_seconds(18, True, speed_kn) == expected


def test_class_b_extended_message_is_always_cs():

    # Type 19 ("Extended Class B CS Position Report") has no cs flag at all
    # — it's definitionally always a CS unit, regardless of what's passed.
    assert expected_interval_seconds(19, None, 10) == 30
    assert expected_interval_seconds(19, True, 10) == 30


def test_none_speed_treated_as_stationary():

    assert expected_interval_seconds(1, None, None) == 10
    assert expected_interval_seconds(18, False, None) == 180


@pytest.mark.parametrize("msg_type", [4, 5, 21, 24, 999])
def test_unmodeled_message_types_return_none(msg_type):

    # Static data, base stations, AtoNs — no ITU-R reporting-rate rule
    # applies, so "not comparable" (None) rather than a fabricated 0.
    assert expected_interval_seconds(msg_type, None, 10) is None
