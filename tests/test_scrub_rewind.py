from datetime import datetime, timedelta

from pyais.encode import encode_dict

from ui.main_window import MainWindow


def ais_sentence(mmsi, lat, lon):

    return encode_dict({"type": 1, "mmsi": mmsi, "lat": lat, "lon": lon, "speed": 5.0}, sentence_type="VDM")[0]


def write_log(tmp_path, entries):

    path = tmp_path / "scrub.log"

    lines = [f"[{ts:%Y-%m-%d %H:%M:%S.%f}] {sentence}" for ts, sentence in entries]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return str(path)


ONLY_AT_START_MMSI = 111111111
NEAR_TARGET_MMSI = 222222222


def build_60_minute_log(tmp_path):
    """A vessel seen only at t=0, another seen at t=0 and again 5 minutes
    before the target — with the default 10-minute Track Length/Vessel
    Timeout, seeking to the end should keep the second vessel (its last
    report is inside the rewind window) but lose the first (its only
    report is 60 minutes before the target, well outside it) — exactly
    what continuous playback would also show, since a real 10-minute
    Vessel Timeout would have dropped that vessel from the list long
    before the target regardless of how it got there."""

    start = datetime(2026, 1, 1, 0, 0, 0)

    entries = [
        (start, ais_sentence(ONLY_AT_START_MMSI, 50.0, -2.0)),
        (start, ais_sentence(NEAR_TARGET_MMSI, 50.0, -2.0)),
        (start + timedelta(minutes=55), ais_sentence(NEAR_TARGET_MMSI, 50.1, -2.1)),
        (start + timedelta(minutes=60), ais_sentence(NEAR_TARGET_MMSI, 50.2, -2.2)),
    ]

    return write_log(tmp_path, entries)


def test_scrub_rewind_seconds_is_the_wider_of_track_length_and_vessel_timeout(qapp):

    window = MainWindow()

    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "25"
    assert window.scrub_rewind_seconds() == 25 * 60

    window.settings["track_length"] = "40"
    window.settings["vessel_timeout"] = "25"
    assert window.scrub_rewind_seconds() == 40 * 60


def test_scrub_rewind_seconds_is_none_when_either_setting_is_unlimited(qapp):

    window = MainWindow()

    window.settings["track_length"] = "Unlimited"
    window.settings["vessel_timeout"] = "10"
    assert window.scrub_rewind_seconds() is None

    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "Unlimited"
    assert window.scrub_rewind_seconds() is None


def test_bounded_seek_drops_a_vessel_whose_only_report_is_outside_the_window(qapp, tmp_path):

    window = MainWindow()
    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "10"
    window.animate_scrub_checkbox.setChecked(False)

    log_path = build_60_minute_log(tmp_path)
    window.replay.load_file(log_path)
    window.replay.filename = log_path

    window.seek_to_index(len(window.replay.lines) - 1)

    assert window.registry.get(NEAR_TARGET_MMSI) is not None
    assert window.registry.get(ONLY_AT_START_MMSI) is None


def test_bounded_seek_skips_over_an_unparseable_leading_line(qapp, tmp_path):
    """Found against a real trial log: it opens with a single blank line
    before its first real timestamped entry. The rewind scan used to treat
    the first unparseable line as the boundary itself and stop dead there,
    always landing rewind_start_index at 0 — silently defeating the whole
    optimization (falling back to a full from-zero replay) for any file
    with so much as one bad line near the start. It must skip over an
    unparseable line and keep scanning instead."""

    log_path = build_60_minute_log(tmp_path)

    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n" + content)

    window = MainWindow()
    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "10"
    window.animate_scrub_checkbox.setChecked(False)

    window.replay.load_file(log_path)
    window.replay.filename = log_path

    window.seek_to_index(len(window.replay.lines) - 1)

    # Same assertion as the bounded-rewind test above — if the leading
    # blank line broke the scan, this vessel (only reported 60 minutes
    # before the target) would still be present.
    assert window.registry.get(NEAR_TARGET_MMSI) is not None
    assert window.registry.get(ONLY_AT_START_MMSI) is None


