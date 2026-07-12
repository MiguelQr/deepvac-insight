"""OpcMixin — builds the OPC Server broadcast setup page."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


class OpcMixin:
    def _opc_view(self):
        container = QWidget()
        container.setObjectName("workspaceBody")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)

        hdr = QLabel("OPC Server")
        hdr.setObjectName("pageTitle")
        outer.addWidget(hdr)
        sub = QLabel("Configure and start an OPC UA server to broadcast live chamber data to external clients.")
        sub.setObjectName("sectionLabel")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        cfg_card = QFrame()
        cfg_card.setObjectName("card")
        cfg_card.setFixedWidth(300)
        cl = QVBoxLayout(cfg_card)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(10)

        lbl = QLabel("SERVER CONFIGURATION")
        lbl.setObjectName("sectionLabel")
        cl.addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        self._opc_port = QSpinBox()
        self._opc_port.setRange(1, 65535)
        self._opc_port.setValue(4840)

        self._opc_namespace = QLineEdit("urn:deepvac:opc:server")

        self._opc_security = QComboBox()
        self._opc_security.addItems(["None", "Basic128Rsa15", "Basic256Sha256"])

        self._opc_auth = QComboBox()
        self._opc_auth.addItems(["Anonymous", "Username / Password"])

        self._opc_update_rate = QComboBox()
        self._opc_update_rate.addItems(["100 ms", "250 ms", "500 ms", "1 s"])
        self._opc_update_rate.setCurrentIndex(2)

        for row_idx, (cap, w) in enumerate([
            ("Port",         self._opc_port),
            ("Namespace",    self._opc_namespace),
            ("Security",     self._opc_security),
            ("Auth",         self._opc_auth),
            ("Update rate",  self._opc_update_rate),
        ]):
            l = QLabel(cap)
            l.setObjectName("sectionLabel")
            grid.addWidget(l, row_idx, 0)
            grid.addWidget(w, row_idx, 1)
        cl.addLayout(grid)

        self._opc_start_btn = QPushButton("Start Server")
        self._opc_start_btn.setObjectName("primaryButton")
        self._opc_start_btn.clicked.connect(self._on_opc_toggle)
        cl.addWidget(self._opc_start_btn)

        status_row = QHBoxLayout()
        self._opc_dot = QLabel("●")
        self._opc_dot.setObjectName("chamberIconOff")
        self._opc_status_lbl = QLabel("Server stopped")
        self._opc_status_lbl.setObjectName("statusText")
        status_row.addWidget(self._opc_dot)
        status_row.addWidget(self._opc_status_lbl, 1)
        cl.addLayout(status_row)
        cl.addStretch(1)
        top_row.addWidget(cfg_card)

        info_card = QFrame()
        info_card.setObjectName("card")
        il = QVBoxLayout(info_card)
        il.setContentsMargins(14, 14, 14, 14)
        il.setSpacing(8)
        info_lbl = QLabel("ENDPOINT INFO")
        info_lbl.setObjectName("sectionLabel")
        il.addWidget(info_lbl)
        placeholder = QLabel(
            "Server not running\n\n"
            "Configure the settings and click Start Server\n"
            "to begin broadcasting data over OPC UA."
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setObjectName("monitorPlaceholder")
        placeholder.setMinimumHeight(240)
        il.addWidget(placeholder, 1)
        top_row.addWidget(info_card, 1)
        outer.addLayout(top_row)
        outer.addStretch(1)
        return container

    def _on_opc_toggle(self):
        QMessageBox.information(
            self, "OPC Server",
            "OPC UA server is not yet implemented.\n\n"
            "This panel will be enabled when the OPC UA\n"
            "broadcasting module is developed.",
        )
