"""Tests for the mission state machine, including hysteresis."""
from app.models.enums import MissionState
from app.models.mission_state import StateMachine

HEALTHY = dict(battery=90.0, temperature=30.0, signal=80.0, in_pass=True)


def conditions(**changes):
    return {**HEALTHY, **changes}


def test_healthy_satellite_is_nominal():
    assert StateMachine().evaluate(**HEALTHY) is MissionState.NOMINAL


def test_nominal_to_low_power():
    machine = StateMachine()
    old, new, reason = machine.update(**conditions(battery=20))
    assert (old, new) == (MissionState.NOMINAL, MissionState.LOW_POWER)
    assert reason
    assert machine.history[-1][1] is MissionState.LOW_POWER


def test_nominal_to_thermal_alert():
    machine = StateMachine()
    machine.update(**conditions(temperature=63))
    assert machine.state is MissionState.THERMAL_ALERT


def test_severe_thermal_goes_to_safe_mode():
    assert StateMachine().evaluate(**conditions(temperature=72)) is MissionState.SAFE_MODE


def test_critical_battery_goes_to_safe_mode():
    assert StateMachine().evaluate(**conditions(battery=12)) is MissionState.SAFE_MODE


def test_thermal_recovery_uses_hysteresis():
    machine = StateMachine()
    machine.update(**conditions(temperature=63))
    # 58 °C is below the 60 °C trigger but above the 55 °C recovery level: stay in alert.
    assert machine.evaluate(**conditions(temperature=58)) is MissionState.THERMAL_ALERT
    machine.update(**conditions(temperature=54))
    assert machine.state is MissionState.NOMINAL


def test_low_power_recovery_uses_hysteresis():
    machine = StateMachine()
    machine.update(**conditions(battery=20))
    assert machine.evaluate(**conditions(battery=26)) is MissionState.LOW_POWER
    assert machine.evaluate(**conditions(battery=29)) is MissionState.NOMINAL


def test_comm_failure_and_forced_safe_mode():
    machine = StateMachine()
    assert machine.evaluate(**HEALTHY, comm_failure=True) is MissionState.COMMUNICATION_LOSS
    assert machine.evaluate(**HEALTHY, forced_safe=True) is MissionState.SAFE_MODE


def test_degraded_link_only_counts_during_a_pass():
    machine = StateMachine()
    assert machine.evaluate(**conditions(signal=25)) is MissionState.DEGRADED_LINK
    assert machine.evaluate(**conditions(signal=2, in_pass=False)) is MissionState.NOMINAL


def test_update_returns_none_when_nothing_changes():
    assert StateMachine().update(**HEALTHY) is None
