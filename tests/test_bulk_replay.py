from datetime import datetime, timedelta

from services.vessel_uptime import UptimeState
from ui.main_window import MainWindow

SAMPLE_LOG = "resources/sample_replay.log"


def write_gap_log(tmp_path, gap_minutes):
    """One AIS position report, then gap_minutes of GNSS-only chatter
    (every 5s, like a real receiver's steady 1Hz-ish fix stream), then a
    resuming AIS report from the same vessel — the scenario found in
    review: a real outage entirely within a stretch that has no
    !AIVDM/!AIVDO/$PSMT traffic at all to drive ticking via
    update_target_tree()."""

    start = datetime(2026, 1, 1, 12, 0, 0)
    lines = []

    def stamp(t):
        return f"[{t:%Y-%m-%d %H:%M:%S.%f}]"

    ais_sentence = "!AIVDM,1,1,,A,13M@KdU01uOiIf@MGja7q5gp05KL,0*0A"

    lines.append(f"{stamp(start)} {ais_sentence}")

    t = start
    end = start + timedelta(minutes=gap_minutes)

    while t < end:
        t += timedelta(seconds=5)
        lines.append(f"{stamp(t)} $GNRMC,000000.00,V,,,,,,,,,,N*7C")

    resume_time = end + timedelta(seconds=5)
    lines.append(f"{stamp(resume_time)} {ais_sentence}")

    path = tmp_path / "gap.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return str(path)


def test_skip_to_end_still_populates_raw_data_in_full(qapp):
    """begin_bulk_replay/end_bulk_replay batch the Raw Data pane update for
    performance (see git log) — this must not lose any of the skipped
    lines' text, only change how many Qt calls it takes to add it."""

    window = MainWindow()
    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    total_lines = len(window.replay.lines)

    window.skip_to_end_clicked()

    raw_text = window.raw_data.toPlainText()

    # Every non-empty line should appear somewhere in Raw Data (filters are
    # all on by default, so nothing here should have been excluded).
    for line in window.replay.lines[:total_lines]:
        stripped = line.rstrip("\n")
        if stripped:
            assert stripped in raw_text


def test_skip_to_end_sets_the_final_replay_time_label(qapp):

    window = MainWindow()
    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    window.skip_to_end_clicked()

    assert window.replay.current_time is not None
    expected = window.replay.current_time.strftime("%Y-%m-%d %H:%M:%S")

    assert window.replay_time_label.text() == expected


def test_bulk_replay_flag_is_cleared_after_end_bulk_replay(qapp):

    window = MainWindow()
    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG

    window.begin_bulk_replay()
    assert window._raw_data_buffer is not None

    window.end_bulk_replay()
    assert window._raw_data_buffer is None


def test_seek_to_index_without_animation_lands_at_the_target_with_correct_state(qapp):

    window = MainWindow()
    window.replay.load_file(SAMPLE_LOG)
    window.replay.filename = SAMPLE_LOG
    window.animate_scrub_checkbox.setChecked(False)

    target_index = len(window.replay.lines) // 2

    window.seek_to_index(target_index)

    assert window.replay.index == target_index + 1
    assert window.replay.current_time is not None
    assert window.replay_time_label.text() == window.replay.current_time.strftime("%Y-%m-%d %H:%M:%S")


def test_skip_to_end_does_not_collapse_an_outage_entirely_within_a_quiet_stretch(qapp, tmp_path):
    """Found in review: without periodic ticking during a bulk fast-forward,
    a real multi-minute outage with no AIS traffic at all during it (only
    GNSS chatter, which doesn't drive update_target_tree()'s own ticking)
    got its AMBER/RED transition timestamps collapsed to the exact instant
    of the resuming report — a zero-width, invisible segment on the uptime
    bar — instead of reflecting when the outage actually started."""

    # A short-enough gap that trim_vessel_uptime (10-minute default track
    # length) won't have discarded the earlier change points by the time
    # skip_to_end finishes, so the full RED span is still visible here.
    log_path = write_gap_log(tmp_path, gap_minutes=5)

    window = MainWindow()
    window.replay.load_file(log_path)
    window.replay.filename = log_path

    window.skip_to_end_clicked()

    vessel = next(iter(window.registry.vessels.values()))
    segments = vessel.uptime_tracker.segments(window.replay.current_time)

    red_segments = [(start, end) for start, end, state in segments if state == UptimeState.RED]

    assert red_segments, "expected at least one RED segment for the outage"

    red_start, red_end = red_segments[0]

    # The bug produced a zero-width segment (red_start == red_end); a real
    # ~5-minute outage should show as most of that width, not an instant.
    assert (red_end - red_start).total_seconds() > 60
