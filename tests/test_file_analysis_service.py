import os
import threading
import time
from datetime import datetime, timedelta

import pytest
from pyais.encode import encode_dict

import services.file_analysis_service as file_analysis_service
from services.file_analysis_service import (
    analyze_file, extract_rssi_history, format_duration, VesselAnalysis, FileAnalysisThread
)

SAMPLE_LOG = "resources/sample_replay.log"

# Private field-test logs, same convention/skip behavior as
# tests/test_replay_regression.py — not committed to the repo.
FIELD_LOG_1 = "resources/field_log_1.txt"
FIELD_LOG_2 = "resources/field_log_2.log"


def test_format_duration_under_an_hour():

    assert format_duration(125) == "2m 05s"


def test_format_duration_an_hour_or_more():

    assert format_duration(3725) == "1h 02m"


def test_vessel_analysis_derived_properties_with_no_samples():

    analysis = VesselAnalysis(mmsi=123456789)

    assert analysis.duration_seconds == 0
    assert analysis.avg_rssi is None
    assert analysis.avg_speed is None


@pytest.fixture(scope="module")
def sample_analyses():

    return analyze_file(SAMPLE_LOG)


def test_analyze_file_excludes_own_ship(sample_analyses):

    # 9 total entities appear in the live target list for this same file
    # (see test_sample_replay.py) — 4 vessels, a base station, 2 AtoNs, a
    # SART beacon, and the synthetic own-ship AIVDO echo. Own-ship isn't a
    # received target, so it must not appear here.
    OWN_MMSI = 999000000

    assert len(sample_analyses) == 8
    assert all(a.mmsi != OWN_MMSI for a in sample_analyses)


def test_analyze_file_sorts_by_mmsi(sample_analyses):

    mmsis = [a.mmsi for a in sample_analyses]

    assert mmsis == sorted(mmsis)


def test_analyze_file_captures_name_and_callsign(sample_analyses):

    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)

    assert vessel_one.name == "SAMPLE VESSEL ONE"
    assert vessel_one.callsign == "ZZ1001"
    assert vessel_one.tx_count > 1


def test_analyze_file_computes_avg_speed_close_to_the_constant_sog(sample_analyses):

    # SAMPLE VESSEL ONE holds a constant 18.0kn course/speed throughout the
    # generated scenario (see scripts/generate_sample_log.py) — avg_speed
    # over all its position reports should land right on that.
    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)

    assert vessel_one.avg_speed == pytest.approx(18.0, abs=0.01)


def test_analyze_file_accumulates_distance_traveled(sample_analyses):

    # A moving vessel logged for the full 180s scenario at 18kn travels a
    # known, non-trivial distance — a stationary AtoN/base station (a
    # single one-time position report, no second point to diff against)
    # should show exactly zero.
    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)
    assert vessel_one.distance_traveled_nm > 0.5

    lighthouse = next(a for a in sample_analyses if a.mmsi == 992320001)
    assert lighthouse.distance_traveled_nm == 0.0


def test_analyze_file_computes_rssi_min_max_avg(sample_analyses):

    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)

    assert vessel_one.rssi_min is not None
    assert vessel_one.rssi_max is not None
    assert vessel_one.rssi_min <= vessel_one.avg_rssi <= vessel_one.rssi_max


def test_analyze_file_computes_range_from_own_position(sample_analyses):

    # Own-ship has a resolved GNSS fix throughout this scenario (see
    # test_sample_replay_own_position_resolves) — every vessel should end
    # up with a real closest/furthest range, not None.
    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)

    assert vessel_one.range_min_nm is not None
    assert vessel_one.range_max_nm is not None
    assert vessel_one.range_min_nm <= vessel_one.range_max_nm


def test_analyze_file_first_seen_before_last_seen(sample_analyses):

    vessel_one = next(a for a in sample_analyses if a.mmsi == 999000001)

    assert vessel_one.first_seen < vessel_one.last_seen
    assert vessel_one.duration_seconds > 0


def test_analyze_file_stationary_station_has_no_avg_speed(sample_analyses):

    # Base stations/AtoNs don't carry a speed field at all — distinct from
    # a vessel that reports speed 0 (anchored), which would still average
    # to a real 0.0, not None.
    lighthouse = next(a for a in sample_analyses if a.mmsi == 992320001)

    assert lighthouse.avg_speed is None


