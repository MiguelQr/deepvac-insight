"""Integration tests for app/services/tcp_client.py's ChamberConnection --
send_command() (the outbound protocol Test Profiles use to push setpoints),
exercised against a real local QTcpServer loopback rather than a mock, so
what's asserted is genuinely the bytes written to the wire."""

import json

import pytest
from PySide6.QtNetwork import QHostAddress, QTcpServer

from app.services.tcp_client import ChamberConnection

pytestmark = pytest.mark.integration

# Captured at import time, before any test's fixtures run -- conftest.py's
# autouse no_real_network fixture monkeypatches connect_to_host to a no-op
# for every other test in the suite (so nothing accidentally opens a real
# socket). This module is the one deliberate exception: it exists to prove
# the real wire protocol, so real_connect_to_host below restores the
# genuine implementation for just these tests.
_real_connect_to_host = ChamberConnection.connect_to_host


@pytest.fixture
def real_connect_to_host(monkeypatch):
    monkeypatch.setattr(ChamberConnection, "connect_to_host", _real_connect_to_host)


@pytest.fixture
def loopback_server(qapp):
    server = QTcpServer()
    assert server.listen(QHostAddress.LocalHost, 0)
    yield server
    server.close()


def test_send_command_raises_when_not_connected():
    conn = ChamberConnection()
    with pytest.raises(RuntimeError):
        conn.send_command({"cmd": "set_point"})


def test_send_command_writes_newline_delimited_json(qtbot, loopback_server, real_connect_to_host):
    conn = ChamberConnection()
    accepted = []
    loopback_server.newConnection.connect(
        lambda: accepted.append(loopback_server.nextPendingConnection())
    )

    with qtbot.waitSignal(conn.connected, timeout=2000):
        conn.connect_to_host("127.0.0.1", loopback_server.serverPort())

    qtbot.waitUntil(lambda: len(accepted) == 1, timeout=2000)
    server_socket = accepted[0]

    payload = {
        "cmd": "set_point",
        "temperature": 60.0,
        "pressure": None,
        "step_index": 0,
        "step_label": "Ramp",
        "profile_name": "Test A",
    }
    conn.send_command(payload)

    qtbot.waitUntil(lambda: server_socket.bytesAvailable() > 0, timeout=2000)
    raw = bytes(server_socket.readAll())
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8").strip()) == payload

    conn.disconnect_from_host()
