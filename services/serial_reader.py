import serial
from PySide6.QtCore import QThread, Signal

PARITY_CODES = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}


def parse_serial_format(format_string):
    """"8N1" -> (bytesize=8, parity=serial.PARITY_NONE, stopbits=1)."""

    bytesize = int(format_string[0])
    parity = PARITY_CODES[format_string[1]]
    stopbits = int(format_string[2])

    return bytesize, parity, stopbits


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

        self._running = False

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

        self._running = True

        while self._running:

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

        self._running = False

        self.wait(2000)
