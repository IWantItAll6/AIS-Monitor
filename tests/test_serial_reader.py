import time

import serial

from services.serial_reader import SerialReaderThread, parse_serial_format


def test_parse_serial_format_covers_common_presets():

    assert parse_serial_format("8N1") == (8, serial.PARITY_NONE, 1)
    assert parse_serial_format("8E1") == (8, serial.PARITY_EVEN, 1)
    assert parse_serial_format("7O1") == (7, serial.PARITY_ODD, 1)


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


def test_reader_thread_reports_connection_failure(qapp):

    def failing_factory(*args, **kwargs):
        raise RuntimeError("port not found")

    errors = []

    thread = SerialReaderThread("COM_FAKE", 9600, "8N1", serial_factory=failing_factory)
    thread.error_occurred.connect(errors.append)

    thread.start()

    assert pump_until(qapp, lambda: len(errors) >= 1)
