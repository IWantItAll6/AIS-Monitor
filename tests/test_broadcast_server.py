import time

from PySide6.QtNetwork import QTcpSocket, QTcpServer, QHostAddress

from services.broadcast_server import BroadcastServer


def pump_until(qapp, condition, timeout=2.0):

    deadline = time.time() + timeout

    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    return condition()


def connected_client(qapp, port):

    client = QTcpSocket()
    client.connectToHost(QHostAddress.SpecialAddress.LocalHost, port)

    assert pump_until(qapp, lambda: client.state() == QTcpSocket.SocketState.ConnectedState)

    return client


def test_start_and_stop_reports_listening_state(qapp):

    server = BroadcastServer()

    assert server.start(0)  # port 0 -> OS-assigned free port
    assert server.is_listening()
    assert server.server.serverPort() != 0

    server.stop()

    assert not server.is_listening()


def test_client_receives_broadcast_line_verbatim(qapp):

    server = BroadcastServer()
    server.start(0)

    client = connected_client(qapp, server.server.serverPort())

    assert pump_until(qapp, lambda: len(server.clients) == 1)

    server.broadcast_line("$GPRMC,test*00")

    assert pump_until(qapp, lambda: client.bytesAvailable() > 0)

    data = bytes(client.readAll().data())

    # \r\n line ending, no Telnet IAC (0xFF) or option-negotiation bytes.
    assert data == b"$GPRMC,test*00\r\n"
    assert 0xFF not in data

    server.stop()


def test_multiple_clients_all_receive_the_same_line(qapp):

    server = BroadcastServer()
    server.start(0)

    port = server.server.serverPort()
    client_a = connected_client(qapp, port)
    client_b = connected_client(qapp, port)

    assert pump_until(qapp, lambda: len(server.clients) == 2)

    server.broadcast_line("!AIVDM,1,1,,A,test,0*00")

    assert pump_until(qapp, lambda: client_a.bytesAvailable() > 0 and client_b.bytesAvailable() > 0)

    assert bytes(client_a.readAll().data()) == b"!AIVDM,1,1,,A,test,0*00\r\n"
    assert bytes(client_b.readAll().data()) == b"!AIVDM,1,1,,A,test,0*00\r\n"

    server.stop()


def test_client_disconnect_updates_client_count(qapp):

    server = BroadcastServer()
    server.start(0)

    counts = []
    server.client_count_changed.connect(counts.append)

    client = connected_client(qapp, server.server.serverPort())

    assert pump_until(qapp, lambda: len(server.clients) == 1)

    client.close()

    assert pump_until(qapp, lambda: len(server.clients) == 0)
    assert counts[-1] == 0

    server.stop()


def test_start_fails_gracefully_when_port_already_in_use(qapp):

    # Bind the same wildcard address BroadcastServer itself uses (Any) —
    # binding Any:port after a specific-interface bind on the same port can
    # silently succeed on some platforms/socket-option combinations, so this
    # is the one guaranteed-to-conflict setup.
    blocker = QTcpServer()
    assert blocker.listen(QHostAddress.SpecialAddress.Any, 0)

    errors = []
    server = BroadcastServer()
    server.error_occurred.connect(errors.append)

    assert not server.start(blocker.serverPort())
    assert len(errors) == 1
    assert not server.is_listening()

    blocker.close()
