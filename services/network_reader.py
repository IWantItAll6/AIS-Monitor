import socket
import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QTcpSocket

from services.serial_reader import analyze_reception


class NetworkAisReader(QObject):
    """Reads NMEA/AIS lines from a TCP connection — the network-source
    counterpart to SerialReaderThread, for AIS receivers that expose their
    data over WiFi/TCP instead of a serial port. Mutually exclusive with the
    serial AIS source (settings["ais_source_type"]), never both at once —
    see MainWindow.make_ais_reader().

    Not a QThread: QTcpSocket is already asynchronous within Qt's event
    loop, so nothing here needs a background thread the way pyserial's
    blocking readline() requires for SerialReaderThread.
    """

    line_received = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, host, port, socket_factory=None):

        super().__init__()

        self.host = host
        self.port = port

        # Injectable so tests can substitute a fake socket instead of a
        # real QTcpSocket — same seam as serial_reader.py's serial_factory.
        self._socket_factory = socket_factory or QTcpSocket

        self.socket = None
        self._buffer = b""

    def start(self):

        self.socket = self._socket_factory()
        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.errorOccurred.connect(self._on_socket_error)

        self.socket.connectToHost(self.host, self.port)

    def _on_ready_read(self):

        self._buffer += bytes(self.socket.readAll().data())

        # A TCP stream has no message framing of its own — split on
        # newlines the same way SerialReaderThread's line-oriented
        # readline() effectively does, since a sentence can arrive split
        # across more than one readyRead.
        while b"\n" in self._buffer:

            line, self._buffer = self._buffer.split(b"\n", 1)
            text = line.decode("ascii", errors="ignore").strip()

            if text:
                self.line_received.emit(text)

    def _on_socket_error(self, socket_error):

        self.error_occurred.emit(self.socket.errorString())

    def request_stop(self):

        if self.socket is not None:
            self.socket.disconnectFromHost()

    def wait(self, timeout_ms=2000):

        # Not a thread — nothing to actually wait on. Kept only so this
        # satisfies the same interface stop_live_serial() calls uniformly
        # on every reader in self.serial_readers, whether serial- or
        # network-backed.
        return True

    def stop(self):

        self.request_stop()


class NetworkTestThread(QThread):
    """One-shot "does this host:port actually have AIS data" check for the
    Communications dialog's network Test button — mirrors SerialTestThread's
    interface and behavior, just over a plain TCP socket instead of a
    serial port."""

    test_finished = Signal(dict)

    DURATION_SECONDS = 3

    def __init__(self, host, port, connect_factory=None):

        super().__init__()

        self.host = host
        self.port = port

        # Injectable so tests can substitute a fake connection instead of a
        # real socket.
        self._connect_factory = connect_factory or (
            lambda host, port, timeout: socket.create_connection((host, port), timeout=timeout)
        )

    def run(self):

        try:
            connection = self._connect_factory(self.host, self.port, 3)

        except Exception as e:
            self.test_finished.emit({"success": False, "error": str(e)})
            return

        connection.settimeout(1)

        raw_bytes = bytearray()
        deadline = time.monotonic() + self.DURATION_SECONDS

        try:
            while time.monotonic() < deadline:

                try:
                    chunk = connection.recv(256)

                except socket.timeout:
                    continue

                if not chunk:
                    break

                raw_bytes.extend(chunk)

        except Exception as e:
            connection.close()
            self.test_finished.emit({"success": False, "error": str(e)})
            return

        connection.close()

        self.test_finished.emit(analyze_reception(raw_bytes))