def test_unlimited_setting_falls_back_to_a_full_replay_from_the_start(qapp, tmp_path):

    window = MainWindow()
    window.settings["track_length"] = "Unlimited"
    window.settings["vessel_timeout"] = "Unlimited"
    window.animate_scrub_checkbox.setChecked(False)

    log_path = build_60_minute_log(tmp_path)
    window.replay.load_file(log_path)
    window.replay.filename = log_path

    window.seek_to_index(len(window.replay.lines) - 1)

    # With no bounded window, both vessels survive — matches today's
    # (pre-optimization) exact-reconstruction behavior.
    assert window.registry.get(NEAR_TARGET_MMSI) is not None
    assert window.registry.get(ONLY_AT_START_MMSI) is not None


def test_warns_once_for_a_large_file_with_an_unlimited_setting(qapp, monkeypatch, tmp_path):

    window = MainWindow()
    window.settings["track_length"] = "Unlimited"
    window.settings["vessel_timeout"] = "10"

    window.LARGE_FILE_LINE_THRESHOLD = 3  # keep the synthetic log small

    warnings = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *a, **kw: warnings.append(a)
    )

    log_path = build_60_minute_log(tmp_path)  # 4 lines >= threshold of 3
    window.load_replay_file(log_path)

    assert len(warnings) == 1


def test_no_warning_with_bounded_settings_on_a_sparse_file(qapp, monkeypatch, tmp_path):
    """build_60_minute_log's 4 lines spread across a full hour are sparse
    enough that even a low LARGE_FILE_LINE_THRESHOLD shouldn't trigger a
    warning once the estimate is scoped to just the rewind window (10
    minutes of that hour) instead of the file's total line count."""

    window = MainWindow()
    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "10"

    window.LARGE_FILE_LINE_THRESHOLD = 3

    warnings = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *a, **kw: warnings.append(a)
    )

    log_path = build_60_minute_log(tmp_path)
    window.load_replay_file(log_path)

    assert warnings == []


def test_warns_for_a_bounded_but_dense_file_even_without_unlimited(qapp, monkeypatch, tmp_path):
    """A bounded Track Length/Vessel Timeout isn't automatically fast — on
    a dense enough capture, the window itself can still contain a lot of
    lines (matches the real-world case discussed: a 60-minute setting on a
    busy file could still take tens of seconds per scrub). The warning
    should catch this even though nothing here is "Unlimited"."""

    start = datetime(2026, 1, 1, 0, 0, 0)

    # 100 lines packed into the same 600s (10-minute) span the default
    # Track Length/Vessel Timeout would rewind by — density alone should
    # make the estimate ~100 lines.
    entries = [
        (start + timedelta(seconds=6 * i), ais_sentence(NEAR_TARGET_MMSI, 50.0, -2.0))
        for i in range(100)
    ]

    window = MainWindow()
    window.settings["track_length"] = "10"
    window.settings["vessel_timeout"] = "10"

    window.LARGE_FILE_LINE_THRESHOLD = 50

    warnings = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *a, **kw: warnings.append(a)
    )

    log_path = write_log(tmp_path, entries)
    window.load_replay_file(log_path)

    assert len(warnings) == 1

    # The message shouldn't blame "Unlimited" for a case that isn't.
    _self, _title, message_text = warnings[0]
    assert "Unlimited" not in message_text
    assert "roughly" in message_text


def test_no_warning_for_a_small_file_even_with_an_unlimited_setting(qapp, monkeypatch, tmp_path):

    window = MainWindow()
    window.settings["track_length"] = "Unlimited"
    window.settings["vessel_timeout"] = "Unlimited"

    window.LARGE_FILE_LINE_THRESHOLD = 100  # the synthetic log's 4 lines stay under this

    warnings = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *a, **kw: warnings.append(a)
    )

    log_path = build_60_minute_log(tmp_path)
    window.load_replay_file(log_path)

    assert warnings == []
