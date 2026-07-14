"""ControllerMixin — builds the Controller page: a one-off Manual Setpoint
sender and Test Profiles (multi-step temperature/pressure schedules) with
the step-sequencer that runs one, both against whichever chamber is
connected via Live Monitoring.

The chamber connection itself (services/tcp_client.ChamberConnection,
self.tcp) is shared app-wide and owned by Live Monitoring (views/
monitoring.py) -- this page only reads its connected state and, once a
test starts, writes to it via send_command(). See monitoring.py's
_mon_set_connected() for the other half of the integration: it stops a
running test if the chamber disconnects mid-test.
"""

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import app.services.test_profiles_service as test_profiles_service


def _format_hms(seconds):
    seconds = int(max(0.0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class ControllerMixin:
    def _controller_view(self):
        container = QWidget()
        container.setObjectName("workspaceBody")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)

        hdr = QLabel(self.tr("Controller"))
        hdr.setObjectName("pageTitle")
        outer.addWidget(hdr)

        status_row = QHBoxLayout()
        self._ctrl_chamber_dot = QLabel("●")
        self._ctrl_chamber_dot.setObjectName("chamberIconOff")
        self._ctrl_chamber_status_lbl = QLabel(self.tr("No chamber connected"))
        self._ctrl_chamber_status_lbl.setObjectName("statusText")
        status_row.addWidget(self._ctrl_chamber_dot)
        status_row.addWidget(self._ctrl_chamber_status_lbl)
        status_row.addStretch(1)
        outer.addLayout(status_row)

        self._test_running_profile = None
        self._test_step_index = None
        self._test_step_started_at = None
        self._test_timer = None
        self._test_tick_timer = None

        self._manual_running = False
        self._manual_started_at = None
        self._manual_timer = None

        # ── Manual Setpoint ──────────────────────────────────────────────────
        manual_card = QFrame()
        manual_card.setObjectName("card")
        mnl = QVBoxLayout(manual_card)
        mnl.setContentsMargins(14, 14, 14, 14)
        mnl.setSpacing(10)

        manual_hdr = QLabel(self.tr("MANUAL SETPOINT"))
        manual_hdr.setObjectName("sectionLabel")
        mnl.addWidget(manual_hdr)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel(self.tr("Temp (°C)")))
        self._manual_temp_ed = QLineEdit()
        self._manual_temp_ed.setPlaceholderText(self.tr("optional"))
        self._manual_temp_ed.setFixedWidth(90)
        manual_row.addWidget(self._manual_temp_ed)
        manual_row.addWidget(QLabel(self.tr("Pressure")))
        self._manual_pressure_ed = QLineEdit()
        self._manual_pressure_ed.setPlaceholderText(self.tr("optional"))
        self._manual_pressure_ed.setFixedWidth(90)
        manual_row.addWidget(self._manual_pressure_ed)
        self._manual_send_btn = QPushButton(self.tr("Start"))
        self._manual_send_btn.setObjectName("primaryButton")
        self._manual_send_btn.setEnabled(False)
        self._manual_send_btn.clicked.connect(self._on_manual_button_clicked)
        manual_row.addWidget(self._manual_send_btn)
        manual_row.addStretch(1)
        mnl.addLayout(manual_row)

        self._manual_status_lbl = QLabel(self.tr("Not running"))
        self._manual_status_lbl.setObjectName("statusText")
        self._manual_status_lbl.setWordWrap(True)
        mnl.addWidget(self._manual_status_lbl)

        outer.addWidget(manual_card)

        # ── Test Profiles ────────────────────────────────────────────────────
        profiles_card = QFrame()
        profiles_card.setObjectName("card")
        pfl = QVBoxLayout(profiles_card)
        pfl.setContentsMargins(14, 14, 14, 14)
        pfl.setSpacing(10)

        profiles_hdr = QHBoxLayout()
        pflbl = QLabel(self.tr("TEST PROFILES"))
        pflbl.setObjectName("sectionLabel")
        profiles_hdr.addWidget(pflbl)
        profiles_hdr.addStretch(1)
        manage_profiles_btn = QPushButton(self.tr("Manage Test Profiles"))
        manage_profiles_btn.clicked.connect(self._open_test_profiles_dialog)
        profiles_hdr.addWidget(manage_profiles_btn)
        pfl.addLayout(profiles_hdr)

        picker_row = QHBoxLayout()
        self._test_profile_combo = QComboBox()
        self._test_profile_combo.setMinimumWidth(220)
        self._test_profile_combo.currentIndexChanged.connect(self._on_test_profile_changed)
        picker_row.addWidget(self._test_profile_combo, 1)
        self._test_start_btn = QPushButton(self.tr("Start Test"))
        self._test_start_btn.setObjectName("primaryButton")
        self._test_start_btn.setEnabled(False)
        self._test_start_btn.clicked.connect(self._test_start)
        picker_row.addWidget(self._test_start_btn)
        self._test_stop_btn = QPushButton(self.tr("Stop Test"))
        self._test_stop_btn.setEnabled(False)
        self._test_stop_btn.clicked.connect(lambda: self._test_stop())
        picker_row.addWidget(self._test_stop_btn)
        pfl.addLayout(picker_row)

        self._test_status_lbl = QLabel(self.tr("Not running"))
        self._test_status_lbl.setObjectName("statusText")
        self._test_status_lbl.setWordWrap(True)
        pfl.addWidget(self._test_status_lbl)

        self._load_test_profiles()
        outer.addWidget(profiles_card)
        outer.addStretch(1)
        return container

    def _refresh_controller_chamber_status(self):
        """Called from main_window's chamber connected/disconnected
        handlers (see _on_chamber_connected/_on_chamber_disconnected) so
        this page's read-only status readout stays in sync without polling."""
        connected = getattr(self, "_chamber_connected", False)
        chamber = getattr(self, "_active_chamber", None)
        self._ctrl_chamber_dot.setObjectName("chamberIconOn" if connected else "chamberIconOff")
        self._ctrl_chamber_dot.style().unpolish(self._ctrl_chamber_dot)
        self._ctrl_chamber_dot.style().polish(self._ctrl_chamber_dot)
        if connected and chamber:
            self._ctrl_chamber_status_lbl.setText(
                self.tr("Connected — {0} ({1}:{2})").format(
                    chamber.get("name", "?"), chamber.get("host", "?"), chamber.get("port", "?")
                )
            )
        else:
            self._ctrl_chamber_status_lbl.setText(
                self.tr("No chamber connected — connect one in Live Monitoring.")
            )
        self._on_test_profile_changed()

    # ── Manual Setpoint ──────────────────────────────────────────────────────

    def _on_manual_button_clicked(self):
        if self._manual_running:
            self._stop_manual_setpoint()
        else:
            self._start_manual_setpoint()

    def _start_manual_setpoint(self):
        temp_text = self._manual_temp_ed.text().strip()
        pressure_text = self._manual_pressure_ed.text().strip()
        if not temp_text and not pressure_text:
            QMessageBox.warning(
                self, self.tr("Start"), self.tr("Enter a temperature and/or pressure.")
            )
            return
        try:
            temp = float(temp_text) if temp_text else None
            pressure = float(pressure_text) if pressure_text else None
        except ValueError:
            QMessageBox.warning(
                self, self.tr("Start"), self.tr("Temperature/pressure must be numbers.")
            )
            return
        if not self.tcp.is_connected():
            QMessageBox.warning(self, self.tr("Start"), self.tr("Connect to a chamber first."))
            return
        if self._test_running_profile is not None:
            QMessageBox.warning(
                self, self.tr("Start"), self.tr("Stop the running test profile first.")
            )
            return
        payload = {
            "cmd": "set_point",
            "temperature": temp,
            "pressure": pressure,
            "step_index": None,
            "step_label": "Manual setpoint",
            "profile_name": None,
        }
        try:
            self.tcp.send_command(payload)
        except RuntimeError as exc:
            self._manual_status_lbl.setText(self.tr("Failed: {0}").format(str(exc)))
            return

        self._manual_running = True
        self._manual_started_at = time.monotonic()
        self._manual_temp_ed.setEnabled(False)
        self._manual_pressure_ed.setEnabled(False)
        self._manual_send_btn.setText(self.tr("Stop"))
        self._update_manual_elapsed_label()
        self._manual_timer = QTimer(self)
        self._manual_timer.timeout.connect(self._update_manual_elapsed_label)
        self._manual_timer.start(1000)
        self._on_test_profile_changed()

    def _stop_manual_setpoint(self, error=None):
        if not self._manual_running:
            return
        if self._manual_timer is not None:
            self._manual_timer.stop()
            self._manual_timer = None
        elapsed = time.monotonic() - self._manual_started_at if self._manual_started_at else 0.0
        self._manual_running = False
        self._manual_started_at = None
        self._manual_temp_ed.setEnabled(True)
        self._manual_pressure_ed.setEnabled(True)
        self._manual_send_btn.setText(self.tr("Start"))
        if error:
            self._manual_status_lbl.setText(self.tr("Stopped: {0}").format(error))
        else:
            self._manual_status_lbl.setText(
                self.tr("Stopped after {0}").format(_format_hms(elapsed))
            )
        self._on_test_profile_changed()

    def _update_manual_elapsed_label(self):
        if not self._manual_running or self._manual_started_at is None:
            return
        elapsed = time.monotonic() - self._manual_started_at
        self._manual_status_lbl.setText(self.tr("Running for {0}").format(_format_hms(elapsed)))

    # ── Test Profiles ────────────────────────────────────────────────────────

    def _load_test_profiles(self):
        previous = (
            self._test_profile_combo.currentData() if self._test_profile_combo.count() else None
        )
        self._test_profile_combo.blockSignals(True)
        self._test_profile_combo.clear()
        try:
            profiles = test_profiles_service.list_profiles()
        except Exception:
            profiles = []
        for profile in profiles:
            n = len(profile["steps"])
            self._test_profile_combo.addItem(f"{profile['name']}  ({n} step(s))", profile)
        if previous is not None:
            idx = next(
                (
                    i
                    for i in range(self._test_profile_combo.count())
                    if self._test_profile_combo.itemData(i)["id"] == previous["id"]
                ),
                0,
            )
            self._test_profile_combo.setCurrentIndex(idx)
        self._test_profile_combo.blockSignals(False)
        self._on_test_profile_changed()

    def _on_test_profile_changed(self):
        connected = self.tcp.is_connected()
        no_test_running = self._test_running_profile is None
        can_start_test = (
            connected
            and self._test_profile_combo.count() > 0
            and self._test_profile_combo.currentData() is not None
            and bool(self._test_profile_combo.currentData()["steps"])
            and no_test_running
            and not self._manual_running
        )
        self._test_start_btn.setEnabled(can_start_test)
        # Stop must always be clickable (even if the chamber just dropped)
        # so the user is never stuck with a "running" manual setpoint they
        # can't get out of; Start additionally needs a live connection and
        # no test profile currently running.
        self._manual_send_btn.setEnabled(self._manual_running or (connected and no_test_running))

    def _open_test_profiles_dialog(self):
        from app.test_profiles_dialog import TestProfilesDialog

        dlg = TestProfilesDialog(current_user=self.current_user, parent=self)
        dlg.exec()
        if dlg.changed:
            self._load_test_profiles()

    def _test_start(self):
        profile = self._test_profile_combo.currentData()
        if not profile or not profile["steps"]:
            return
        if not self.tcp.is_connected():
            QMessageBox.warning(self, self.tr("Start Test"), self.tr("Connect to a chamber first."))
            return
        if self._manual_running:
            QMessageBox.warning(
                self, self.tr("Start Test"), self.tr("Stop the manual setpoint first.")
            )
            return
        self._test_running_profile = profile
        self._session_test_profile_name = profile["name"]
        self._test_step_index = 0
        self._test_start_btn.setEnabled(False)
        self._test_stop_btn.setEnabled(True)
        self._test_profile_combo.setEnabled(False)
        self._manual_send_btn.setEnabled(False)
        self._test_send_current_step()

    def _test_send_current_step(self):
        profile = self._test_running_profile
        step = profile["steps"][self._test_step_index]
        payload = {
            "cmd": "set_point",
            "temperature": step["setpoint_temp"],
            "pressure": step["setpoint_pressure"],
            "step_index": self._test_step_index,
            "step_label": step["label"],
            "profile_name": profile["name"],
        }
        try:
            self.tcp.send_command(payload)
        except RuntimeError as exc:
            self._test_stop(error=str(exc))
            return

        self._test_step_started_at = time.monotonic()
        self._update_test_status_label()

        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(self._test_advance_step)
        self._test_timer.start(max(0, int(step["duration_s"] * 1000)))

        if self._test_tick_timer is None:
            self._test_tick_timer = QTimer(self)
            self._test_tick_timer.timeout.connect(self._update_test_status_label)
        self._test_tick_timer.start(1000)

    def _test_advance_step(self):
        if self._test_running_profile is None:
            return
        self._test_step_index += 1
        if self._test_step_index >= len(self._test_running_profile["steps"]):
            self._test_finish()
            return
        self._test_send_current_step()

    def _test_finish(self):
        name = self._test_running_profile["name"] if self._test_running_profile else ""
        self._test_status_lbl.setText(self.tr("Test '{0}' complete.").format(name))
        self._test_cleanup()

    def _test_stop(self, error=None):
        if self._test_running_profile is None:
            return
        if error:
            self._test_status_lbl.setText(self.tr("Test stopped: {0}").format(error))
        else:
            name = self._test_running_profile["name"]
            self._test_status_lbl.setText(self.tr("Test '{0}' stopped.").format(name))
        self._test_cleanup()

    def _test_cleanup(self):
        if self._test_timer is not None:
            self._test_timer.stop()
            self._test_timer = None
        if self._test_tick_timer is not None:
            self._test_tick_timer.stop()
        self._test_running_profile = None
        self._test_step_index = None
        self._test_step_started_at = None
        self._test_stop_btn.setEnabled(False)
        self._test_profile_combo.setEnabled(True)
        self._on_test_profile_changed()

    def _update_test_status_label(self):
        if self._test_running_profile is None:
            return
        profile = self._test_running_profile
        step = profile["steps"][self._test_step_index]
        elapsed = time.monotonic() - self._test_step_started_at
        remaining = max(0.0, step["duration_s"] - elapsed)
        parts = []
        if step["setpoint_temp"] is not None:
            parts.append(f"T={step['setpoint_temp']:g}")
        if step["setpoint_pressure"] is not None:
            parts.append(f"P={step['setpoint_pressure']:g}")
        setpoint_str = ", ".join(parts)
        label = step["label"] or self.tr("Step {0}").format(self._test_step_index + 1)
        self._test_status_lbl.setText(
            self.tr("Running '{0}' — step {1}/{2}: {3} ({4}) — {5:.0f}s remaining").format(
                profile["name"],
                self._test_step_index + 1,
                len(profile["steps"]),
                label,
                setpoint_str,
                remaining,
            )
        )
