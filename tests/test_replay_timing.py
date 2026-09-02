import time

from PySide6.QtCore import QEventLoop, QTimer

from ui.main_window import MainWindow


def pump_event_loop_for(ms):

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_replay_paces_by_real_elapsed_time_between_batches(qapp, tmp_path, monkeypatch):

    # Reaching end-of-file pops a modal QMessageBox — fine for a real user,
    # but pump_event_loop_for() below runs a real Qt event loop with no one
    # to dismiss it, which would hang the test indefinitely if it fired.
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: None)

    # Two lines sharing a timestamp (should play together, no wait between
    # them), then a third 400ms later (should genuinely wait ~400ms real
    # time before playing, at 1x) — locks in the timestamp-accurate pacing
    # replacing the old fixed lines-per-second model. A trailing 4th line,
    # far off, keeps has_next() true after C so reaching it doesn't trigger
    # end-of-file's auto-reset-to-start before the assertions below run.
    log_file = tmp_path / "timing.log"
    log_file.write_text(
        "[2026-01-01 08:00:00.000] TEST_LINE_A\n"
        "[2026-01-01 08:00:00.000] TEST_LINE_B\n"
        "[2026-01-01 08:00:00.400] TEST_LINE_C\n"
        "[2026-01-01 08:05:00.000] TEST_LINE_D\n"
    )

    window = MainWindow()
    window.replay.load_file(str(log_file))
    window.replay.filename = str(log_file)

    wall_start = time.monotonic()
    window.start_clicked()

    # Both same-timestamp lines consumed in the same, immediate batch.
    assert window.replay.index == 2

    # Not yet past the 400ms gap to the third line.
    pump_event_loop_for(150)
    assert window.replay.index == 2

    pump_event_loop_for(500)
    elapsed_ms = (time.monotonic() - wall_start) * 1000

    assert window.replay.index == 3
    # ~400ms expected; wide margin — a full-suite run showed this can slip
    # past 1s under system load, and the property actually worth locking in
    # is "genuinely waited, roughly the right order of magnitude", not
    # tight precision.
    assert 300 < elapsed_ms < 3000

    window.stop_clicked()


def test_replay_speed_multiplier_scales_real_wait(qapp, tmp_path, monkeypatch):

    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: None)

    # Trailing 3rd line, far off, keeps has_next() true after B so reaching
    # it doesn't trigger end-of-file's auto-reset-to-start before the
    # assertions below run.
    log_file = tmp_path / "timing_fast.log"
    log_file.write_text(
        "[2026-01-01 08:00:00.000] TEST_LINE_A\n"
        "[2026-01-01 08:00:01.000] TEST_LINE_B\n"
        "[2026-01-01 08:05:00.000] TEST_LINE_C\n"
    )

    window = MainWindow()
    window.replay.load_file(str(log_file))
    window.replay.filename = str(log_file)

    for _ in range(9):  # 1x -> 10x
        window.faster_clicked()

    assert window.replay.speed == 10

    wall_start = time.monotonic()
    window.start_clicked()

    assert window.replay.index == 1

    # At 10x, a real 1000ms gap should collapse to ~100ms — comfortably
    # done well before the un-sped-up 1000ms would have been.
    pump_event_loop_for(400)
    elapsed_ms = (time.monotonic() - wall_start) * 1000

    assert window.replay.index == 2
    assert elapsed_ms < 1000

    window.stop_clicked()


def test_pause_then_resume_preserves_remaining_wait_instead_of_playing_instantly(qapp, tmp_path, monkeypatch):

    # Found in review: resuming from Pause always called replay_next_line()
    # directly, playing whatever batch was pending instantly regardless of
    # how much of its real-time wait remained — silently fast-forwarding
    # through the log and undermining the "1x means real time" pacing this
    # whole module otherwise locks in.
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: None)

    log_file = tmp_path / "pause_resume.log"
    log_file.write_text(
        "[2026-01-01 08:00:00.000] TEST_LINE_A\n"
        "[2026-01-01 08:00:01.000] TEST_LINE_B\n"
        "[2026-01-01 08:05:00.000] TEST_LINE_C\n"
    )

    window = MainWindow()
    window.replay.load_file(str(log_file))
    window.replay.filename = str(log_file)

    window.start_clicked()
    assert window.replay.index == 1

    # Still well within the ~1000ms wait for line B.
    pump_event_loop_for(150)
    assert window.replay.index == 1

    window.pause_clicked()
    assert window._paused_remaining_ms is not None and window._paused_remaining_ms > 0

    # However long we wait here, the remaining wait doesn't burn down while
    # paused — the timer is genuinely stopped, not just ignored.
    pump_event_loop_for(500)
    assert window.replay.index == 1

    window.start_clicked()

    # Resuming shouldn't play line B instantly...
    pump_event_loop_for(100)
    assert window.replay.index == 1

    # ...but should still play it soon after, honoring roughly the
    # remaining wait rather than either "instantly" or "the full original".
    pump_event_loop_for(1500)
    assert window.replay.index == 2

    window.stop_clicked()
