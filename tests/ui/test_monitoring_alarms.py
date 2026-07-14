"""Tests for app/views/monitoring.py's alarm evaluation state machine
(_evaluate_alarms): deadband (hysteresis) and delay (debounce) behavior,
and that trigger/clear transitions are persisted via alarms_service.

time.monotonic() is monkeypatched to a controllable fake clock so delay_s
behavior can be tested deterministically without real sleeps.
"""

import pytest

from app.main_window import DeepVacDesktop
from app.services import alarms_service

pytestmark = pytest.mark.ui


@pytest.fixture
def window(deepvac_ui, fake_user, qtbot):
    win = DeepVacDesktop(current_user=fake_user)
    qtbot.addWidget(win)
    win.restore_window_state()
    return win


@pytest.fixture
def fake_clock(monkeypatch):
    # _evaluate_alarms() does `import time` locally, which still binds to
    # the one process-wide `time` module object (sys.modules cache) -- so
    # patching time.monotonic here reaches it, even though app.views.
    # monitoring has no module-level `time` attribute to patch instead.
    import time

    state = {"t": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: state["t"])
    return state


def _rule(**overrides):
    base = {
        "id": 1,
        "name": "High Temp",
        "variable": "temp",
        "condition": "above",
        "value": 80.0,
        "value2": None,
        "severity": "Critical",
        "deadband": 0.0,
        "delay_s": 0.0,
        "_active": False,
        "_last_value": None,
        "_condition_since": None,
        "_event_id": None,
    }
    base.update(overrides)
    return base


def test_above_condition_triggers_immediately_with_no_delay(deepvac_data_dir, window):
    rule = alarms_service.add_rule("High Temp", "temp", "above", 80.0, None, "Critical")
    window._monitor_alarms = [_rule(id=rule["id"])]

    window._evaluate_alarms({"temp": 85.0})

    assert window._monitor_alarms[0]["_active"] is True
    events = alarms_service.list_events()
    assert len(events) == 1
    assert events[0]["trigger_value"] == 85.0


def test_below_threshold_never_triggers(deepvac_data_dir, window):
    rule = alarms_service.add_rule("High Temp", "temp", "above", 80.0, None, "Critical")
    window._monitor_alarms = [_rule(id=rule["id"])]

    window._evaluate_alarms({"temp": 50.0})

    assert window._monitor_alarms[0]["_active"] is False
    assert alarms_service.list_events() == []


def test_delay_suppresses_trigger_until_elapsed(deepvac_data_dir, window, fake_clock):
    rule = alarms_service.add_rule(
        "High Temp", "temp", "above", 80.0, None, "Critical", delay_s=10.0
    )
    window._monitor_alarms = [_rule(id=rule["id"], delay_s=10.0)]

    fake_clock["t"] = 0.0
    window._evaluate_alarms({"temp": 85.0})
    assert window._monitor_alarms[0]["_active"] is False  # condition just started

    fake_clock["t"] = 5.0
    window._evaluate_alarms({"temp": 85.0})
    assert window._monitor_alarms[0]["_active"] is False  # delay not yet elapsed

    fake_clock["t"] = 10.0
    window._evaluate_alarms({"temp": 85.0})
    assert window._monitor_alarms[0]["_active"] is True  # delay elapsed
    assert len(alarms_service.list_events()) == 1


def test_delay_resets_if_condition_stops_holding(deepvac_data_dir, window, fake_clock):
    rule = alarms_service.add_rule(
        "High Temp", "temp", "above", 80.0, None, "Critical", delay_s=10.0
    )
    window._monitor_alarms = [_rule(id=rule["id"], delay_s=10.0)]

    fake_clock["t"] = 0.0
    window._evaluate_alarms({"temp": 85.0})
    fake_clock["t"] = 5.0
    window._evaluate_alarms({"temp": 50.0})  # drops below threshold -- resets the timer
    fake_clock["t"] = 8.0
    window._evaluate_alarms({"temp": 85.0})  # condition restarts here, not at t=0

    assert window._monitor_alarms[0]["_active"] is False
    assert alarms_service.list_events() == []


def test_deadband_prevents_premature_clear(deepvac_data_dir, window):
    rule = alarms_service.add_rule(
        "High Temp", "temp", "above", 80.0, None, "Critical", deadband=5.0
    )
    window._monitor_alarms = [_rule(id=rule["id"], deadband=5.0)]

    window._evaluate_alarms({"temp": 85.0})
    assert window._monitor_alarms[0]["_active"] is True

    # Value drops back below the raw threshold (80) but stays within the
    # deadband zone (must go below 80 - 5 = 75 to actually clear).
    window._evaluate_alarms({"temp": 78.0})
    assert window._monitor_alarms[0]["_active"] is True

    window._evaluate_alarms({"temp": 70.0})
    assert window._monitor_alarms[0]["_active"] is False
    events = alarms_service.list_events()
    assert events[0]["cleared_at"] is not None


def test_outside_range_condition(deepvac_data_dir, window):
    rule = alarms_service.add_rule(
        "Out of Range", "pressure", "outside range", 10.0, 20.0, "Warning"
    )
    window._monitor_alarms = [
        _rule(
            id=rule["id"], variable="pressure", condition="outside range", value=10.0, value2=20.0
        )
    ]

    window._evaluate_alarms({"pressure": 5.0})
    assert window._monitor_alarms[0]["_active"] is True

    window._evaluate_alarms({"pressure": 15.0})
    assert window._monitor_alarms[0]["_active"] is False


def test_non_numeric_sample_value_is_skipped_without_error(deepvac_data_dir, window):
    rule = alarms_service.add_rule("High Temp", "temp", "above", 80.0, None, "Critical")
    window._monitor_alarms = [_rule(id=rule["id"])]

    window._evaluate_alarms({"temp": None})  # must not raise
    assert window._monitor_alarms[0]["_active"] is False


def test_delete_alarm_removes_rule_from_persistence(deepvac_data_dir, window):
    rule = alarms_service.add_rule("High Temp", "temp", "above", 80.0, None, "Critical")
    window._monitor_alarms = [_rule(id=rule["id"])]

    window._delete_alarm(0)

    assert window._monitor_alarms == []
    assert alarms_service.list_rules() == []
