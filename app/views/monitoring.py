"""MonitoringMixin — builds the Live Monitoring page and alarm management.

Test Profiles (multi-step setpoint schedules run against the chamber this
page connects) live on the separate Controller page -- see
views/controller.py -- not here; this module only owns the connection
itself (self.tcp) and the alarm/session-recording features built directly
on top of it."""

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import app.services.alarms_service as alarms_service
import app.services.chambers_service as chambers_service
import app.services.data_service as data
from app.common import COLORS, fmt

# Internal English keys stay stable for storage/comparison; only the label
# shown to the user is translated (built fresh, per language, where used).
_CONDITIONS = ["above", "below", "outside range"]
_SEVERITIES = ["Info", "Warning", "Critical"]

# How many most-recent points the live chart redraws each sample -- the
# full session (for "Save Session as Run") is kept in self._mon_buffer
# uncapped; this only bounds what's actively plotted, so a long session
# doesn't make every incoming sample redraw an ever-growing curve.
_LIVE_CHART_WINDOW = 500
# Reconnect attempts after a connection drop that the user didn't request
# themselves (see _on_mon_disconnected_unexpectedly), with linear backoff.
_RECONNECT_MAX_ATTEMPTS = 5
_RECONNECT_DELAY_MS = 3000


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

        chamber_row = QWidget()
        chamber_lay = QHBoxLayout(chamber_row)
        chamber_lay.setContentsMargins(0, 0, 0, 0)
        chamber_lay.setSpacing(4)
        self._mon_chamber_combo = QComboBox()
        self._mon_chamber_combo.setToolTip(self.tr("Which saved chamber to connect to."))
        chamber_lay.addWidget(self._mon_chamber_combo, 1)
        manage_chambers_btn = QPushButton("…")
        manage_chambers_btn.setFixedWidth(26)
        manage_chambers_btn.setToolTip(self.tr("Manage saved chambers…"))
        manage_chambers_btn.clicked.connect(self._open_chambers_dialog)
        chamber_lay.addWidget(manage_chambers_btn)
        self._load_chamber_choices()

        self._mon_interval = QComboBox()
        self._mon_interval.addItems(["250 ms", "500 ms", "1 s", "2 s", "5 s"])
        self._mon_interval.setCurrentIndex(2)
        self._mon_interval.setToolTip(
            self.tr(
                "The connection is push-based (the chamber sends samples as they "
                "occur) — this is reserved for future poll-based protocols."
            )
        )

        for row_idx, (cap, w) in enumerate(
            [
                (self.tr("Protocol"), self._mon_protocol),
                (self.tr("Chamber"), chamber_row),
                (self.tr("Poll interval"), self._mon_interval),
            ]
        ):
            lbl = QLabel(cap)
            lbl.setObjectName("sectionLabel")
            conn_grid.addWidget(lbl, row_idx, 0)
            conn_grid.addWidget(w, row_idx, 1)
        cl.addLayout(conn_grid)

        self._mon_connect_btn = QPushButton(self.tr("Connect"))
        self._mon_connect_btn.setObjectName("primaryButton")
        self._mon_connect_btn.clicked.connect(self._on_mon_connect)
        cl.addWidget(self._mon_connect_btn)

        status_row = QHBoxLayout()
        self._mon_dot = QLabel("●")
        self._mon_dot.setObjectName("chamberIconOff")
        self._mon_status_lbl = QLabel(self.tr("Offline — not connected"))
        self._mon_status_lbl.setObjectName("statusText")
        status_row.addWidget(self._mon_dot)
        status_row.addWidget(self._mon_status_lbl, 1)
        cl.addLayout(status_row)

        self._mon_recording_lbl = QLabel(self.tr("Not recording"))
        self._mon_recording_lbl.setObjectName("sectionLabel")
        cl.addWidget(self._mon_recording_lbl)

        self._mon_save_session_btn = QPushButton(self.tr("Save Session as Run…"))
        self._mon_save_session_btn.setEnabled(False)
        self._mon_save_session_btn.setToolTip(
            self.tr("Save every sample recorded this session as a normal run.")
        )
        self._mon_save_session_btn.clicked.connect(self._save_monitoring_session)
        cl.addWidget(self._mon_save_session_btn)

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

        # ── Live trend chart ─────────────────────────────────────────────────
        trend_card = QFrame()
        trend_card.setObjectName("card")
        tl = QVBoxLayout(trend_card)
        tl.setContentsMargins(14, 14, 14, 14)
        tl.setSpacing(8)
        trend_lbl = QLabel(self.tr("LIVE TREND"))
        trend_lbl.setObjectName("sectionLabel")
        tl.addWidget(trend_lbl)

        self._mon_plot_widget = pg.PlotWidget()
        self._mon_plot_widget.setBackground(None)
        self._mon_plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._mon_plot_widget.addLegend()
        self._mon_plot_widget.setMinimumHeight(220)
        tl.addWidget(self._mon_plot_widget)
        outer.addWidget(trend_card)

        self._mon_buffer = []  # every sample this session -- see _save_monitoring_session
        self._mon_curves = {}  # variable name -> PlotDataItem
        self._mon_user_disconnected = False
        self._mon_reconnect_attempts = 0
        self._mon_reconnect_timer = None
        self._active_chamber = None  # the chamber dict currently connected, if any
        self._session_test_profile_name = None  # last test profile run this session, if any

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
        history_btn = QPushButton(self.tr("History…"))
        history_btn.clicked.connect(self._open_alarm_history)
        alarms_hdr.addWidget(history_btn)
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

        self._alarm_name_ed = QLineEdit()
        self._alarm_name_ed.setPlaceholderText(self.tr("Alarm name"))
        self._alarm_name_ed.setFixedWidth(130)
        self._alarm_var_combo = QComboBox()
        self._alarm_var_combo.addItems(
            ["temp", "temp_ref", "kp", "ki", "kd", "temp_u", "temp_u_p", "temp_u_i", "temp_u_d"]
        )
        self._alarm_var_combo.setEditable(True)
        self._alarm_var_combo.setFixedWidth(100)
        self._alarm_cond_combo = QComboBox()
        cond_labels = {
            "above": self.tr("above"),
            "below": self.tr("below"),
            "outside range": self.tr("outside range"),
        }
        for cond in _CONDITIONS:
            self._alarm_cond_combo.addItem(cond_labels[cond], cond)
        self._alarm_cond_combo.setFixedWidth(110)
        self._alarm_val_ed = QLineEdit()
        self._alarm_val_ed.setPlaceholderText(self.tr("threshold"))
        self._alarm_val_ed.setFixedWidth(80)
        self._alarm_val2_ed = QLineEdit()
        self._alarm_val2_ed.setPlaceholderText(self.tr("upper (range)"))
        self._alarm_val2_ed.setFixedWidth(100)
        self._alarm_sev_combo = QComboBox()
        sev_labels = {
            "Info": self.tr("Info"),
            "Warning": self.tr("Warning"),
            "Critical": self.tr("Critical"),
        }
        for sev in _SEVERITIES:
            self._alarm_sev_combo.addItem(sev_labels[sev], sev)
        self._alarm_sev_combo.setFixedWidth(90)

        self._alarm_deadband_ed = QLineEdit("0")
        self._alarm_deadband_ed.setPlaceholderText(self.tr("deadband"))
        self._alarm_deadband_ed.setToolTip(
            self.tr(
                "Once active, the value must return past the threshold by at least this "
                "much before the alarm clears -- prevents rapid on/off flicker right at "
                "the edge of the threshold."
            )
        )
        self._alarm_deadband_ed.setFixedWidth(70)

        self._alarm_delay_ed = QLineEdit("0")
        self._alarm_delay_ed.setPlaceholderText(self.tr("delay (s)"))
        self._alarm_delay_ed.setToolTip(
            self.tr(
                "The condition must hold continuously for this many seconds before the "
                "alarm actually triggers -- prevents a single noisy sample from firing it."
            )
        )
        self._alarm_delay_ed.setFixedWidth(70)

        save_alarm_btn = QPushButton(self.tr("Add"))
        save_alarm_btn.setObjectName("primaryButton")
        save_alarm_btn.clicked.connect(self._save_alarm)
        cancel_alarm_btn = QPushButton(self.tr("Cancel"))
        cancel_alarm_btn.clicked.connect(self._toggle_alarm_form)

        for cap, w in [
            (self.tr("Name"), self._alarm_name_ed),
            (self.tr("Variable"), self._alarm_var_combo),
            (self.tr("Condition"), self._alarm_cond_combo),
            (self.tr("Value"), self._alarm_val_ed),
            ("", self._alarm_val2_ed),
            (self.tr("Severity"), self._alarm_sev_combo),
            (self.tr("Deadband"), self._alarm_deadband_ed),
            (self.tr("Delay"), self._alarm_delay_ed),
            ("", save_alarm_btn),
            ("", cancel_alarm_btn),
        ]:
            if cap:
                lbl = QLabel(cap)
                lbl.setObjectName("sectionLabel")
                afl.addWidget(lbl)
            afl.addWidget(w)
        afl.addStretch(1)
        self._alarm_form.setVisible(False)
        al.addWidget(self._alarm_form)

        self._alarms_table = QTableWidget()
        self._alarms_table.setMinimumHeight(180)
        self._alarms_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._alarms_table.setSelectionMode(QAbstractItemView.SingleSelection)
        al.addWidget(self._alarms_table)
        self._load_alarm_rules()
        self._refresh_alarms_table()
        outer.addWidget(alarms_card, 1)
        return container

    def _load_alarm_rules(self):
        """Loads persisted alarm rules, replacing the placeholder empty
        list main_window.py's __init__ sets self._monitor_alarms to before
        this page is ever built. Each rule dict gets runtime-only keys
        added (_active, _last_value, _condition_since, _event_id) that are
        never persisted -- see _evaluate_alarms()."""
        try:
            rules = alarms_service.list_rules()
        except Exception:
            rules = []
        for rule in rules:
            rule["_active"] = False
            rule["_last_value"] = None
            rule["_condition_since"] = None
            rule["_event_id"] = None
        self._monitor_alarms = rules

    # ── Connection ───────────────────────────────────────────────────────────

    def _load_chamber_choices(self):
        previous = (
            self._mon_chamber_combo.currentData() if self._mon_chamber_combo.count() else None
        )
        self._mon_chamber_combo.blockSignals(True)
        self._mon_chamber_combo.clear()
        try:
            chambers = chambers_service.list_chambers()
        except Exception:
            chambers = []
        for chamber in chambers:
            self._mon_chamber_combo.addItem(
                f"{chamber['name']}  ({chamber['host']}:{chamber['port']})", chamber
            )
        if previous is not None:
            idx = next(
                (
                    i
                    for i in range(self._mon_chamber_combo.count())
                    if self._mon_chamber_combo.itemData(i)["id"] == previous["id"]
                ),
                0,
            )
            self._mon_chamber_combo.setCurrentIndex(idx)
        self._mon_chamber_combo.blockSignals(False)

    def _open_chambers_dialog(self):
        from app.chambers_dialog import ChambersDialog

        dlg = ChambersDialog(parent=self)
        dlg.exec()
        if dlg.changed:
            self._load_chamber_choices()

    def _on_mon_connect(self):
        if self.tcp.is_connected():
            self._mon_user_disconnected = True  # don't auto-reconnect after this
            self.tcp.disconnect_from_host()
            return
        chamber = self._mon_chamber_combo.currentData()
        if not chamber:
            QMessageBox.warning(
                self,
                self.tr("Connect"),
                self.tr("Add a chamber first (click … next to the Chamber field)."),
            )
            return
        self._active_chamber = chamber
        self._mon_user_disconnected = False
        self._mon_reconnect_attempts = 0
        self._mon_buffer = []
        self._session_test_profile_name = None
        self._mon_curves = {}
        self._mon_plot_widget.clear()
        self._mon_plot_widget.addLegend()
        self._mon_chamber_combo.setEnabled(False)
        self._connect_to_host()

    def _connect_to_host(self):
        chamber = self._active_chamber
        self._mon_connect_btn.setEnabled(False)
        self._mon_status_lbl.setText(
            self.tr("Connecting to {0} ({1}:{2})…").format(
                chamber["name"], chamber["host"], chamber["port"]
            )
        )
        self.tcp.connect_to_host(chamber["host"], chamber["port"])

    def _mon_set_connected(self, connected):
        self._mon_connect_btn.setEnabled(True)
        self._mon_connect_btn.setText(self.tr("Disconnect") if connected else self.tr("Connect"))
        self._mon_chamber_combo.setEnabled(not connected)
        self._mon_dot.setObjectName("chamberIconOn" if connected else "chamberIconOff")
        self._mon_dot.style().unpolish(self._mon_dot)
        self._mon_dot.style().polish(self._mon_dot)
        if connected:
            chamber = self._active_chamber or {}
            self._mon_status_lbl.setText(
                self.tr("Online — {0} ({1}:{2})").format(
                    chamber.get("name", "?"), chamber.get("host", "?"), chamber.get("port", "?")
                )
            )
            self._mon_reconnect_attempts = 0
            self._mon_recording_lbl.setText(self.tr("Recording…"))
            self._mon_save_session_btn.setEnabled(False)
        else:
            self._mon_status_lbl.setText(self.tr("Offline — not connected"))
            self._mon_live_table.setRowCount(0)
            self._mon_update_lbl.setText("—")
            self._mon_save_session_btn.setEnabled(bool(self._mon_buffer))
            if self._mon_buffer:
                self._mon_recording_lbl.setText(
                    self.tr("Stopped -- {0} sample(s) recorded").format(len(self._mon_buffer))
                )
            else:
                self._mon_recording_lbl.setText(self.tr("Not recording"))
            if self._test_running_profile is not None:
                self._test_stop(error=self.tr("chamber disconnected"))
            self._maybe_schedule_reconnect()
        self._on_test_profile_changed()
        for alarm in self._monitor_alarms:
            alarm["_active"] = False
        self._refresh_alarms_table()

    def _maybe_schedule_reconnect(self):
        if self._mon_user_disconnected:
            return
        if self._mon_reconnect_attempts >= _RECONNECT_MAX_ATTEMPTS:
            self._mon_status_lbl.setText(
                self.tr("Offline — reconnect failed after {0} attempts").format(
                    _RECONNECT_MAX_ATTEMPTS
                )
            )
            return
        self._mon_reconnect_attempts += 1
        self._mon_status_lbl.setText(
            self.tr("Connection lost -- reconnecting (attempt {0}/{1})…").format(
                self._mon_reconnect_attempts, _RECONNECT_MAX_ATTEMPTS
            )
        )
        self._mon_reconnect_timer = QTimer(self)
        self._mon_reconnect_timer.setSingleShot(True)
        self._mon_reconnect_timer.timeout.connect(self._connect_to_host)
        self._mon_reconnect_timer.start(_RECONNECT_DELAY_MS * self._mon_reconnect_attempts)

    def _mon_on_error(self, msg):
        self._mon_connect_btn.setEnabled(True)
        self._mon_connect_btn.setText(self.tr("Connect"))
        self._mon_status_lbl.setText(self.tr("Connection error: {0}").format(msg))

    def _save_monitoring_session(self):
        from PySide6.QtWidgets import QInputDialog

        if not self._mon_buffer:
            return
        default_name = f"monitoring-{len(self._mon_buffer)}-samples"
        name, ok = QInputDialog.getText(
            self, self.tr("Save Session as Run"), self.tr("Name:"), text=default_name
        )
        if not ok or not name.strip():
            return
        chamber_name = self._active_chamber["name"] if self._active_chamber else None
        try:
            result = data.save_monitoring_session(
                name.strip(),
                self._mon_buffer,
                chamber=chamber_name,
                test_profile=self._session_test_profile_name,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Save session failed"), str(exc))
            return
        self.runs = result["runs"]
        self.render_runs()
        self._refresh_dashboard()
        self._refresh_reports()
        self._mon_buffer = []
        self._session_test_profile_name = None
        self._mon_save_session_btn.setEnabled(False)
        self._mon_recording_lbl.setText(self.tr("Not recording"))
        QMessageBox.information(
            self,
            self.tr("Session saved"),
            self.tr("Saved as run '{0}'.").format(result["id"]),
        )

    def _mon_on_sample(self, sample):
        from datetime import datetime, timezone

        self._mon_buffer.append(sample)

        self._mon_update_lbl.setText(datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
        self._render_live_sample(sample)
        self._render_live_chart()
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

    def _render_live_chart(self):
        window = self._mon_buffer[-_LIVE_CHART_WINDOW:]
        if not window:
            return
        has_timestamps = all(isinstance(s.get("timestamp"), (int, float)) for s in window)
        if has_timestamps:
            first_t = window[0]["timestamp"]
            xs = [s["timestamp"] - first_t for s in window]
        else:
            xs = list(range(len(window)))

        numeric_keys = sorted(
            {
                key
                for s in window
                for key, value in s.items()
                if isinstance(value, (int, float)) and key != "timestamp"
            }
        )
        for index, key in enumerate(numeric_keys):
            ys = [s.get(key) for s in window]
            plot_xs = [x for x, y in zip(xs, ys, strict=False) if isinstance(y, (int, float))]
            plot_ys = [y for y in ys if isinstance(y, (int, float))]
            if not plot_xs:
                continue
            color = COLORS[index % len(COLORS)]
            curve = self._mon_curves.get(key)
            if curve is None:
                curve = self._mon_plot_widget.plot(
                    plot_xs, plot_ys, pen=pg.mkPen(color, width=1.6), name=key
                )
                self._mon_curves[key] = curve
            else:
                curve.setData(plot_xs, plot_ys)

    # ── Alarms ───────────────────────────────────────────────────────────────

    def _toggle_alarm_form(self):
        self._alarm_form.setVisible(not self._alarm_form.isVisible())

    def _open_alarm_history(self):
        from app.alarm_history_dialog import AlarmHistoryDialog

        dlg = AlarmHistoryDialog(current_user=self.current_user, parent=self)
        dlg.exec()

    def _save_alarm(self):
        name = self._alarm_name_ed.text().strip()
        var = self._alarm_var_combo.currentText().strip()
        cond = self._alarm_cond_combo.currentData()
        val_text = self._alarm_val_ed.text().strip()
        val2_text = self._alarm_val2_ed.text().strip()
        sev = self._alarm_sev_combo.currentData()
        if not name or not var or not val_text:
            return
        try:
            value = float(val_text)
            value2 = float(val2_text) if val2_text else None
            deadband = float(self._alarm_deadband_ed.text().strip() or "0")
            delay_s = float(self._alarm_delay_ed.text().strip() or "0")
        except ValueError:
            return
        if deadband < 0 or delay_s < 0:
            QMessageBox.warning(
                self, self.tr("Add Alarm"), self.tr("Deadband and delay must not be negative.")
            )
            return
        try:
            rule = alarms_service.add_rule(
                name,
                var,
                cond,
                value,
                value2,
                sev,
                deadband=deadband,
                delay_s=delay_s,
                created_by=self.current_user.get("name") or "Unknown",
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Add Alarm"), str(exc))
            return
        rule["_active"] = False
        rule["_last_value"] = None
        rule["_condition_since"] = None
        rule["_event_id"] = None
        self._monitor_alarms.append(rule)
        self._alarm_name_ed.clear()
        self._alarm_val_ed.clear()
        self._alarm_val2_ed.clear()
        self._alarm_deadband_ed.setText("0")
        self._alarm_delay_ed.setText("0")
        self._alarm_form.setVisible(False)
        self._refresh_alarms_table()

    def _delete_alarm(self, idx):
        if 0 <= idx < len(self._monitor_alarms):
            rule = self._monitor_alarms.pop(idx)
            alarms_service.delete_rule(rule["id"])
        self._refresh_alarms_table()

    def _evaluate_alarms(self, sample):
        import time

        changed = False
        now = time.monotonic()
        for alarm in self._monitor_alarms:
            value = sample.get(alarm["variable"])
            alarm["_last_value"] = value
            if not isinstance(value, (int, float)):
                continue

            cond = alarm["condition"]
            deadband = alarm.get("deadband") or 0.0
            threshold, threshold2 = alarm["value"], alarm.get("value2")

            if cond == "above":
                raw_active = value > threshold
                clears = value <= threshold - deadband
            elif cond == "below":
                raw_active = value < threshold
                clears = value >= threshold + deadband
            elif cond == "outside range" and threshold2 is not None:
                lo, hi = min(threshold, threshold2), max(threshold, threshold2)
                raw_active = value < lo or value > hi
                clears = (lo + deadband) <= value <= (hi - deadband)
            else:
                continue

            if not alarm["_active"]:
                if raw_active:
                    if alarm.get("_condition_since") is None:
                        alarm["_condition_since"] = now
                    if now - alarm["_condition_since"] >= (alarm.get("delay_s") or 0.0):
                        alarm["_active"] = True
                        changed = True
                        alarm["_event_id"] = alarms_service.record_trigger(alarm, value)
                else:
                    alarm["_condition_since"] = None
            elif clears:
                alarm["_active"] = False
                alarm["_condition_since"] = None
                changed = True
                alarms_service.record_clear(alarm.get("_event_id"))
                alarm["_event_id"] = None
        if changed:
            self._refresh_alarms_table()

    def _refresh_alarms_table(self):
        cols = [
            self.tr("Name"),
            self.tr("Variable"),
            self.tr("Condition"),
            self.tr("Value / Range"),
            self.tr("Severity"),
            self.tr("Status"),
        ]
        cond_labels = {
            "above": self.tr("above"),
            "below": self.tr("below"),
            "outside range": self.tr("outside range"),
        }
        sev_labels = {
            "Info": self.tr("Info"),
            "Warning": self.tr("Warning"),
            "Critical": self.tr("Critical"),
        }
        tbl = self._alarms_table
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
            values = [
                alarm["name"],
                alarm["variable"],
                cond_labels.get(alarm["condition"], alarm["condition"]),
                val_str,
                sev_labels.get(sev, sev),
                status_display,
            ]
            for ci, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if ci == 4:
                    color = {"Info": "#60a5fa", "Warning": "#f2bd52", "Critical": "#ff6f7d"}.get(
                        sev, "#94a3b8"
                    )
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
