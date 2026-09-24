"""State changes and one-shot threshold crossing alerts."""

from __future__ import annotations
from app import config
from app.models.enums import MissionState
from app.models.mission_state import StateMachine
from app.models.telemetry import TelemetrySnapshot


class HealthMonitor:
    """Converts sensor readings into state transitions and alerts."""

    def __init__(self, state_machine: StateMachine):
        self.state_machine = state_machine
        self._crossed: set[str] = set()

    def check(
        self, snapshot: TelemetrySnapshot, comm_failure: bool, forced_safe: bool
    ) -> tuple[tuple[MissionState, MissionState, str] | None, list[tuple[str, str]]]:
        """Check thresholds; emit an alert only on entry to each bad range."""
        transition = self.state_machine.update(
            snapshot.battery,
            snapshot.temperature,
            snapshot.signal,
            snapshot.in_pass,
            comm_failure,
            forced_safe,
        )
        checks = {
            "battery_low": (
                snapshot.battery < config.BATTERY_LOW_THRESHOLD,
                "WARNING",
                "Battery below low-power threshold",
            ),
            "battery_critical": (
                snapshot.battery < config.BATTERY_CRITICAL_THRESHOLD,
                "CRITICAL",
                "Battery reserve critical",
            ),
            "thermal_warning": (
                snapshot.temperature > config.TEMP_WARNING_THRESHOLD,
                "WARNING",
                "Thermal warning threshold crossed",
            ),
            "thermal_critical": (
                snapshot.temperature > config.TEMP_CRITICAL_THRESHOLD,
                "CRITICAL",
                "Thermal critical threshold crossed",
            ),
            "signal_low": (
                snapshot.in_pass and snapshot.signal < config.SIGNAL_MIN_THRESHOLD,
                "WARNING",
                "Ground link signal is weak",
            ),
        }
        alerts = []
        for name, (active, severity, message) in checks.items():
            if active and name not in self._crossed:
                alerts.append((severity, message))
                self._crossed.add(name)
            elif not active:
                self._crossed.discard(name)
        return transition, alerts
