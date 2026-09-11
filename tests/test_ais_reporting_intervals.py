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


@pytest.mark.parametrize("nav_status", ["AtAnchor", "Moored"])
def test_class_a_anchored_or_moored_slows_to_three_minutes(nav_status):

    assert expected_interval_seconds(1, None, 0, nav_status) == 180
    assert expected_interval_seconds(2, None, 3, nav_status) == 180

    # Above 3kn, the anchored/moored rule no longer applies even if the
    # station is still reporting that nav_status (e.g. dragging anchor).
    assert expected_interval_seconds(3, None, 3.1, nav_status) == 10


def test_class_a_anchored_nav_status_ignored_without_matching_speed_rule():

    # A nav_status of "AtAnchor" alone isn't enough without also being
    # <=3kn — matches the ITU-R table's compound condition.
    assert expected_interval_seconds(1, None, 10, "AtAnchor") == 10


def test_class_a_underway_nav_status_does_not_get_the_anchored_rate():

    assert expected_interval_seconds(1, None, 0, "UnderWayUsingEngine") == 10


def test_class_b_ignores_nav_status_since_speed_alone_already_covers_it():

    # Passing nav_status for Class B is a no-op — its tables already use
    # speed alone for the slow tier.
    assert expected_interval_seconds(18, False, 10, "AtAnchor") == 30


@pytest.mark.parametrize("msg_type", [4, 5, 21, 24, 999])
def test_unmodeled_message_types_return_none(msg_type):

    # Static data, base stations, AtoNs — no ITU-R reporting-rate rule
    # applies, so "not comparable" (None) rather than a fabricated 0.
    assert expected_interval_seconds(msg_type, None, 10) is None
