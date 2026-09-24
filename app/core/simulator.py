"""Live sensor simulation around the satellite and ground-pass models."""
from __future__ import annotations
import numpy as np
from app import config
from app.core.ground_pass import GroundPass, PassInfo
from app.models.communication_modes import CommunicationMode
from app.models.enums import MissionState
from app.models.satellite import Satellite
from app.models.telemetry import TelemetrySnapshot
from app.utils.helpers import now_iso
from app.utils.validation import clamp

class TelemetrySimulator:
    """Advances battery, thermal, and RF telemetry one tick at a time."""
    def __init__(self, satellite: Satellite, ground_pass: GroundPass, rng: np.random.Generator):
        self.satellite, self.ground_pass, self.rng = satellite, ground_pass, rng
    def step(self, mission_time: float, orbit_time: float, dt: float, active_mode: CommunicationMode | None,
             state: MissionState, signal_attenuation: float = 1.0, queue_size: int = 0,
             comm_state: str = "") -> tuple[TelemetrySnapshot, PassInfo]:
        """Calculate one simulated frame; an injected bad frame tests recovery."""
        info = self.ground_pass.info(orbit_time)
        draw = config.SAFE_MODE_POWER_DRAW if state is MissionState.SAFE_MODE else config.BASE_POWER_DRAW + (active_mode.power_draw if active_mode else 0.0)
        self.satellite.power.set_load(draw)
        self.satellite.power.consume_power(draw, dt)
        if info.sunlit:
            self.satellite.power.recharge(config.SOLAR_INPUT_W, dt)
        temperature = self.satellite.thermal.update(draw, info.sunlit, dt, float(self.rng.normal(0, config.THERMAL_NOISE_STD)))
        signal = self.ground_pass.signal_profile(info, self.rng) * signal_attenuation
        loss = clamp(1 + 25 * (1 - signal / 100) ** 2 + float(self.rng.normal(0, 0.6)), 0, 100) if info.in_pass else 0.0
        battery = self.satellite.power.battery_level
        if self.rng.random() < config.TELEMETRY_CORRUPTION_PROBABILITY:
            battery = float("nan")
        snapshot = TelemetrySnapshot(mission_time, battery, self.satellite.power.voltage, temperature,
                                     signal, draw, loss, queue_size, state.value,
                                     comm_state or ("LINK READY" if info.in_pass else "NO PASS"),
                                     info.phase.value, info.in_pass, info.sunlit, now_iso())
        return snapshot, info
