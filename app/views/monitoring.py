"""MonitoringMixin — builds the Live Monitoring page and alarm management."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.common import fmt

# Internal English keys stay stable for storage/comparison; only the label
# shown to the user is translated (built fresh, per language, where used).
_CONDITIONS = ["above", "below", "outside range"]
_SEVERITIES = ["Info", "Warning", "Critical"]


class MonitoringMixin:
    def _monitoring_view(self):
        container = QWidget()
        container.setObjectName("workspaceBody")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)

        hdr = QLabel(self.tr("Live Monitoring"))
        hdr.setObjectName("pageTitle")
        outer.addWidget(hdr)
        sub = QLabel(self.tr("Real-time chamber data streaming and alarm management."))
        sub.setObjectName("sectionLabel")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # ── Top row: connection + live data ──────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        conn_card = QFrame()
        conn_card.setObjectName("card")
        conn_card.setFixedWidth(248)
        cl = QVBoxLayout(conn_card)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(10)

        lbl = QLabel(self.tr("CONNECTION"))
        lbl.setObjectName("sectionLabel")
        cl.addWidget(lbl)

        conn_grid = QGridLayout()
        conn_grid.setSpacing(6)
        conn_grid.setColumnStretch(1, 1)

        self._mon_protocol = QComboBox()
        self._mon_protocol.addItems(["TCP / IP"])

        host_row = QWidget()
        host_lay = QHBoxLayout(host_row)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(4)
        self._mon_host = QLineEdit("127.0.0.1")
        self._mon_port = QSpinBox()
        self._mon_port.setRange(1, 65535)
        self._mon_port.setValue(5555)
        self._mon_port.setFixedWidth(68)
        host_lay.addWidget(self._mon_host)
        host_lay.addWidget(self._mon_port)

        self._mon_interval = QComboBox()
        self._mon_interval.addItems(["250 ms", "500 ms", "1 s", "2 s", "5 s"])
        self._mon_interval.setCurrentIndex(2)
        self._mon_interval.setToolTip(self.tr(
            "The connection is push-based (the chamber sends samples as they "
            "occur) — this is reserved for future poll-based protocols."))

        for row_idx, (cap, w) in enumerate([
            (self.tr("Protocol"),      self._mon_protocol),
            (self.tr("Host / Port"),   host_row),
            (self.tr("Poll interval"), self._mon_interval),
        ]):
            l = QLabel(cap)
            l.setObjectName("sectionLabel")
            conn_grid.addWidget(l, row_idx, 0)
            conn_grid.addWidget(w, row_idx, 1)
        cl.addLayout(conn_grid)

        self._mon_connect_btn = QPushButton(self.tr("Connect"))
        self._mon_connect_btn.setObjectName("primaryButton")
        self._mon_connect_btn.clicked.connect(self._on_mon_connect)
        cl.addWidget(self._mon_connect_btn)

        status_row = QHBoxLayout()
        self._mon_dot       = QLabel("●")
        self._mon_dot.setObjectName("chamberIconOff")
        self._mon_status_lbl = QLabel(self.tr("Offline — not connected"))
        self._mon_status_lbl.setObjectName("statusText")
        status_row.addWidget(self._mon_dot)
        status_row.addWidget(self._mon_status_lbl, 1)
        cl.addLayout(status_row)
        cl.addStretch(1)
        top_row.addWidget(conn_card)

        live_card = QFrame()
        live_card.setObjectName("card")
        ll = QVBoxLayout(live_card)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(8)
        live_hdr = QHBoxLayout()
        live_lbl = QLabel(self.tr("LIVE DATA"))
        live_lbl.setObjectName("sectionLabel")
        live_hdr.addWidget(live_lbl)
        live_hdr.addStretch(1)
        self._mon_update_lbl = QLabel("—")
        self._mon_update_lbl.setObjectName("sectionLabel")
        live_hdr.addWidget(self._mon_update_lbl)
        ll.addLayout(live_hdr)

        self._mon_live_table = QTableWidget()
        self._mon_live_table.setColumnCount(2)
        self._mon_live_table.setHorizontalHeaderLabels([self.tr("Variable"), self.tr("Value")])
        self._mon_live_table.verticalHeader().setVisible(False)
        self._mon_live_table.horizontalHeader().setStretchLastSection(True)
        self._mon_live_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._mon_live_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._mon_live_table.setAlternatingRowColors(True)
        self._mon_live_table.setShowGrid(False)
        self._mon_live_table.setMinimumHeight(240)
        ll.addWidget(self._mon_live_table, 1)
        top_row.addWidget(live_card, 1)
        outer.addLayout(top_row)

        # ── Alarms ───────────────────────────────────────────────────────────
        alarms_card = QFrame()
        alarms_card.setObjectName("card")
        al = QVBoxLayout(alarms_card)
        al.setContentsMargins(14, 14, 14, 14)
        al.setSpacing(10)

        alarms_hdr = QHBoxLayout()
        albl = QLabel(self.tr("ALARMS"))
        albl.setObjectName("sectionLabel")
        alarms_hdr.addWidget(albl)
        adesc = QLabel(self.tr("Define thresholds that notify you when values go out of range."))
        adesc.setObjectName("sectionLabel")
        adesc.setWordWrap(True)
        alarms_hdr.addWidget(adesc, 1)
        add_alarm_btn = QPushButton(self.tr("+ Add Alarm"))
        add_alarm_btn.setObjectName("primaryButton")
        add_alarm_btn.clicked.connect(self._toggle_alarm_form)
        alarms_hdr.addWidget(add_alarm_btn)
        al.addLayout(alarms_hdr)

        self._alarm_form = QFrame()
        self._alarm_form.setObjectName("ruleRow")
        afl = QHBoxLayout(self._alarm_form)
        afl.setContentsMargins(8, 8, 8, 8)
        afl.setSpacing(8)

        self._alarm_name_ed   = QLineEdit()
        self._alarm_name_ed.setPlaceholderText(self.tr("Alarm name"))
        self._alarm_name_ed.setFixedWidth(130)
        self._alarm_var_combo = QComboBox()
        self._alarm_var_combo.addItems(
            ["temp", "temp_ref", "kp", "ki", "kd", "temp_u", "temp_u_p", "temp_u_i", "temp_u_d"])
        self._alarm_var_combo.setEditable(True)
        self._alarm_var_combo.setFixedWidth(100)
        self._alarm_cond_combo = QComboBox()
        cond_labels = {"above": self.tr("above"), "below": self.tr("below"),
                       "outside range": self.tr("outside range")}
        for cond in _CONDITIONS:
            self._alarm_cond_combo.addItem(cond_labels[cond], cond)
        self._alarm_cond_combo.setFixedWidth(110)
        self._alarm_val_ed  = QLineEdit()
        self._alarm_val_ed.setPlaceholderText(self.tr("threshold"))
        self._alarm_val_ed.setFixedWidth(80)
        self._alarm_val2_ed = QLineEdit()
        self._alarm_val2_ed.setPlaceholderText(self.tr("upper (range)"))
        self._alarm_val2_ed.setFixedWidth(100)
        self._alarm_sev_combo = QComboBox()
        sev_labels = {"Info": self.tr("Info"), "Warning": self.tr("Warning"),
                      "Critical": self.tr("Critical")}
        for sev in _SEVERITIES:
            self._alarm_sev_combo.addItem(sev_labels[sev], sev)
        self._alarm_sev_combo.setFixedWidth(90)

        save_alarm_btn   = QPushButton(self.tr("Add"))
        save_alarm_btn.setObjectName("primaryButton")
        save_alarm_btn.clicked.connect(self._save_alarm)
        cancel_alarm_btn = QPushButton(self.tr("Cancel"))
        cancel_alarm_btn.clicked.connect(self._toggle_alarm_form)

        for cap, w in [
            (self.tr("Name"),      self._alarm_name_ed),
            (self.tr("Variable"),  self._alarm_var_combo),
            (self.tr("Condition"), self._alarm_cond_combo),
            (self.tr("Value"),     self._alarm_val_ed),
            ("",                   self._alarm_val2_ed),
            (self.tr("Severity"),  self._alarm_sev_combo),
            ("",                   save_alarm_btn),
            ("",                   cancel_alarm_btn),
        ]:
            if cap:
                l = QLabel(cap)
                l.setObjectName("sectionLabel")
                afl.addWidget(l)
            afl.addWidget(w)
        afl.addStretch(1)
        self._alarm_form.setVisible(False)
        al.addWidget(self._alarm_form)

        self._alarms_table = QTableWidget()
        self._alarms_table.setMinimumHeight(180)
        self._alarms_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._alarms_table.setSelectionMode(QAbstractItemView.SingleSelection)
        al.addWidget(self._alarms_table)
        self._refresh_alarms_table()
        outer.addWidget(alarms_card, 1)
        return container

    # ── Connection ───────────────────────────────────────────────────────────

    def _on_mon_connect(self):
        if self.tcp.is_connected():
            self.tcp.disconnect_from_host()
            return
        host = self._mon_host.text().strip() or "127.0.0.1"
        port = self._mon_port.value()
        self._mon_connect_btn.setEnabled(False)
        self._mon_status_lbl.setText(self.tr("Connecting to {0}:{1}…").format(host, port))
        self.tcp.connect_to_host(host, port)

    def _mon_set_connected(self, connected):
        self._mon_connect_btn.setEnabled(True)
        self._mon_connect_btn.setText(self.tr("Disconnect") if connected else self.tr("Connect"))
        self._mon_dot.setObjectName("chamberIconOn" if connected else "chamberIconOff")
        self._mon_dot.style().unpolish(self._mon_dot)
        self._mon_dot.style().polish(self._mon_dot)
        if connected:
            host = self._mon_host.text().strip() or "127.0.0.1"
            self._mon_status_lbl.setText(
                self.tr("Online — {0}:{1}").format(host, self._mon_port.value()))
        else:
            self._mon_status_lbl.setText(self.tr("Offline — not connected"))
            self._mon_live_table.setRowCount(0)
            self._mon_update_lbl.setText("—")
        for alarm in self._monitor_alarms:
            alarm["_active"] = False
        self._refresh_alarms_table()

    def _mon_on_error(self, msg):
        self._mon_connect_btn.setEnabled(True)
        self._mon_connect_btn.setText(self.tr("Connect"))
        self._mon_status_lbl.setText(self.tr("Connection error: {0}").format(msg))

    def _mon_on_sample(self, sample):
        from datetime import datetime, timezone
        self._mon_update_lbl.setText(datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
        self._render_live_sample(sample)
        self._evaluate_alarms(sample)

    def _render_live_sample(self, sample):
        keys = list(sample.keys())
        self._mon_live_table.setUpdatesEnabled(False)
        self._mon_live_table.setRowCount(len(keys))
        for i, key in enumerate(keys):
            value = sample.get(key)
            text = fmt(value) if isinstance(value, (int, float)) else str(value)
            self._mon_live_table.setItem(i, 0, QTableWidgetItem(str(key)))
            self._mon_live_table.setItem(i, 1, QTableWidgetItem(text))
        self._mon_live_table.resizeColumnsToContents()
        self._mon_live_table.setUpdatesEnabled(True)

    # ── Alarms ───────────────────────────────────────────────────────────────

    def _toggle_alarm_form(self):
        self._alarm_form.setVisible(not self._alarm_form.isVisible())

    def _save_alarm(self):
        name      = self._alarm_name_ed.text().strip()
        var       = self._alarm_var_combo.currentText().strip()
        cond      = self._alarm_cond_combo.currentData()
        val_text  = self._alarm_val_ed.text().strip()
        val2_text = self._alarm_val2_ed.text().strip()
        sev       = self._alarm_sev_combo.currentData()
        if not name or not var or not val_text:
            return
        try:
            value  = float(val_text)
            value2 = float(val2_text) if val2_text else None
        except ValueError:
            return
        self._monitor_alarms.append({
            "name": name, "variable": var, "condition": cond,
            "value": value, "value2": value2, "severity": sev,
            "_active": False,
        })
        self._alarm_name_ed.clear()
        self._alarm_val_ed.clear()
        self._alarm_val2_ed.clear()
        self._alarm_form.setVisible(False)
        self._refresh_alarms_table()

    def _delete_alarm(self, idx):
        if 0 <= idx < len(self._monitor_alarms):
            self._monitor_alarms.pop(idx)
        self._refresh_alarms_table()

    def _evaluate_alarms(self, sample):
        changed = False
        for alarm in self._monitor_alarms:
            value = sample.get(alarm["variable"])
            active = False
            if isinstance(value, (int, float)):
                cond = alarm["condition"]
                if cond == "above":
                    active = value > alarm["value"]
                elif cond == "below":
                    active = value < alarm["value"]
                elif cond == "outside range" and alarm.get("value2") is not None:
                    lo, hi = alarm["value"], alarm["value2"]
                    active = value < min(lo, hi) or value > max(lo, hi)
            if alarm.get("_active") != active:
                changed = True
            alarm["_active"] = active
            alarm["_last_value"] = value
        if changed:
            self._refresh_alarms_table()

    def _refresh_alarms_table(self):
        cols = [self.tr("Name"), self.tr("Variable"), self.tr("Condition"),
                self.tr("Value / Range"), self.tr("Severity"), self.tr("Status")]
        cond_labels = {"above": self.tr("above"), "below": self.tr("below"),
                       "outside range": self.tr("outside range")}
        sev_labels = {"Info": self.tr("Info"), "Warning": self.tr("Warning"),
                      "Critical": self.tr("Critical")}
        tbl  = self._alarms_table
        tbl.setUpdatesEnabled(False)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        tbl.setWordWrap(False)
        tbl.verticalHeader().setVisible(False)
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setColumnCount(len(cols) + 1)
        tbl.setRowCount(len(self._monitor_alarms))
        tbl.setHorizontalHeaderLabels(cols + [""])
        connected = self.tcp.is_connected()
        for ri, alarm in enumerate(self._monitor_alarms):
            val_str = str(alarm["value"])
            if alarm.get("value2") is not None:
                val_str += f" – {alarm['value2']}"
            sev = alarm["severity"]
            if not connected:
                is_active, status_display = False, self.tr("Inactive (not connected)")
            elif alarm.get("_active"):
                is_active, status_display = True, self.tr("Active")
            else:
                is_active, status_display = False, self.tr("Inactive")
            values = [alarm["name"], alarm["variable"], cond_labels.get(alarm["condition"], alarm["condition"]),
                      val_str, sev_labels.get(sev, sev), status_display]
            for ci, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if ci == 4:
                    color = {"Info": "#60a5fa", "Warning": "#f2bd52",
                             "Critical": "#ff6f7d"}.get(sev, "#94a3b8")
                    item.setForeground(QColor(color))
                elif ci == 5 and is_active:
                    item.setForeground(QColor("#ff6f7d"))
                tbl.setItem(ri, ci, item)
            del_btn = QPushButton("✕")
            del_btn.setObjectName("tabClose")
            del_btn.setFixedSize(24, 24)
            del_btn.clicked.connect(lambda _=False, i=ri: self._delete_alarm(i))
            tbl.setCellWidget(ri, len(cols), del_btn)
        tbl.resizeColumnsToContents()
        tbl.setUpdatesEnabled(True)
