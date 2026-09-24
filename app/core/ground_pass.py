"""Compressed orbit geometry and CSV-derived ground-pass windows."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
from app import config
from app.models.enums import PassPhase
from app.utils.validation import clamp

@dataclass
class PassInfo:
    """Current visibility and orbit information for a ground station."""
    phase: PassPhase
    in_pass: bool
    orbit_angle: float
    progress: float
    seconds_to_aos: float
    seconds_to_los: float
    sunlit: bool
    pass_number: int
    def to_dict(self) -> dict:
        """Return a plain event payload."""
        return {**asdict(self), "phase": self.phase.value}

class GroundPass:
    """Periodic live visibility model with a smooth signal profile."""
    def __init__(self, period: float = config.ORBIT_PERIOD, duration: float = config.PASS_DURATION,
                 station_angle: float = config.GROUND_STATION_ANGLE,
                 initial_time_to_aos: float = config.INITIAL_TIME_TO_AOS):
        self.period, self.duration = period, duration
        self.station_angle, self.initial_time_to_aos = station_angle, initial_time_to_aos
    @property
    def half_arc(self) -> float:
        """Visible half-arc in degrees."""
        return 180 * self.duration / self.period
    def orbit_angle(self, t: float) -> float:
        """Return smooth counterclockwise satellite angle."""
        phase_t = (t - self.initial_time_to_aos) % self.period
        return (self.station_angle - self.half_arc + 360 * phase_t / self.period) % 360
    def info(self, t: float) -> PassInfo:
        """Calculate phase, countdowns, sunlight, and position."""
        phase_t = (t - self.initial_time_to_aos) % self.period
        in_pass = phase_t < self.duration and t >= self.initial_time_to_aos
        if in_pass:
            phase = PassPhase.AOS if phase_t < config.AOS_PHASE_DURATION else PassPhase.ACTIVE
        else:
            phase = PassPhase.LOS if t >= self.initial_time_to_aos and phase_t - self.duration < config.LOS_PHASE_DURATION and phase_t >= self.duration else PassPhase.PRE_PASS
        angle = self.orbit_angle(t)
        sunlit = math.cos(math.radians(angle - config.SUN_DIRECTION_ANGLE)) > config.SUNLIT_COSINE_LIMIT
        to_aos = 0.0 if in_pass else self.initial_time_to_aos - t if t < self.initial_time_to_aos else self.period - phase_t
        return PassInfo(phase, in_pass, angle, phase_t / self.duration if in_pass else 0.0,
                        to_aos, max(0.0, self.duration - phase_t) if in_pass else 0.0,
                        sunlit, max(0, math.floor((t - self.initial_time_to_aos) / self.period) + 1))
    def signal_profile(self, info: PassInfo, rng: np.random.Generator) -> float:
        """Model a stronger link around the middle of a pass."""
        if not info.in_pass:
            return float(rng.uniform(0, config.OUT_OF_PASS_SIGNAL_MAX))
        signal = config.MIN_PASS_SIGNAL + (config.PEAK_PASS_SIGNAL - config.MIN_PASS_SIGNAL) * math.sin(math.pi * info.progress) ** 0.8
        return float(clamp(signal + rng.normal(0, config.SIGNAL_NOISE_STD), 0, 100))
    def next_aos_offset(self, t: float) -> float:
        """Seconds until the next acquisition of signal."""
        if t < self.initial_time_to_aos:
            return self.initial_time_to_aos - t
        phase_t = (t - self.initial_time_to_aos) % self.period
        return self.period - phase_t

class ReplayGroundPass(GroundPass):
    """Visibility derived from actual replay signal intervals."""
    def __init__(self, windows: list[tuple[float, float]], period: float = config.ORBIT_PERIOD):
        super().__init__(period=period)
        self.windows = sorted(windows)
    def info(self, t: float) -> PassInfo:
        """Interpolate around each CSV-derived pass window."""
        for index, (start, end) in enumerate(self.windows):
            if start <= t <= end:
                duration = max(end - start, 1e-9)
                progress = clamp((t - start) / duration, 0, 1)
                angle = (self.station_angle - self.half_arc + 2 * self.half_arc * progress) % 360
                phase = PassPhase.AOS if t - start < config.AOS_PHASE_DURATION else PassPhase.ACTIVE
                return PassInfo(phase, True, angle, progress, 0.0, max(0, end - t), self._sunlit(angle), index + 1)
        future = [(i, s) for i, (s, _) in enumerate(self.windows) if s > t]
        if future:
            index, next_start = future[0]
            previous_end = self.windows[index - 1][1] if index else next_start - self.period
            phase = PassPhase.LOS if index and t - previous_end < config.LOS_PHASE_DURATION else PassPhase.PRE_PASS
            gap = max(next_start - previous_end, 1e-9)
            angle = (self.station_angle + self.half_arc + (360 - 2 * self.half_arc) * clamp((t - previous_end) / gap, 0, 1)) % 360
            return PassInfo(phase, False, angle, 0.0, next_start - t, 0.0, self._sunlit(angle), index)
        last_end = self.windows[-1][1] if self.windows else 0.0
        angle = (self.station_angle + self.half_arc + 360 * (t - last_end) / self.period) % 360
        phase = PassPhase.LOS if self.windows and t - last_end < config.LOS_PHASE_DURATION else PassPhase.PRE_PASS
        return PassInfo(phase, False, angle, 0.0, self.period, 0.0, self._sunlit(angle), len(self.windows))
    def _sunlit(self, angle: float) -> bool:
        return math.cos(math.radians(angle - config.SUN_DIRECTION_ANGLE)) > config.SUNLIT_COSINE_LIMIT
