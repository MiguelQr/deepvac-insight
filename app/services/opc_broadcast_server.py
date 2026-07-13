"""A lightweight TCP broadcast server standing in for an OPC UA server.

NOTE ON SCOPE: this is not a spec-compliant OPC UA server -- no OPC UA
library (asyncua/opcua) is installed, and pulling one in means bridging
asyncio into this app's Qt event loop. What this actually does: once the
chamber TCP connection (tcp_client.ChamberConnection) is established, this
server can be started to re-broadcast each incoming sample (newline-
delimited JSON, same shape as the source) to any TCP client that connects
on the configured port, tagged with the configured namespace. That
satisfies "broadcast the values read from the chamber to external clients"
without OPC UA protocol compliance. Swap in a real asyncua server here if
protocol compliance is required later.
"""

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer


class OpcBroadcastServer(QObject):
    started = Signal(int)  # port
    stopped = Signal()
    client_count_changed = Signal(int)
    server_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._clients = []
        self.namespace = ""

    def is_running(self):
        return self._server.isListening()

    def start(self, port, namespace=""):
        if self.is_running():
            return True
        self.namespace = namespace
        ok = self._server.listen(QHostAddress.Any, int(port))
        if not ok:
            self.server_error.emit(self._server.errorString())
            return False
        self.started.emit(int(port))
        return True

    def stop(self):
        for client in list(self._clients):
            client.disconnectFromHost()
        self._clients.clear()
        self._server.close()
        self.stopped.emit()
        self.client_count_changed.emit(0)

    def broadcast(self, sample: dict):
        if not self.is_running() or not self._clients:
            return
        payload = {"namespace": self.namespace, **sample}
        line = (json.dumps(payload) + "\n").encode("utf-8")
        for client in list(self._clients):
            if client.state() == client.SocketState.ConnectedState:
                client.write(line)
            else:
                self._remove_client(client)

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.disconnected.connect(lambda s=sock: self._remove_client(s))
            self._clients.append(sock)
        self.client_count_changed.emit(len(self._clients))

    def _remove_client(self, client):
        if client in self._clients:
            self._clients.remove(client)
            self.client_count_changed.emit(len(self._clients))