@pytest.mark.parametrize("field_log", [FIELD_LOG_1, FIELD_LOG_2])
def test_analyze_real_field_log_raises_no_errors_and_produces_plausible_output(field_log):

    if not os.path.exists(field_log):
        pytest.skip(f"{field_log} not present — real field logs aren't in the repo")

    analyses = analyze_file(field_log)

    assert len(analyses) > 0

    for a in analyses:

        assert a.tx_count > 0
        assert a.duration_seconds >= 0

        if a.rssi_count:
            assert a.rssi_min <= a.avg_rssi <= a.rssi_max


def test_analyze_file_returns_none_when_cancelled_before_it_starts():

    # A pre-set event guarantees cancellation is caught on the very first
    # loop iteration — deterministic, unlike trying to race a real
    # in-flight cancel against however fast the file happens to parse.
    cancel_event = threading.Event()
    cancel_event.set()

    assert analyze_file(SAMPLE_LOG, cancel_event=cancel_event) is None


def test_analyze_file_reports_progress_up_to_completion():

    calls = []

    analyze_file(SAMPLE_LOG, progress_callback=lambda done, total: calls.append((done, total)), progress_interval=100)

    assert calls, "progress_callback should fire at least once (the guaranteed final call)"

    # Every call reports the same total, and the last call reports full
    # completion — callers (FileAnalysisThread's progress bar) rely on this
    # to know when to show 100%.
    total = calls[0][1]
    assert all(t == total for _, t in calls)
    assert calls[-1] == (total, total)


def pump_until(qapp, condition, timeout=2.0):

    deadline = time.time() + timeout

    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    return condition()


def test_file_analysis_thread_emits_finished_analysis_on_success(qapp, monkeypatch):

    expected = [VesselAnalysis(mmsi=123456789)]
    monkeypatch.setattr(file_analysis_service, "analyze_file", lambda *a, **kw: expected)

    results = []

    thread = FileAnalysisThread("irrelevant.log")
    thread.finished_analysis.connect(results.append)

    thread.start()

    assert pump_until(qapp, lambda: len(results) >= 1)
    assert results[0] == expected


def write_log(tmp_path, entries):
    """entries: [(datetime, sentence), ...] -> a "[timestamp] sentence"
    file matching this app's replay/recording format, returns its path."""

    path = tmp_path / "synthetic.log"

    lines = [f"[{ts:%Y-%m-%d %H:%M:%S.%f}] {sentence}" for ts, sentence in entries]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return str(path)


def ais_sentence(msg_type, mmsi, lat, lon, speed, cs=None):

    fields = {"type": msg_type, "mmsi": mmsi, "lat": lat, "lon": lon, "speed": speed}

    if cs is not None:
        fields["cs"] = cs

    return encode_dict(fields, sentence_type="VDM")[0]


def static_data_sentence(mmsi, shipname):
    """Type 24 Part A ("Static Data Report") — unlike type 5, this fits in
    a single sentence, which is all write_log()'s one-line-per-entry format
    needs to carry a shipname."""

    return encode_dict({"type": 24, "mmsi": mmsi, "shipname": shipname, "partno": 0}, sentence_type="VDM")[0]


def psmt_sentence(rssi):

    return f"$PSMT,,,,,,,,,,{rssi},*00"


def test_estimate_tx_loss_runs_by_default(tmp_path):

    # No estimate_tx_loss flag to opt into anymore — measured to add no
    # meaningful runtime cost, so it always runs (see analyze_file's
    # docstring). Zero-vs-one report never produces a comparable gap, so
    # expected_tx/estimated_tx_loss_percent correctly stay at "no data yet"
    # even though the calculation ran.
    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))
    vessel = analyses[0]

    assert vessel.position_report_count == 1
    assert vessel.expected_tx == 0.0
    assert vessel.estimated_tx_loss_percent is None


def test_estimate_tx_loss_class_a(tmp_path):

    # 10kn -> 10s nominal interval (see ais_reporting_intervals). Two
    # reports 100s apart -> 10 expected, only 2 actually received -> 80%
    # estimated loss.
    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
        (start + timedelta(seconds=100), ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))
    vessel = next(a for a in analyses if a.mmsi == 111111111)

    assert vessel.position_report_count == 2
    assert vessel.expected_tx == pytest.approx(10.0)
    assert vessel.estimated_tx_loss_percent == pytest.approx(80.0)


