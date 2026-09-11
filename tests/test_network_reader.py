import time

from PySide6.QtNetwork import QTcpServer, QHostAddress

from services.network_reader import NetworkAisReader, NetworkTestThread


def pump_until(qapp, condition, timeout=2.0):

    deadline = time.time() + timeout

    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    return condition()


def start_loopback_server():

    server = QTcpServer()
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0)

    return server


def test_reader_emits_lines_received_over_tcp(qapp):

    server = start_loopback_server()

    reader = NetworkAisReader("127.0.0.1", server.serverPort())

    received = []
    reader.line_received.connect(received.append)

    reader.start()

    assert pump_until(qapp, server.hasPendingConnections)
    connection = server.nextPendingConnection()

    connection.write(b"$GPRMC,test*00\r\n")

    assert pump_until(qapp, lambda: len(received) >= 1)
    assert received == ["$GPRMC,test*00"]

    reader.stop()
    server.close()


def test_reader_splits_a_sentence_arriving_across_two_reads(qapp):

    server = start_loopback_server()

    reader = NetworkAisReader("127.0.0.1", server.serverPort())

    received = []
    reader.line_received.connect(received.append)

    reader.start()

    assert pump_until(qapp, server.hasPendingConnections)
    connection = server.nextPendingConnection()

    connection.write(b"$GPRMC,par")
    qapp.processEvents()
    time.sleep(0.05)
    connection.write(b"tial*00\r\n")

    assert pump_until(qapp, lambda: len(received) >= 1)
    assert received == ["$GPRMC,partial*00"]

    reader.stop()
    server.close()


def test_reader_reports_connection_failure(qapp):

    # Bind then immediately release a real port, so connecting to it is
    # guaranteed to be refused promptly (unlike an arbitrary unused port
    # number, which some environments silently swallow instead of
    # refusing).
    server = start_loopback_server()
    closed_port = server.serverPort()
    server.close()

    errors = []

    reader = NetworkAisReader("127.0.0.1", closed_port)
    reader.error_occurred.connect(errors.append)

    reader.start()

    # Windows' TCP stack has been observed to take a couple of seconds to
    # surface "connection refused" for a loopback connect, longer than
    # pump_until's default 2s timeout.
    assert pump_until(qapp, lambda: len(errors) >= 1, timeout=5.0)


def test_request_stop_does_not_block_the_caller(qapp):

    server = start_loopback_server()

    reader = NetworkAisReader("127.0.0.1", server.serverPort())
    reader.start()

    assert pump_until(qapp, server.hasPendingConnections)

    start = time.monotonic()
    reader.request_stop()
    elapsed = time.monotonic() - start

    assert elapsed < 0.1

    assert reader.wait(2000) is True

    server.close()


class FakeConnection:
    """Mimics enough of socket.create_connection()'s interface to drive
    NetworkTestThread without a real socket."""

    def __init__(self, chunks):

        self._chunks = list(chunks)

    def settimeout(self, timeout):
        pass

    def recv(self, size):

        if self._chunks:
            return self._chunks.pop(0)

        return b""

    def close(self):
        pass


def run_network_test_thread(qapp, monkeypatch, connect_factory):

    monkeypatch.setattr(NetworkTestThread, "DURATION_SECONDS", 0.05)

    results = []

    thread = NetworkTestThread("127.0.0.1", 12345, connect_factory=connect_factory)
    thread.test_finished.connect(results.append)

    thread.start()

    assert pump_until(qapp, lambda: len(results) >= 1)

    return results[0]


def test_network_test_reports_connection_failure(qapp, monkeypatch):

    def failing_factory(host, port, timeout):
        raise OSError("connection refused")

    result = run_network_test_thread(qapp, monkeypatch, failing_factory)

    assert result["success"] is False
    assert "connection refused" in result["error"]


def test_network_test_detects_nmea_sentence(qapp, monkeypatch):

    factory = lambda host, port, timeout: FakeConnection([b"$GPRMC,test*00\r\n"])

    result = run_network_test_thread(qapp, monkeypatch, factory)

    assert result["success"] is True
    assert result["byte_count"] > 0
    assert result["found_nmea"] is True
