"""TCP client for a live chamber connection.

Wire protocol: newline-delimited JSON. Each line the server sends is one
JSON object of variable readings, the same shape as a run_samples.csv row
(temp, temp_ref, kp, ki, kd, temp_u, temp_u_p, temp_u_i, temp_u_d, ...).

Built on QTcpSocket rather than a raw socket + thread: Qt delivers socket
events (connected/disconnected/data ready) as signals on the existing Qt
event loop, so no extra thread or manual synchronization is needed here.

See tcp/dummy_chamber_server.py (gitignored, a local dev/test tool, not
part of the shipped app) for a server that speaks this same protocol.
"""

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket


class ChamberConnection(QObject):
    connected = Signal()
    disconnected = Signal()
    connection_error = Signal(str)
    sample_received = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket = QTcpSocket(self)
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.readyRead.connect(self._on_ready_read)
        self._socket.errorOccurred.connect(self._on_error)
        self._buffer = b""

    def connect_to_host(self, host, port):
        if self.is_connected():
            return
        self._buffer = b""
        self._socket.connectToHost(host, int(port))

    def disconnect_from_host(self):
        self._socket.disconnectFromHost()

    def is_connected(self):
        return self._socket.state() == QAbstractSocket.ConnectedState

    def _on_connected(self):
        self.connected.emit()

    def _on_disconnected(self):
        self._buffer = b""
        self.disconnected.emit()

    def _on_error(self, _err):
        self.connection_error.emit(self._socket.errorString())

    def _on_ready_read(self):
        self._buffer += bytes(self._socket.readAll())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(sample, dict):
                self.sample_received.emit(sample)
