from datetime import datetime, timedelta

import pytest

from services.vessel_uptime import VesselUptimeTracker, UptimeState

START = datetime(2026, 1, 1, 0, 0, 0)


def at(seconds):
    return START + timedelta(seconds=seconds)


def test_first_report_starts_green_with_no_prior_history():

    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    segments = tracker.segments(at(0))

    assert segments == [(at(0), at(0), UptimeState.GREEN)]


def test_ticking_within_nominal_interval_stays_green():

    # 10kn Class A -> 10s nominal interval.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    for t in range(1, 11):
        tracker.tick(at(t))

    segments = tracker.segments(at(10))

    assert segments == [(at(0), at(10), UptimeState.GREEN)]


def test_ticking_past_nominal_but_within_grace_goes_amber():

    # 10s nominal, grace = 2x = 20s. Ticks every second (matching the real
    # 1s UI timer) so the transition is caught right at the boundary,
    # rather than jumping straight to t=15 and only learning about it late.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    for t in range(1, 16):
        tracker.tick(at(t))

    segments = tracker.segments(at(15))

    # Green up to the amber transition (elapsed > 10s, first true at t=11),
    # then amber through t=15.
    assert segments[0] == (at(0), at(11), UptimeState.GREEN)
    assert segments[1] == (at(11), at(15), UptimeState.AMBER)


def test_ticking_past_grace_goes_red_and_stays_red():

    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # past grace (20s) -> red
    tracker.tick(at(100))  # still red, far later

    segments = tracker.segments(at(100))

    assert segments[-1] == (at(21), at(100), UptimeState.RED)


def test_a_late_report_does_not_retroactively_erase_amber_or_red():

    # The core design decision: once amber/red happened, a later report
    # doesn't rewrite it — it only starts a fresh green segment from its
    # own arrival time onward.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # red

    # A report finally arrives at t=30 — well after grace elapsed.
    tracker.record_report(at(30), msg_type=1, cs_flag=None, speed_kn=10.0)

    segments = tracker.segments(at(30))

    assert (at(0), at(11), UptimeState.GREEN) in segments
    assert (at(11), at(21), UptimeState.AMBER) in segments
    assert (at(21), at(30), UptimeState.RED) in segments
    assert segments[-1] == (at(30), at(30), UptimeState.GREEN)


def test_a_report_arriving_within_grace_never_becomes_red_at_all():

    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    tracker.tick(at(15))  # amber, still within grace (20s)

    # Report arrives at t=18 — resolved before ever reaching red. (Folded
    # back into a single green run — see the retroactive fold-back test
    # below for that behavior specifically.)
    tracker.record_report(at(18), msg_type=1, cs_flag=None, speed_kn=10.0)

    segments = tracker.segments(at(18))

    assert all(state != UptimeState.RED for _, _, state in segments)
    assert segments[-1] == (at(0), at(18), UptimeState.GREEN)


def test_a_report_arriving_within_grace_retroactively_folds_amber_into_green():

    # A late-but-not-lost report proves nothing was actually missed — just
    # slow — so the whole span should read as one continuous green, not
    # green-then-amber-then-green.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    tracker.tick(at(15))  # amber, still within grace (20s)
    assert tracker.segments(at(15))[-1][2] == UptimeState.AMBER

    tracker.record_report(at(18), msg_type=1, cs_flag=None, speed_kn=10.0)

    assert tracker.segments(at(18)) == [(at(0), at(18), UptimeState.GREEN)]


def test_amber_fold_back_only_applies_to_the_current_amber_run_not_past_red():

    # Once a run has actually gone red, a later report resolves that run
    # to green from its own arrival time, but does not reach back through
    # the red (or the amber before it) that already happened in that run.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)

    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # red

    tracker.record_report(at(30), msg_type=1, cs_flag=None, speed_kn=10.0)

    segments = tracker.segments(at(30))

    assert (at(0), at(11), UptimeState.GREEN) in segments
    assert (at(11), at(21), UptimeState.AMBER) in segments
    assert (at(21), at(30), UptimeState.RED) in segments
    assert segments[-1] == (at(30), at(30), UptimeState.GREEN)


def test_record_report_passes_nav_status_through_for_anchored_slowdown():

    # AtAnchor + <=3kn -> 180s nominal (see
    # ais_reporting_intervals.class_a_interval_seconds) — without nav_status
    # this would already be red (10s nominal, 20s grace) well before t=150.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=0.0, nav_status="AtAnchor")
    tracker.tick(at(150))

    assert tracker.segments(at(150)) == [(at(0), at(150), UptimeState.GREEN)]


def test_class_b_sotdma_and_cs_use_different_intervals():

    # 5kn Class B SOTDMA (cs=False) -> 30s nominal, 60s grace.
    sotdma = VesselUptimeTracker()
    sotdma.record_report(at(0), msg_type=18, cs_flag=False, speed_kn=5.0)
    sotdma.tick(at(45))  # past 30s nominal, within 60s grace

    assert sotdma.segments(at(45))[-1][2] == UptimeState.AMBER

    # 5kn Class B CS (cs=True) -> also 30s nominal (>2kn tier) — same result
    # here, but exercised via the cs=True path specifically.
    cs = VesselUptimeTracker()
    cs.record_report(at(0), msg_type=18, cs_flag=True, speed_kn=5.0)
    cs.tick(at(45))

    assert cs.segments(at(45))[-1][2] == UptimeState.AMBER


def test_unmodeled_message_type_is_ignored():

    tracker = VesselUptimeTracker()

    # Type 5 (static data) has no reporting-interval rule.
    tracker.record_report(at(0), msg_type=5, cs_flag=None, speed_kn=10.0)

    assert tracker.change_points == []
    assert tracker.segments(at(0)) == []


def test_trim_keeps_one_change_point_before_cutoff_for_continuity():

    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)
    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # red
    tracker.record_report(at(30), msg_type=1, cs_flag=None, speed_kn=10.0)  # green again

    # Cutoff at t=25 — drops the (0, GREEN) and (11, AMBER) points, but
    # keeps (21, RED) since it's the state in effect at the cutoff itself.
    tracker.trim(at(25))

    assert tracker.change_points == [(at(21), UptimeState.RED), (at(30), UptimeState.GREEN)]


def test_uptime_percentage_is_none_with_no_data():

    tracker = VesselUptimeTracker()

    assert tracker.uptime_percentage(at(0)) is None


def test_uptime_percentage_is_100_for_solid_green():

    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)
    tracker.tick(at(10))

    assert tracker.uptime_percentage(at(10)) == 100.0


def test_uptime_percentage_counts_amber_and_red_against_it():

    # 10s nominal, 20s grace: green 0-11, amber 11-21, red 21-41.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)
    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # red

    assert tracker.uptime_percentage(at(41)) == pytest.approx(11 / 41 * 100)


def test_uptime_percentage_respects_window_start():

    # Same shape as above, but the window starts at t=15 — inside the
    # amber segment, entirely past the green portion, so none of the
    # green before it should count.
    tracker = VesselUptimeTracker()
    tracker.record_report(at(0), msg_type=1, cs_flag=None, speed_kn=10.0)
    tracker.tick(at(11))  # amber
    tracker.tick(at(21))  # red

    assert tracker.uptime_percentage(at(41), window_start=at(15)) == 0.0
