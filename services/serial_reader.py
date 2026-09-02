import time
import serial
from PySide6.QtCore import QThread, Signal

PARITY_CODES = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}


def parse_serial_format(format_string):
    """"8N1" -> (bytesize=8, parity=serial.PARITY_NONE, stopbits=1)."""

    bytesize = int(format_string[0])
    parity = PARITY_CODES[format_string[1]]
    stopbits = int(format_string[2])

    return bytesize, parity, stopbits


def looks_like_nmea(line):

    line = line.strip()

    if not line or line[0] not in "$!":
        return False

    # Not a full checksum validation — just enough to distinguish "this is
    # shaped like a NMEA/AIS sentence" from random noise, since a short test
    # window isn't guaranteed to catch a full, uncut line anyway.
    return "," in line and "*" in line


class SerialReaderThread(QThread):

    line_received = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, port, baud, serial_format, serial_factory=None):
        super().__init__()

        self.port = port
        self.baud = baud
        self.serial_format = serial_format

        # Injectable so tests can substitute a fake serial connection
        # instead of opening a real port. Resolved here rather than as a
        # default-argument value, since a default is bound once at def-time
        # — before any test's monkeypatch of serial.Serial could apply.
        self.serial_factory = serial_factory or serial.Serial

        # Written only by stop() (main thread), read only by run() (this
        # thread's own run loop) — run() must never write to this, or a
        # stop() call arriving while serial_factory(...) is still (slowly)
        # opening the port gets silently clobbered the instant run()
        # resumes, starting the read loop anyway despite the stop request.
        self._stop_requested = False

    def run(self):

        bytesize, parity, stopbits = parse_serial_format(self.serial_format)

        try:
            connection = self.serial_factory(
                self.port,
                baudrate=self.baud,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=1
            )

        except Exception as e:
            self.error_occurred.emit(str(e))
            return

        while not self._stop_requested:

            try:
                raw = connection.readline()

            except Exception as e:
                self.error_occurred.emit(str(e))
                break

            if not raw:
                continue

            line = raw.decode("ascii", errors="ignore").strip()

            if line:
                self.line_received.emit(line)

        connection.close()

    def stop(self):

        self._stop_requested = True

        self.wait(2000)


class SerialTestThread(QThread):
    """One-shot "does this port actually work" check for the Communications
    dialog's Test button — opens the port, listens for a few seconds, and
    reports back what it saw rather than committing to a full live session.
    """

    test_finished = Signal(dict)

    DURATION_SECONDS = 3

    def __init__(self, port, baud, serial_format, serial_factory=None):
        super().__init__()

        self.port = port
        self.baud = baud
        self.serial_format = serial_format

        self.serial_factory = serial_factory or serial.Serial

    def run(self):

        bytesize, parity, stopbits = parse_serial_format(self.serial_format)

        try:
            connection = self.serial_factory(
                self.port,
                baudrate=self.baud,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=1
            )

        except Exception as e:
            self.test_finished.emit({"success": False, "error": str(e)})
            return

        raw_bytes = bytearray()
        deadline = time.monotonic() + self.DURATION_SECONDS

        try:
            while time.monotonic() < deadline:

                # timeout=1 on the connection bounds each read, so this loop
                # can't overrun the deadline by more than ~1s even if the
                # port never sends anything.
                chunk = connection.read(256)

                if chunk:
                    raw_bytes.extend(chunk)

        except Exception as e:
            connection.close()
            self.test_finished.emit({"success": False, "error": str(e)})
            return

        connection.close()

        # Printable ASCII + CR/LF/TAB is what real NMEA traffic looks like
        # at the byte level — a low ratio here usually means a baud/parity
        # mismatch rather than "no data", since a wrong baud still reads
        # *something*, just garbled.
        printable = sum(1 for b in raw_bytes if 32 <= b <= 126 or b in (9, 10, 13))
        printable_ratio = (printable / len(raw_bytes)) if raw_bytes else 0.0

        text = raw_bytes.decode("ascii", errors="replace")
        found_nmea = any(looks_like_nmea(line) for line in text.splitlines())

        self.test_finished.emit({
            "success": True,
            "error": None,
            "byte_count": len(raw_bytes),
            "printable_ratio": printable_ratio,
            "found_nmea": found_nmea
        })
