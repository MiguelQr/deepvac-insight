"""ControllerMixin — builds the Controller page: Test Profiles (multi-step
temperature/pressure schedules) and the step-sequencer that runs one
against whichever chamber is connected via Live Monitoring.

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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import app.services.test_profiles_service as test_profiles_service


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
        sub = QLabel(
            self.tr(
                "Run multi-step temperature/pressure test profiles against the chamber "
                "connected in Live Monitoring."
            )
        )
        sub.setObjectName("sectionLabel")
        sub.setWordWrap(True)
        outer.addWidget(sub)

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
        pfdesc = QLabel(
            self.tr(
                "Multi-step temperature/pressure schedules -- Start Test sends each "
                "step's setpoint to the connected chamber in turn."
            )
        )
        pfdesc.setObjectName("sectionLabel")
        pfdesc.setWordWrap(True)
        profiles_hdr.addWidget(pfdesc, 1)
        manage_profiles_btn = QPushButton(self.tr("Manage Test Profiles…"))
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
        can_start = (
            self.tcp.is_connected()
            and self._test_profile_combo.count() > 0
            and self._test_profile_combo.currentData() is not None
            and bool(self._test_profile_combo.currentData()["steps"])
            and self._test_running_profile is None
        )
        self._test_start_btn.setEnabled(can_start)

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
        self._test_running_profile = profile
        self._session_test_profile_name = profile["name"]
        self._test_step_index = 0
        self._test_start_btn.setEnabled(False)
        self._test_stop_btn.setEnabled(True)
        self._test_profile_combo.setEnabled(False)
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
