import os
import threading
import time
from datetime import datetime, timedelta

import pytest

import services.file_analysis_service as file_analysis_service
from services.file_analysis_service import analyze_file, format_duration, VesselAnalysis, FileAnalysisThread

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


def test_file_analysis_thread_emits_cancelled_when_analyze_file_returns_none(qapp, monkeypatch):

    monkeypatch.setattr(file_analysis_service, "analyze_file", lambda *a, **kw: None)

    cancelled = []

    thread = FileAnalysisThread("irrelevant.log")
    thread.cancelled.connect(lambda: cancelled.append(True))

    thread.start()

    assert pump_until(qapp, lambda: len(cancelled) >= 1)


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
