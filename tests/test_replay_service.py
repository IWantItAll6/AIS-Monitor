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


def test_next_batch_does_not_merge_lines_with_unparseable_timestamps():

    # Found in review: `peek_ts != first_ts` is True even when both sides
    # are None (an unparseable/missing timestamp), so every consecutive line
    # with a bad timestamp got folded into one unbounded, unpaced batch
    # instead of being played back one at a time like the rest of the log.
    service = ReplayService()

    service.lines = [
        "NO TIMESTAMP HERE — LINE_A\n",
        "NO TIMESTAMP HERE — LINE_B\n",
        "[2026-01-01 08:00:00.000] LINE_C\n",
    ]

    assert service.next_batch() == ["NO TIMESTAMP HERE — LINE_A"]
    assert service.next_batch() == ["NO TIMESTAMP HERE — LINE_B"]
    assert service.next_batch() == ["[2026-01-01 08:00:00.000] LINE_C"]


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


class FakeClock:

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_clocked_service(lines):

    service = ReplayService()
    service.clock = FakeClock()
    service.lines = lines

    return service


def test_replay_clock_marks_batches_due_by_elapsed_wall_time_times_speed():

    # Regression: pacing used to chain "wait the gap to the next line"
    # timers, so time spent processing/repainting between ticks was never
    # subtracted — on a busy real log 2x/10x collapsed to about real time.
    # The replay clock measures against wall time elapsed since an anchor,
    # so anything the clock has already passed counts as due immediately.
    service = make_clocked_service([
        "[2026-01-01 08:00:00.000] A\n",
        "[2026-01-01 08:00:01.000] B\n",
        "[2026-01-01 08:00:02.000] C\n",
        "[2026-01-01 08:00:10.000] D\n",
    ])
    service.speed = 2

    for line in service.next_batch():
        service.update_time(line)

    service.anchor_clock()

    assert not service.next_batch_due()
    assert service.ms_until_next_due() == 500

    # 1.2s of wall time at 2x = 2.4s of log time: both B and C are overdue,
    # even though only one "tick" has happened.
    service.clock.now += 1.2

    assert service.next_batch_due()
    service.update_time(service.next_batch()[0])
    assert service.next_batch_due()
    service.update_time(service.next_batch()[0])
    assert not service.next_batch_due()

    # D is at +10s log time; the clock is at +2.4s, 7.6s left at 2x.
    assert service.ms_until_next_due() == 3800


def test_speed_change_rebases_clock_instead_of_applying_retroactively():

    service = make_clocked_service([
        "[2026-01-01 08:00:00.000] A\n",
        "[2026-01-01 08:01:00.000] B\n",
    ])

    service.update_time(service.next_batch()[0])
    service.anchor_clock()

    service.clock.now += 10  # 10s of log time at 1x

    service.speed_up()
    service.speed_up()  # now 3x

    # Clock stays at +10s rather than jumping to +30s; 50s left at 3x.
    assert service.clock_time() == datetime(2026, 1, 1, 8, 0, 10)
    assert service.ms_until_next_due() == 16666


def test_clock_not_running_falls_back_to_gap_based_wait():

    service = make_clocked_service([
        "[2026-01-01 08:00:00.000] A\n",
        "[2026-01-01 08:00:01.000] B\n",
    ])

    service.update_time(service.next_batch()[0])

    assert service.clock_time() is None
    assert not service.next_batch_due()
    assert service.ms_until_next_due() == 1000

    service.anchor_clock()
    service.reset()

    assert service.clock_time() is None
