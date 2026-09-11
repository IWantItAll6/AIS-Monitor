import socket
import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QTcpSocket

from services.serial_reader import analyze_reception

# Telnet (RFC 854) control bytes. Most "NMEA over TCP" receivers just
# stream a raw byte feed on whatever port — testing one with a telnet
# client (as opposed to a real telnet *server*) works fine precisely
# because there's no actual telnet protocol involved, only a convenient
# generic TCP terminal. But a device that genuinely runs telnet protocol
# would send IAC option-negotiation sequences unsolicited, and this app
# never replies to them (it isn't a telnet client) — left alone, those
# sequences would otherwise corrupt whichever NMEA sentence they land
# next to: the IAC byte itself (0xFF) is non-ASCII and gets silently
# dropped by the ascii/errors="ignore" decode below, but the option code
# that follows it (e.g. ECHO=1, SUPPRESS-GO-AHEAD=3) is valid low-ASCII
# and would survive, embedded as a stray control character.
IAC = 0xFF
SE = 240
SB = 250


def strip_telnet_negotiation(data):
    """Removes complete IAC negotiation/subnegotiation sequences from a raw
    byte buffer. Returns (cleaned, remainder) — remainder holds the tail
    starting at an IAC sequence that hasn't fully arrived yet (or b"" if
    none), left for the next call to retry once more data comes in, the
    same "wait for the rest" idea as the line-buffering this feeds into."""

    result = bytearray()
    i = 0
    n = len(data)

    while i < n:

        if data[i] != IAC:
            result.append(data[i])
            i += 1
            continue

        if i + 1 >= n:
            break  # bare trailing IAC - the command byte hasn't arrived yet

        command = data[i + 1]

        if command == IAC:
            result.append(IAC)  # IAC IAC escapes a literal 0xFF data byte
            i += 2

        elif command == SB:

            end = data.find(bytes([IAC, SE]), i + 2)

            if end == -1:
                break  # subnegotiation payload not fully arrived yet

            i = end + 2

        elif 251 <= command <= 254:  # WILL/WONT/DO/DONT, each + one option byte

            if i + 2 >= n:
                break

            i += 3

        else:
            i += 2  # other two-byte commands (NOP, AYT, GA, ...)

    return bytes(result), data[i:]


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

        # Raw bytes from the socket not yet telnet-stripped (see
        # strip_telnet_negotiation) — separate from _buffer, which holds
        # already-stripped bytes waiting to be split into lines, so an IAC
        # sequence that hasn't fully arrived yet stays raw rather than
        # getting prematurely treated as line data.
        self._raw_buffer = b""
        self._buffer = b""

        # Set by request_stop() so _on_disconnected can tell "the user
        # clicked Stop" apart from "the remote end closed the connection
        # on us" — only the latter is actually worth surfacing as an error.
        self._stop_requested = False

    def start(self):

        self.socket = self._socket_factory()
        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.errorOccurred.connect(self._on_socket_error)
        self.socket.disconnected.connect(self._on_disconnected)

        self.socket.connectToHost(self.host, self.port)

    def _on_ready_read(self):

        self._raw_buffer += bytes(self.socket.readAll().data())

        cleaned, self._raw_buffer = strip_telnet_negotiation(self._raw_buffer)
        self._buffer += cleaned

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

    def _on_disconnected(self):
        """QTcpSocket emits `disconnected` (not `errorOccurred`) for a
        clean close initiated by either end — a receiver rebooting or
        just closing the connection normally wouldn't otherwise be
        noticed at all, silently leaving the app looking "live" with no
        more AIS data arriving, indistinguishable from a genuinely quiet
        channel."""

        if not self._stop_requested:
            self.error_occurred.emit("Connection closed by remote host")

    def request_stop(self):

        self._stop_requested = True

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
