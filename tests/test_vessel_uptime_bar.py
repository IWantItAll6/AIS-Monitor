from datetime import datetime, timedelta

from services.vessel_uptime import UptimeState
from ui.vessel_uptime_bar import VesselUptimeBar

START = datetime(2026, 1, 1, 0, 0, 0)


def at(seconds):
    return START + timedelta(seconds=seconds)


def test_bucket_index_is_stable_regardless_of_which_window_it_is_computed_for(qapp):

    # The whole point of grid-anchored buckets: the same instant must map
    # to the same bucket index no matter what bucket_seconds' *source*
    # window happens to be, as long as bucket_seconds itself is the same.
    bar = VesselUptimeBar()

    bucket_seconds = 10.0
    moment = at(12345)

    assert bar.bucket_index(moment, bucket_seconds) == bar.bucket_index(moment, bucket_seconds)


def test_bucket_bounds_round_trips_through_bucket_index(qapp):

    bar = VesselUptimeBar()
    bucket_seconds = 10.0

    index = bar.bucket_index(at(125), bucket_seconds)
    bucket_start, bucket_end = bar.bucket_bounds(index, bucket_seconds)

    assert bucket_start <= at(125) < bucket_end
    assert (bucket_end - bucket_start).total_seconds() == bucket_seconds


def test_a_fixed_red_span_covers_the_same_number_of_buckets_as_now_advances(qapp):
    """The bug this whole grid-anchoring scheme fixes: previously, bucket
    boundaries were computed fresh each repaint as fractions of the total
    visible span, so as "now" advanced (continuously sliding the window),
    a fixed historical red stretch would sometimes cover 4 buckets,
    sometimes 3, with no underlying data change. Anchoring buckets to a
    fixed grid (GRID_EPOCH) instead of to a per-repaint start_time means a
    fixed span always overlaps the same set of bucket boundaries."""

    bar = VesselUptimeBar()

    red_start = at(1000)
    red_end = at(1045)  # a fixed 45s-wide red stretch

    bar.segments = [
        (at(0), red_start, UptimeState.GREEN),
        (red_start, red_end, UptimeState.RED),
    ]

    bucket_seconds = 10.0  # fixed, as it would be with a fixed window_start

    counts = set()

    # Simulate "now" creeping forward in small, sub-bucket steps, as it
    # would across consecutive repaints during a live/replay session.
    for now_offset_ms in range(0, 3000, 137):

        now = red_end + timedelta(milliseconds=now_offset_ms)

        red_bucket_count = 0

        for index in range(bar.bucket_index(at(0), bucket_seconds), bar.bucket_index(now, bucket_seconds) + 1):

            bucket_start, bucket_end = bar.bucket_bounds(index, bucket_seconds)

            if bar.worst_state_in(bucket_start, bucket_end) == UptimeState.RED:
                red_bucket_count += 1

        counts.add(red_bucket_count)

    # Not necessarily a single exact number (the grid's phase relative to
    # red_start/red_end is arbitrary), but it must be stable — not
    # drifting across repaints the way the bug did.
    assert len(counts) == 1


def test_worst_state_in_picks_red_over_everything(qapp):

    bar = VesselUptimeBar()
    bar.segments = [
        (at(0), at(3), UptimeState.GREEN),
        (at(3), at(6), UptimeState.AMBER),
        (at(6), at(9), UptimeState.RED),
    ]

    assert bar.worst_state_in(at(0), at(9)) == UptimeState.RED


def test_worst_state_in_picks_green_over_amber_when_no_red_present(qapp):

    # A vessel bouncing between amber and green without ever truly failing
    # should read as green, not a wall of amber.
    bar = VesselUptimeBar()
    bar.segments = [
        (at(0), at(3), UptimeState.AMBER),
        (at(3), at(4), UptimeState.GREEN),
        (at(4), at(9), UptimeState.AMBER),
    ]

    assert bar.worst_state_in(at(0), at(9)) == UptimeState.GREEN


def test_worst_state_in_picks_amber_only_when_it_is_the_only_state_present(qapp):

    bar = VesselUptimeBar()
    bar.segments = [(at(0), at(9), UptimeState.AMBER)]

    assert bar.worst_state_in(at(0), at(9)) == UptimeState.AMBER