def test_estimate_tx_loss_class_b_sotdma(tmp_path):

    # 5kn Class B SOTDMA (cs=False) -> 30s nominal interval. 60s gap -> 2
    # expected, 2 actual -> 0% loss.
    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(18, 222222222, 50.0, -5.0, 5.0, cs=False)),
        (start + timedelta(seconds=60), ais_sentence(18, 222222222, 50.0, -5.0, 5.0, cs=False)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))
    vessel = next(a for a in analyses if a.mmsi == 222222222)

    assert vessel.expected_tx == pytest.approx(2.0)
    assert vessel.position_report_count == 2
    assert vessel.estimated_tx_loss_percent == pytest.approx(0.0)


def test_estimate_tx_loss_class_b_cs_can_go_negative(tmp_path):

    # 5kn Class B CS (cs=True) -> 30s nominal interval, but these two
    # reports arrive only 15s apart — faster than modeled, so loss is
    # negative rather than clamped to 0. Deliberate: a negative value is
    # the approximation's own visible signal (see estimated_tx_loss_percent's
    # docstring), not something to hide.
    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(18, 333333333, 50.0, -5.0, 5.0, cs=True)),
        (start + timedelta(seconds=15), ais_sentence(18, 333333333, 50.0, -5.0, 5.0, cs=True)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))
    vessel = next(a for a in analyses if a.mmsi == 333333333)

    assert vessel.expected_tx == pytest.approx(0.5)
    assert vessel.position_report_count == 2
    assert vessel.estimated_tx_loss_percent == pytest.approx(-300.0)


def test_estimate_tx_loss_relaxes_for_sustained_low_speed_without_anchored_status(tmp_path):
    """Found in review: this call site didn't track/pass sustained_low_speed
    at all, so a Class A vessel sitting still with nav_status stuck at its
    default (not AtAnchor/Moored) got the strict 10s expected interval here
    even after 120s+, while the live VesselUptimeTracker for the exact same
    data would have already relaxed to the anchored 180s rate — the two
    would silently disagree about the same vessel's same recorded session."""

    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        # Report 1 (t=0): first ever at 0kn - streak just starting, not
        # sustained yet -> 10s nominal, sets the interval used for gap 1->2.
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 0.0)),
        # Report 2 (t=130): 130s into the streak, past
        # SUSTAINED_LOW_SPEED_SECONDS (120) -> 180s nominal, sets the
        # interval used for gap 2->3.
        (start + timedelta(seconds=130), ais_sentence(1, 111111111, 50.0, -5.0, 0.0)),
        # Report 3 (t=310): 180s after report 2.
        (start + timedelta(seconds=310), ais_sentence(1, 111111111, 50.0, -5.0, 0.0)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))
    vessel = next(a for a in analyses if a.mmsi == 111111111)

    # gap 1->2: 130s / 10s (report 1's interval) = 13.0
    # gap 2->3: 180s / 180s (report 2's interval, now relaxed) = 1.0
    # Without the fix, gap 2->3 would instead be 180s / 10s = 18.0.
    assert vessel.expected_tx == pytest.approx(14.0)


def test_estimate_tx_loss_ignores_unmodeled_message_types(tmp_path):

    # A base station (type 4) report sitting between two Class A position
    # reports must not be counted as a comparable report, or distort the
    # gap either as an endpoint or by inflating position_report_count.
    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
        (start + timedelta(seconds=50), ais_sentence(4, 444444444, 50.1, -5.1, 0.0)),
        (start + timedelta(seconds=100), ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))

    vessel = next(a for a in analyses if a.mmsi == 111111111)
    assert vessel.position_report_count == 2
    assert vessel.expected_tx == pytest.approx(10.0)

    base_station = next(a for a in analyses if a.mmsi == 444444444)
    assert base_station.position_report_count == 0
    assert base_station.estimated_tx_loss_percent is None


