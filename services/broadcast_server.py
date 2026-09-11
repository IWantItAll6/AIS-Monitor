from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QTcpServer, QHostAddress


class BroadcastServer(QObject):
    """Streams every raw NMEA/PSMT line this app receives to any TCP client
    that connects — the "Network > TCP" convention marine software like
    OpenCPN already expects, not the Telnet protocol (no IAC/option
    negotiation bytes, which would corrupt the sentence stream).

    Built on QTcpServer/QTcpSocket rather than a QThread: both are already
    asynchronous within Qt's event loop (unlike pyserial's blocking
    readline(), which is why SerialReaderThread needs a thread), so running
    this directly on the GUI thread keeps it simple with no cross-thread
    signal marshalling.
    """

    client_count_changed = Signal(int)
    error_occurred = Signal(str)

    def __init__(self, server_factory=None, parent=None):

        super().__init__(parent)

        # Injectable so tests can substitute a fake/real-but-isolated server
        # instead of always constructing a real QTcpServer — same seam as
        # serial_reader.py's serial_factory.
        self._server_factory = server_factory or QTcpServer

        self.server = None
        self.clients = []

    def start(self, port):

        self.server = self._server_factory()
        self.server.newConnection.connect(self._on_new_connection)

        if not self.server.listen(QHostAddress.SpecialAddress.Any, port):
            self.error_occurred.emit(self.server.errorString())
            self.server = None
            return False

        return True

    def stop(self):

        for client in self.clients:
            client.close()

        self.clients = []

        if self.server is not None:
            self.server.close()
            self.server = None

        self.client_count_changed.emit(0)

    def is_listening(self):

        return self.server is not None and self.server.isListening()

    def _on_new_connection(self):

        while self.server.hasPendingConnections():

            socket = self.server.nextPendingConnection()
            socket.disconnected.connect(lambda s=socket: self._on_client_disconnected(s))

            self.clients.append(socket)

        self.client_count_changed.emit(len(self.clients))

    def _on_client_disconnected(self, socket):

        if socket in self.clients:
            self.clients.remove(socket)

        socket.deleteLater()

        self.client_count_changed.emit(len(self.clients))

    def broadcast_line(self, line):

        if not self.clients:
            return

        # \r\n, not literal Telnet framing — this is what real NMEA-over-TCP
        # consumers (OpenCPN etc.) expect: a bare sentence per line, nothing
        # else. write() queues into Qt's own send buffer and returns
        # immediately, so a slow/stalled client can't block writes to other
        # clients or to the serial-read path — its unsent-buffer only grows
        # unbounded if it never drains, a known, unhardened limitation that's
        # a non-issue at real-world NMEA sentence rates.
        data = (line + "\r\n").encode("ascii", errors="ignore")

        for client in self.clients:
            client.write(data)
