"""Tests for app/views/controller.py's Test Profile step-sequencer
(_test_start/_test_send_current_step/_test_advance_step/_test_stop) --
steps through a profile's schedule and sends each step's setpoint via
ChamberConnection.send_command() as its turn comes up.

window.tcp.is_connected()/send_command() are monkeypatched so this
exercises the sequencing logic in isolation from real sockets (see
tests/integration/test_tcp_client.py for the real wire-protocol
verification). Step durations are kept tiny (real seconds, not faked) so
the real QTimer machinery drives the test at normal speed.
"""

import pytest

from app.main_window import DeepVacDesktop
from app.services import test_profiles_service as profiles

pytestmark = pytest.mark.ui


@pytest.fixture
def window(deepvac_ui, fake_user, qtbot):
    win = DeepVacDesktop(current_user=fake_user)
    qtbot.addWidget(win)
    win.restore_window_state()
    return win


@pytest.fixture
def connected_tcp(window, monkeypatch):
    sent = []
    monkeypatch.setattr(window.tcp, "is_connected", lambda: True)
    monkeypatch.setattr(window.tcp, "send_command", lambda payload: sent.append(payload))
    return sent


def _select_profile(window, profile_id):
    window._load_test_profiles()
    idx = next(
        i
        for i in range(window._test_profile_combo.count())
        if window._test_profile_combo.itemData(i)["id"] == profile_id
    )
    window._test_profile_combo.setCurrentIndex(idx)


def test_start_test_sends_first_step_immediately(deepvac_data_dir, window, connected_tcp):
    profile = profiles.add_profile(
        "Quick Test",
        "",
        [
            {
                "setpoint_temp": 50.0,
                "setpoint_pressure": None,
                "duration_s": 5.0,
                "label": "Step 1",
            },
            {
                "setpoint_temp": 80.0,
                "setpoint_pressure": None,
                "duration_s": 5.0,
                "label": "Step 2",
            },
        ],
    )
    _select_profile(window, profile["id"])

    window._test_start()

    assert len(connected_tcp) == 1
    assert connected_tcp[0]["cmd"] == "set_point"
    assert connected_tcp[0]["temperature"] == 50.0
    assert connected_tcp[0]["step_index"] == 0
    assert connected_tcp[0]["profile_name"] == "Quick Test"
    assert window._test_running_profile is not None
    assert window._test_stop_btn.isEnabled() is True
    assert window._test_start_btn.isEnabled() is False


def test_sequencer_advances_through_all_steps_and_completes(
    deepvac_data_dir, window, connected_tcp, qtbot
):
    profile = profiles.add_profile(
        "Quick Test",
        "",
        [
            {
                "setpoint_temp": 50.0,
                "setpoint_pressure": None,
                "duration_s": 0.05,
                "label": "Step 1",
            },
            {
                "setpoint_temp": 80.0,
                "setpoint_pressure": None,
                "duration_s": 0.05,
                "label": "Step 2",
            },
        ],
    )
    _select_profile(window, profile["id"])

    window._test_start()
    qtbot.waitUntil(lambda: len(connected_tcp) == 2, timeout=2000)
    assert connected_tcp[1]["temperature"] == 80.0
    assert connected_tcp[1]["step_index"] == 1

    qtbot.waitUntil(lambda: window._test_running_profile is None, timeout=2000)
    assert "complete" in window._test_status_lbl.text().lower()
    assert window._test_stop_btn.isEnabled() is False


def test_stop_test_cancels_a_running_sequence(deepvac_data_dir, window, connected_tcp):
    profile = profiles.add_profile(
        "Long Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 30.0, "label": ""}],
    )
    _select_profile(window, profile["id"])

    window._test_start()
    assert window._test_running_profile is not None

    window._test_stop()

    assert window._test_running_profile is None
    assert window._test_stop_btn.isEnabled() is False
    assert "stopped" in window._test_status_lbl.text().lower()


def test_start_test_disabled_without_a_connected_chamber(deepvac_data_dir, window):
    profile = profiles.add_profile(
        "Quick Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 5.0, "label": ""}],
    )
    _select_profile(window, profile["id"])
    assert window.tcp.is_connected() is False
    assert window._test_start_btn.isEnabled() is False


def test_send_command_failure_mid_test_stops_and_reports_error(
    deepvac_data_dir, window, monkeypatch
):
    profile = profiles.add_profile(
        "Quick Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 30.0, "label": ""}],
    )
    monkeypatch.setattr(window.tcp, "is_connected", lambda: True)

    def _raise(payload):
        raise RuntimeError("chamber not connected")

    monkeypatch.setattr(window.tcp, "send_command", _raise)
    _select_profile(window, profile["id"])

    window._test_start()

    assert window._test_running_profile is None
    assert "chamber not connected" in window._test_status_lbl.text()


def test_saving_session_after_running_a_test_tags_the_run_with_its_profile(
    deepvac_data_dir, window, connected_tcp, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    profile = profiles.add_profile(
        "Quick Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 30.0, "label": ""}],
    )
    window._active_chamber = {"id": 1, "name": "Chamber 1", "host": "127.0.0.1", "port": 5555}
    _select_profile(window, profile["id"])
    window._test_start()

    window._mon_buffer = [{"timestamp": "1700000000", "temp": "20.0"}]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("live-test", True)))

    window._save_monitoring_session()

    from app.services import data_service

    runs = data_service.load_cached_runs()
    assert runs[0]["chamber"] == "Chamber 1"
    assert runs[0]["test_profile"] == "Quick Test"
