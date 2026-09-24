from app.models.mission_state import StateMachine
from app.models.enums import MissionState

def test_states_and_hysteresis():
    sm = StateMachine()
    args = dict(battery=90, temperature=27, signal=90, in_pass=True)
    assert sm.update(**{**args, "battery": 20})[1] == MissionState.LOW_POWER
    sm.reset()
    assert sm.update(**{**args, "temperature": 62})[1] == MissionState.THERMAL_ALERT
    assert sm.evaluate(**{**args, "temperature": 58}) == MissionState.THERMAL_ALERT
    assert sm.evaluate(**{**args, "temperature": 54}) == MissionState.NOMINAL
    assert sm.evaluate(**{**args, "temperature": 71}) == MissionState.SAFE_MODE
    assert sm.evaluate(**args, comm_failure=True) == MissionState.COMMUNICATION_LOSS
    assert sm.evaluate(**args, forced_safe=True) == MissionState.SAFE_MODE
