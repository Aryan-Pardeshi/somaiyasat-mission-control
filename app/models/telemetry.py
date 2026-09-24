"""Validated telemetry frames sent across the event bus."""
from dataclasses import dataclass, asdict
import math
from app import config
from app.exceptions import TelemetryCorruptionError
from app.utils.validation import is_valid_percentage

@dataclass
class TelemetrySnapshot:
    """One live or replay sensor reading."""
    mission_time: float
    battery: float
    voltage: float
    temperature: float
    signal: float
    power_draw: float
    packet_loss: float
    queue_size: int
    system_state: str
    comm_state: str
    pass_phase: str
    in_pass: bool
    sunlit: bool
    timestamp: str

    def validate(self) -> None:
        """Reject impossible or nonfinite sensor values."""
        values = (self.mission_time, self.battery, self.voltage, self.temperature, self.signal, self.power_draw, self.packet_loss)
        if not all(math.isfinite(float(v)) for v in values):
            raise TelemetryCorruptionError("Nonfinite telemetry value")
        if not all(is_valid_percentage(v) for v in (self.battery, self.signal, self.packet_loss)):
            raise TelemetryCorruptionError("Percentage outside 0..100")
        if not config.REPLAY_TEMP_RANGE[0] <= self.temperature <= config.REPLAY_TEMP_RANGE[1] or self.power_draw < 0:
            raise TelemetryCorruptionError("Temperature or power outside valid range")

    def to_dict(self) -> dict:
        """Return plain data safe to move between threads."""
        return asdict(self)
