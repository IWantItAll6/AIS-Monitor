import time

import pytest

import services.serial_reader as serial_reader_module
from ui.main_window import MainWindow


class FakeAisSerial:
    """Simulates an AIS receiver on a serial port — one real position report
    sentence, then idle (mirroring how a real port behaves between messages)."""

    def __init__(self, *args, **kwargs):

        self._lines = [b"!AIVDM,1,1,,B,13M@KdU01uOiIf@MGja7q5gp05KL,0*0A\r\n"]

    def readline(self):

        if self._lines:
            return self._lines.pop(0)

        time.sleep(0.02)

        return b""

    def close(self):
        pass


def pump_until(qapp, condition, timeout=3.0):

    deadline = time.time() + timeout

    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    return condition()


@pytest.mark.serial
def test_live_mode_processes_and_records_incoming_lines(qapp, tmp_path, monkeypatch):

    monkeypatch.setattr(serial_reader_module.serial, "Serial", FakeAisSerial)

    window = MainWindow()

    window.recorder.directory = tmp_path / "recordings"
    window.settings["ais_port"] = "COM_FAKE"
    window.settings["ais_baud"] = "38400"
    window.settings["ais_serial_format"] = "8N1"
    window.settings["use_separate_gnss"] = False

    window.start_clicked()

    assert window.current_mode == "Live"
    assert window.recorder.is_recording is True

    assert pump_until(qapp, lambda: len(window.registry.vessels) >= 1)

    window.stop_clicked()

    assert window.current_mode == "Stopped"
    assert window.recorder.is_recording is False
    assert window.serial_readers == []

    recorded_files = list((tmp_path / "recordings").glob("*.log"))

    assert len(recorded_files) == 1
    assert "!AIVDM" in recorded_files[0].read_text(encoding="utf-8")


class SlowFakeSerial:
    """A port whose readline() blocks for a while before returning idle —
    long enough for stop_live_serial()'s overlap-vs-serialize timing to be
    observable."""

    READLINE_DELAY = 0.3

    def __init__(self, *args, **kwargs):
        pass

    def readline(self):

        time.sleep(self.READLINE_DELAY)

        return b""

    def close(self):
        pass


def test_stop_live_serial_overlaps_reader_shutdowns_instead_of_serializing(qapp, tmp_path, monkeypatch):

    # Found in review: SerialReaderThread.stop() blocks its caller (the GUI
    # thread) for up to its shutdown latency, and stop_live_serial() called
    # it in a loop — with separate GNSS enabled (2 readers), a manual Stop
    # paid that latency twice over instead of once, freezing the UI longer
    # than necessary.
    monkeypatch.setattr(serial_reader_module.serial, "Serial", SlowFakeSerial)

    window = MainWindow()

    window.recorder.directory = tmp_path / "recordings"
    window.settings["ais_port"] = "COM_FAKE_AIS"
    window.settings["ais_baud"] = "38400"
    window.settings["ais_serial_format"] = "8N1"
    window.settings["use_separate_gnss"] = True
    window.settings["gnss_port"] = "COM_FAKE_GNSS"
    window.settings["gnss_baud"] = "115200"
    window.settings["gnss_serial_format"] = "8N1"

    window.start_clicked()

    assert len(window.serial_readers) == 2
    assert pump_until(qapp, lambda: all(r.isRunning() for r in window.serial_readers))

    start = time.monotonic()
    window.stop_live_serial()
    elapsed = time.monotonic() - start

    # Serializing two readers' shutdowns would take roughly 2x
    # SlowFakeSerial.READLINE_DELAY; overlapping them keeps it near 1x.
    assert elapsed < SlowFakeSerial.READLINE_DELAY * 1.5


def test_serial_connection_failure_reverts_to_stopped(qapp, tmp_path, monkeypatch):

    def failing_factory(*args, **kwargs):
        raise RuntimeError("could not open port")

    monkeypatch.setattr(serial_reader_module.serial, "Serial", failing_factory)

    window = MainWindow()

    window.recorder.directory = tmp_path / "recordings"
    window.settings["ais_port"] = "COM_DOES_NOT_EXIST"
    window.settings["ais_baud"] = "38400"
    window.settings["ais_serial_format"] = "8N1"
    window.settings["use_separate_gnss"] = False

    window.start_clicked()

    assert pump_until(qapp, lambda: window.current_mode == "Stopped")

    assert window.serial_readers == []
