from services.session_recorder import SessionRecorder


def test_recorder_writes_lines_to_a_new_file(tmp_path):

    recorder = SessionRecorder(directory=tmp_path / "recordings")

    assert recorder.is_recording is False

    recorder.start()

    assert recorder.is_recording is True
    assert recorder.path.exists()

    recorder.write("[2026-01-01 00:00:00.000] $TEST,1*00")
    recorder.write("!AIVDM,1,1,,,dummy,0*00")

    written_path = recorder.path

    recorder.stop()

    assert recorder.is_recording is False
    assert recorder.path is None

    content = written_path.read_text(encoding="utf-8")

    assert "$TEST,1*00" in content
    assert "!AIVDM" in content


def test_write_before_start_is_a_silent_noop(tmp_path):

    recorder = SessionRecorder(directory=tmp_path / "recordings")

    recorder.write("nothing should happen")

    assert not (tmp_path / "recordings").exists()
