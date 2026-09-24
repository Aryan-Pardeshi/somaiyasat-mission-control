"""Priority-ordered health state machine with recovery hysteresis."""
from __future__ import annotations
from app import config
from app.models.enums import MissionState

STATE_DESCRIPTIONS: dict[MissionState, str] = {
    MissionState.NOMINAL: "All spacecraft systems are operating normally.",
    MissionState.LOW_POWER: "Battery reserve is low and expensive modes are suspended.",
    MissionState.DEGRADED_LINK: "The ground link is weak while in pass.",
    MissionState.THERMAL_ALERT: "Spacecraft temperature is above the warning threshold.",
    MissionState.SAFE_MODE: "Only critical control traffic may be transmitted.",
    MissionState.COMMUNICATION_LOSS: "The radio link is unavailable.",
}

class StateMachine:
    """Chooses the highest-severity current operating state."""
    def __init__(self):
        self.state = MissionState.NOMINAL
        self.history: list[tuple[MissionState, MissionState, str]] = []
    def evaluate(self, battery: float, temperature: float, signal: float, in_pass: bool,
                 comm_failure: bool = False, forced_safe: bool = False) -> MissionState:
        """Decide state without mutating history."""
        # Recovery margins keep readings near thresholds from flickering the UI.
        keep_safe = self.state is MissionState.SAFE_MODE and (battery < config.BATTERY_CRITICAL_THRESHOLD + config.BATTERY_RECOVERY_MARGIN or temperature > config.TEMP_WARNING_THRESHOLD)
        if forced_safe or battery < config.BATTERY_CRITICAL_THRESHOLD or temperature > config.TEMP_CRITICAL_THRESHOLD or keep_safe:
            return MissionState.SAFE_MODE
        if comm_failure:
            return MissionState.COMMUNICATION_LOSS
        if temperature > config.TEMP_WARNING_THRESHOLD or self.state is MissionState.THERMAL_ALERT and temperature > config.TEMP_WARNING_THRESHOLD - config.TEMP_RECOVERY_MARGIN:
            return MissionState.THERMAL_ALERT
        if battery < config.BATTERY_LOW_THRESHOLD or self.state is MissionState.LOW_POWER and battery < config.BATTERY_LOW_THRESHOLD + config.BATTERY_RECOVERY_MARGIN:
            return MissionState.LOW_POWER
        if in_pass and signal < config.DEGRADED_LINK_THRESHOLD:
            return MissionState.DEGRADED_LINK
        return MissionState.NOMINAL
    def reason_for(self, state: MissionState, battery: float, temperature: float, signal: float,
                   comm_failure: bool, forced_safe: bool) -> str:
        """Explain a state transition for logs and the archive."""
        if state is MissionState.SAFE_MODE:
            return f"Safe mode: battery {battery:.1f} %, temperature {temperature:.1f} °C" + ("; operator forced" if forced_safe else "")
        if state is MissionState.COMMUNICATION_LOSS:
            return "RF communication failure"
        if state is MissionState.THERMAL_ALERT:
            return f"Temperature {temperature:.1f} °C exceeds safe operating range"
        if state is MissionState.LOW_POWER:
            return f"Battery {battery:.1f} % requires reduced load"
        if state is MissionState.DEGRADED_LINK:
            return f"Signal {signal:.1f} % is degraded"
        return "Conditions restored to nominal"
    def update(self, battery: float, temperature: float, signal: float, in_pass: bool,
               comm_failure: bool = False, forced_safe: bool = False) -> tuple[MissionState, MissionState, str] | None:
        """Apply a transition and record it when state changes."""
        new = self.evaluate(battery, temperature, signal, in_pass, comm_failure, forced_safe)
        if new is self.state:
            return None
        old = self.state
        self.state = new
        result = (old, new, self.reason_for(new, battery, temperature, signal, comm_failure, forced_safe))
        self.history.append(result)
        return result
    def reset(self) -> None:
        """Clear state and transition history."""
        self.state = MissionState.NOMINAL
        self.history.clear()
