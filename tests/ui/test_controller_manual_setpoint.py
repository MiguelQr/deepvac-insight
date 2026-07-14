"""Tests for app/views/controller.py's Manual Setpoint Start/Stop toggle
(_start_manual_setpoint/_stop_manual_setpoint) -- an ad-hoc temperature/
pressure command sent to the connected chamber, tracked with its own
running/elapsed-time state, independent of Test Profiles.

time.monotonic() is monkeypatched to a controllable fake clock so the
elapsed-time counter can be tested deterministically without real sleeps.
"""

import pytest

from app.main_window import DeepVacDesktop

pytestmark = pytest.mark.ui


@pytest.fixture
def window(deepvac_ui, fake_user, qtbot):
    win = DeepVacDesktop(current_user=fake_user)
    qtbot.addWidget(win)
    win.restore_window_state()
    win._nav_to(6)
    return win


@pytest.fixture
def connected_tcp(window, monkeypatch):
    sent = []
    monkeypatch.setattr(window.tcp, "is_connected", lambda: True)
    monkeypatch.setattr(window.tcp, "send_command", lambda payload: sent.append(payload))
    window._refresh_controller_chamber_status()
    return sent


@pytest.fixture
def fake_clock(monkeypatch):
    # _start_manual_setpoint()/_update_manual_elapsed_label() do `import
    # time` at module level in controller.py -- patching the real time
    # module's monotonic reaches it since it's the same process-wide
    # singleton object.
    import time

    state = {"t": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: state["t"])
    return state


def test_manual_button_disabled_without_a_connected_chamber(deepvac_data_dir, window):
    assert window._manual_send_btn.isEnabled() is False


def test_manual_button_enabled_once_connected(deepvac_data_dir, window, connected_tcp):
    assert window._manual_send_btn.isEnabled() is True


def test_start_sends_temperature_only(deepvac_data_dir, window, connected_tcp):
    window._manual_temp_ed.setText("75.5")
    window._manual_pressure_ed.setText("")

    window._start_manual_setpoint()

    assert len(connected_tcp) == 1
    assert connected_tcp[0] == {
        "cmd": "set_point",
        "temperature": 75.5,
        "pressure": None,
        "step_index": None,
        "step_label": "Manual setpoint",
        "profile_name": None,
    }
    assert window._manual_running is True
    assert window._manual_send_btn.text() == "Stop"
    assert "Running for" in window._manual_status_lbl.text()


def test_start_sends_pressure_only(deepvac_data_dir, window, connected_tcp):
    window._manual_temp_ed.setText("")
    window._manual_pressure_ed.setText("2.25")

    window._start_manual_setpoint()

    assert connected_tcp[0]["temperature"] is None
    assert connected_tcp[0]["pressure"] == 2.25


def test_start_sends_both_temperature_and_pressure(deepvac_data_dir, window, connected_tcp):
    window._manual_temp_ed.setText("60")
    window._manual_pressure_ed.setText("1.5")

    window._start_manual_setpoint()

    assert connected_tcp[0]["temperature"] == 60.0
    assert connected_tcp[0]["pressure"] == 1.5


def test_start_with_neither_field_set_does_not_send(deepvac_data_dir, window, connected_tcp):
    window._manual_temp_ed.setText("")
    window._manual_pressure_ed.setText("")

    window._start_manual_setpoint()

    assert connected_tcp == []
    assert window._manual_running is False


def test_start_with_non_numeric_text_does_not_send(deepvac_data_dir, window, connected_tcp):
    window._manual_temp_ed.setText("warm")

    window._start_manual_setpoint()

    assert connected_tcp == []
    assert window._manual_running is False


def test_start_without_connection_does_not_raise(deepvac_data_dir, window):
    window._manual_temp_ed.setText("50")
    window._start_manual_setpoint()  # tcp not connected -- must not raise
    assert window._manual_running is False


def test_fields_disabled_while_running_and_reenabled_after_stop(
    deepvac_data_dir, window, connected_tcp
):
    window._manual_temp_ed.setText("50")
    window._start_manual_setpoint()

    assert window._manual_temp_ed.isEnabled() is False
    assert window._manual_pressure_ed.isEnabled() is False

    window._stop_manual_setpoint()

    assert window._manual_temp_ed.isEnabled() is True
    assert window._manual_pressure_ed.isEnabled() is True
    assert window._manual_send_btn.text() == "Start"
    assert window._manual_running is False


def test_elapsed_counter_ticks_up_while_running(
    deepvac_data_dir, window, connected_tcp, fake_clock
):
    window._manual_temp_ed.setText("50")
    fake_clock["t"] = 0.0
    window._start_manual_setpoint()
    assert "00:00:00" in window._manual_status_lbl.text()

    fake_clock["t"] = 65.0  # 1 minute 5 seconds later
    window._update_manual_elapsed_label()
    assert "00:01:05" in window._manual_status_lbl.text()


def test_stop_reports_total_elapsed_time(deepvac_data_dir, window, connected_tcp, fake_clock):
    window._manual_temp_ed.setText("50")
    fake_clock["t"] = 100.0
    window._start_manual_setpoint()

    fake_clock["t"] = 100.0 + 30.0
    window._stop_manual_setpoint()

    assert "00:00:30" in window._manual_status_lbl.text()
    assert "Stopped" in window._manual_status_lbl.text()


def test_manual_button_disabled_while_a_test_profile_is_running(
    deepvac_data_dir, window, connected_tcp
):
    from app.services import test_profiles_service as profiles

    profile = profiles.add_profile(
        "Quick Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 30.0, "label": ""}],
    )
    window._load_test_profiles()
    idx = next(
        i
        for i in range(window._test_profile_combo.count())
        if window._test_profile_combo.itemData(i)["id"] == profile["id"]
    )
    window._test_profile_combo.setCurrentIndex(idx)

    window._test_start()

    assert window._manual_send_btn.isEnabled() is False

    window._test_stop()

    assert window._manual_send_btn.isEnabled() is True


def test_start_test_blocked_while_manual_setpoint_running(deepvac_data_dir, window, connected_tcp):
    from app.services import test_profiles_service as profiles

    profile = profiles.add_profile(
        "Quick Test",
        "",
        [{"setpoint_temp": 50.0, "setpoint_pressure": None, "duration_s": 30.0, "label": ""}],
    )
    window._load_test_profiles()
    idx = next(
        i
        for i in range(window._test_profile_combo.count())
        if window._test_profile_combo.itemData(i)["id"] == profile["id"]
    )
    window._test_profile_combo.setCurrentIndex(idx)

    window._manual_temp_ed.setText("50")
    window._start_manual_setpoint()

    window._test_start()

    assert window._test_running_profile is None