def test_file_analysis_thread_emits_cancelled_when_analyze_file_returns_none(qapp, monkeypatch):

    monkeypatch.setattr(file_analysis_service, "analyze_file", lambda *a, **kw: None)

    cancelled = []

    thread = FileAnalysisThread("irrelevant.log")
    thread.cancelled.connect(lambda: cancelled.append(True))

    thread.start()

    assert pump_until(qapp, lambda: len(cancelled) >= 1)


def test_analyze_file_accumulates_track_history(tmp_path):

    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
        (start + timedelta(seconds=10), ais_sentence(1, 111111111, 50.01, -5.01, 10.0)),
    ]

    vessel = analyze_file(write_log(tmp_path, entries))[0]

    assert vessel.track == [
        (start, 50.0, -5.0),
        (start + timedelta(seconds=10), 50.01, -5.01),
    ]


def test_analyze_file_splits_reused_mmsi_by_name(tmp_path):
    """Field trials reuse one MMSI across differently-named test vessels
    within a single file — each name must get its own independent row, not
    one row with merged stats."""

    start = datetime(2026, 1, 1, 0, 0, 0)
    mmsi = 111111111

    entries = [
        (start, static_data_sentence(mmsi, "ALPHA")),
        (start + timedelta(seconds=10), ais_sentence(1, mmsi, 50.0, -5.0, 10.0)),
        (start + timedelta(minutes=30), static_data_sentence(mmsi, "BRAVO")),
        (start + timedelta(minutes=30, seconds=10), ais_sentence(1, mmsi, 51.0, -6.0, 5.0)),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))

    assert [a.name for a in analyses] == ["ALPHA", "BRAVO"]
    assert all(a.mmsi == mmsi for a in analyses)

    alpha, bravo = analyses

    assert alpha.tx_count == 2
    assert alpha.position_report_count == 1
    assert alpha.first_seen == start

    assert bravo.tx_count == 2
    assert bravo.position_report_count == 1
    assert bravo.first_seen == start + timedelta(minutes=30)

    # Independent stats — BRAVO's report must not have touched ALPHA's.
    assert alpha.distance_traveled_nm == 0.0
    assert bravo.distance_traveled_nm == 0.0


def test_analyze_file_merges_blank_name_leadin_into_first_name(tmp_path):
    """A position report arriving before any static-data message is normal
    (Class B, or static data just hasn't come round yet) — not a
    "different vessel" the way an actual name change is, so it must land
    under the eventual real name rather than staying its own permanent
    blank-name row."""

    start = datetime(2026, 1, 1, 0, 0, 0)
    mmsi = 111111111

    entries = [
        (start, ais_sentence(1, mmsi, 50.0, -5.0, 10.0)),
        (start + timedelta(seconds=30), static_data_sentence(mmsi, "ALPHA")),
    ]

    analyses = analyze_file(write_log(tmp_path, entries))

    assert len(analyses) == 1

    vessel = analyses[0]
    assert vessel.name == "ALPHA"
    assert vessel.tx_count == 2
    assert vessel.position_report_count == 1
    assert vessel.first_seen == start


def test_extract_rssi_history_scoped_to_one_mmsi(tmp_path):

    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(1, 111111111, 50.0, -5.0, 10.0)),
        (start, psmt_sentence(-70)),
        (start + timedelta(seconds=10), ais_sentence(1, 222222222, 51.0, -6.0, 5.0)),
        (start + timedelta(seconds=10), psmt_sentence(-90)),
        (start + timedelta(seconds=20), ais_sentence(1, 111111111, 50.01, -5.01, 10.0)),
        (start + timedelta(seconds=20), psmt_sentence(-72)),
    ]

    path = write_log(tmp_path, entries)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    history = extract_rssi_history(lines, 111111111)

    assert history == [(start, -70), (start + timedelta(seconds=20), -72)]


def test_file_analysis_thread_emits_failed_on_exception(qapp, monkeypatch):

    def raise_error(*args, **kwargs):
        raise RuntimeError("bad file")

    monkeypatch.setattr(file_analysis_service, "analyze_file", raise_error)

    errors = []

    thread = FileAnalysisThread("irrelevant.log")
    thread.failed.connect(errors.append)

    thread.start()

    assert pump_until(qapp, lambda: len(errors) >= 1)
    assert "bad file" in errors[0]
