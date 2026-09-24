"""Satellite subsystems — the main ENCAPSULATION / DATA-HIDING example.

``PowerSystem.__battery`` and ``ThermalSystem.__temperature`` use double
underscores, so Python "name-mangles" them (they become
``_PowerSystem__battery``). Other code cannot casually write
``power.battery = 5``; it must go through methods such as ``consume_power()``,
``recharge()`` or ``drain()``, which always clamp the value to 0-100 %.
That is data hiding: the object protects its own state from invalid changes.

``Satellite`` uses COMPOSITION: a satellite *has a* power system and *has a*
thermal system (rather than *being* one through inheritance).
"""

from app import config
from app.utils.validation import clamp


class PowerSystem:
    """Tracks battery charge while hiding its mutable level."""

    def __init__(self, initial_level: float = config.BATTERY_INITIAL):
        self.__battery = clamp(initial_level, 0, 100)
        self._power_draw = config.BASE_POWER_DRAW

    def get_battery_level(self) -> float:
        """Read battery percentage."""
        return self.__battery

    @property
    def battery_level(self) -> float:
        """Read-only battery percentage."""
        return self.__battery

    @property
    def voltage(self) -> float:
        """Approximate Li-ion voltage from state of charge."""
        return (
            config.BATTERY_VOLTAGE_EMPTY
            + (config.BATTERY_VOLTAGE_FULL - config.BATTERY_VOLTAGE_EMPTY) * self.__battery / 100
        )

    @property
    def power_draw(self) -> float:
        """Current electrical load in watts."""
        return self._power_draw

    def set_load(self, watts: float) -> None:
        """Set the current load for telemetry."""
        self._power_draw = max(0.0, watts)

    def consume_power(self, watts: float, seconds: float) -> None:
        """Convert consumed joules into simulated charge loss."""
        self.__battery = clamp(
            self.__battery - max(0, watts) * max(0, seconds) * config.BATTERY_PCT_PER_JOULE, 0, 100
        )

    def recharge(self, watts: float, seconds: float) -> None:
        """Convert solar joules into simulated charge gain."""
        self.__battery = clamp(
            self.__battery + max(0, watts) * max(0, seconds) * config.BATTERY_PCT_PER_JOULE, 0, 100
        )

    def drain(self, percent: float) -> None:
        """Apply an operator battery-drain incident."""
        self.__battery = clamp(self.__battery - max(0, percent), 0, 100)

    def reset(self, level: float = config.BATTERY_INITIAL) -> None:
        """Restore charge and idle load."""
        self.__battery = clamp(level, 0, 100)
        self._power_draw = config.BASE_POWER_DRAW


class ThermalSystem:
    """First-order thermal response with an incident heat source."""

    def __init__(self, initial: float = config.TEMP_INITIAL):
        self.__temperature = initial
        self._external_heat = 0.0

    @property
    def temperature(self) -> float:
        """Read-only temperature in Celsius."""
        return self.__temperature

    @property
    def external_heat(self) -> float:
        """Current extra incident heat."""
        return self._external_heat

    def update(self, power_draw: float, sunlit: bool, dt: float, noise: float = 0.0) -> float:
        """Relax toward load, sunlight, and incident heat equilibrium."""
        target = (
            config.THERMAL_BASELINE
            + config.THERMAL_POWER_COEFF * power_draw
            + (config.THERMAL_SUN_OFFSET if sunlit else config.THERMAL_ECLIPSE_OFFSET)
            + self._external_heat
        )
        self.__temperature += (target - self.__temperature) * min(
            1, config.THERMAL_RESPONSE * max(0, dt)
        ) + noise
        self._external_heat *= config.EXTERNAL_HEAT_DECAY ** max(0, dt)
        return self.__temperature

    def inject_heat(self, degrees: float) -> None:
        """Add incident heat to the thermal target."""
        self._external_heat += degrees
        self.__temperature += degrees

    def reset(self) -> None:
        """Restore nominal temperature."""
        self.__temperature = config.TEMP_INITIAL
        self._external_heat = 0.0


class Satellite:
    """Groups the spacecraft's power and thermal systems."""

    def __init__(self, name: str = config.SATELLITE_NAME):
        self.name = name
        self.power = PowerSystem()
        self.thermal = ThermalSystem()

    def reset(self) -> None:
        """Restore both systems before a new mission."""
        self.power.reset()
        self.thermal.reset()
