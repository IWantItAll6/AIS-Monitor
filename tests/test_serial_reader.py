import time

import serial

from services.serial_reader import SerialReaderThread, SerialTestThread, parse_serial_format, looks_like_nmea


def test_parse_serial_format_covers_common_presets():

    assert parse_serial_format("8N1") == (8, serial.PARITY_NONE, 1)
    assert parse_serial_format("8E1") == (8, serial.PARITY_EVEN, 1)
    assert parse_serial_format("7O1") == (7, serial.PARITY_ODD, 1)


def test_looks_like_nmea():

    assert looks_like_nmea("$GPRMC,123456,A*6A")
    assert looks_like_nmea("!AIVDM,1,1,,A,foo,0*3A")
    assert not looks_like_nmea("random garbage")
    assert not looks_like_nmea("$no checksum or comma")
    assert not looks_like_nmea("")


class FakeSerial:
    """Mimics enough of pyserial's interface to drive SerialReaderThread
    without a real or virtual port."""

    def __init__(self, *args, **kwargs):

        self._lines = [b"$GPRMC,test*00\r\n"]
        self.closed = False

    def readline(self):

        if self._lines:
            return self._lines.pop(0)

        # A real serial port with a read timeout returns b'' when idle
        # rather than blocking forever — mimic that instead of busy-looping.
        time.sleep(0.02)

        return b""

    def close(self):

        self.closed = True


def pump_until(qapp, condition, timeout=2.0):

    # Cross-thread signal/slot connections may be queued, which only
    # deliver while the receiving thread's event loop is being pumped —
    # a plain time.sleep() loop wouldn't necessarily see them arrive.
    deadline = time.time() + timeout

    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    return condition()


def test_reader_thread_emits_received_lines(qapp):

    received = []

    thread = SerialReaderThread("COM_FAKE", 9600, "8N1", serial_factory=FakeSerial)
    thread.line_received.connect(received.append)

    thread.start()

    assert pump_until(qapp, lambda: len(received) >= 1)

    thread.stop()

    assert received == ["$GPRMC,test*00"]


class SlowFakeSerial:
    """A port whose readline() blocks for a while before returning idle —
    long enough that request_stop()/stop() timing is actually observable,
    unlike FakeSerial's near-instant reads."""

    READLINE_DELAY = 0.3

    def __init__(self, *args, **kwargs):
        pass

    def readline(self):

        time.sleep(self.READLINE_DELAY)

        return b""

    def close(self):
        pass


def test_request_stop_does_not_block_the_caller(qapp):

    # Found in review: stop() both signals the run loop to exit AND blocks
    # the caller for up to 2s waiting for it — request_stop() splits out
    # just the signal, so a caller stopping several readers (see
    # MainWindow.stop_live_serial) can request all of them stop before
    # waiting on any, rather than paying each reader's shutdown latency
    # one after another.
    thread = SerialReaderThread("COM_FAKE", 9600, "8N1", serial_factory=SlowFakeSerial)
    thread.start()

    assert pump_until(qapp, lambda: thread.isRunning())

    start = time.monotonic()
    thread.request_stop()
    elapsed = time.monotonic() - start

    assert elapsed < 0.1

    thread.wait(2000)


def test_reader_thread_reports_connection_failure(qapp):

    def failing_factory(*args, **kwargs):
        raise RuntimeError("port not found")

    errors = []

    thread = SerialReaderThread("COM_FAKE", 9600, "8N1", serial_factory=failing_factory)
    thread.error_occurred.connect(errors.append)

    thread.start()

    assert pump_until(qapp, lambda: len(errors) >= 1)


class FakeReadSerial:
    """Mimics enough of pyserial's read() interface to drive
    SerialTestThread without a real or virtual port."""

    def __init__(self, chunks):

        self._chunks = list(chunks)

    def read(self, size):

        if self._chunks:
            return self._chunks.pop(0)

        return b""

    def close(self):
        pass


def run_test_thread(qapp, monkeypatch, factory):

    # Real DURATION_SECONDS (3s) would make every test slow — shrink it,
    # restored automatically by monkeypatch after the test.
    monkeypatch.setattr(SerialTestThread, "DURATION_SECONDS", 0.05)

    results = []

    thread = SerialTestThread("COM_FAKE", 9600, "8N1", serial_factory=factory)
    thread.test_finished.connect(results.append)

    thread.start()

    assert pump_until(qapp, lambda: len(results) >= 1)

    return results[0]


def test_test_thread_reports_connection_failure(qapp, monkeypatch):

    def failing_factory(*args, **kwargs):
        raise RuntimeError("port not found")

    result = run_test_thread(qapp, monkeypatch, failing_factory)

    assert result["success"] is False
    assert "port not found" in result["error"]


def test_test_thread_detects_nmea_sentence(qapp, monkeypatch):

    factory = lambda *a, **kw: FakeReadSerial([b"$GPRMC,test*00\r\n"])

    result = run_test_thread(qapp, monkeypatch, factory)

    assert result["success"] is True
    assert result["byte_count"] > 0
    assert result["found_nmea"] is True


def test_test_thread_reports_no_data(qapp, monkeypatch):

    factory = lambda *a, **kw: FakeReadSerial([])

    result = run_test_thread(qapp, monkeypatch, factory)

    assert result["success"] is True
    assert result["byte_count"] == 0
    assert result["found_nmea"] is False


def test_test_thread_detects_garbled_data(qapp, monkeypatch):

    factory = lambda *a, **kw: FakeReadSerial([bytes(range(20)) * 5])

    result = run_test_thread(qapp, monkeypatch, factory)

    assert result["success"] is True
    assert result["byte_count"] > 0
    assert result["found_nmea"] is False
    assert result["printable_ratio"] < 0.9
