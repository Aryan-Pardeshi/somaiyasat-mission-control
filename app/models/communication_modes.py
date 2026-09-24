"""Communication modes — the main INHERITANCE + POLYMORPHISM example.

Class hierarchy::

    CommunicationMode (ABC)          <- abstract: cannot be instantiated
    ├── DigitalLinkMode (abstract)   <- speed depends on signal via efficiency()
    │   ├── TTCMode                  <- robust, forward-error-corrected control link
    │   ├── M17Mode                  <- digital voice: steep "cliff" when signal is weak
    │   └── Codec2Mode               <- low-bitrate voice: degrades gently
    └── SSTVMode                     <- analog image: fixed speed, weak signal = noise

The router and the CommunicationSystem only ever call the common interface
(``transmit``, ``estimate_transmission_time``, ``calculate_energy_cost``,
``minimum_signal_required``). Which *version* of the method runs depends on the
object's class — that is polymorphism. Adding a new radio mode means adding a
subclass; no ``if mode == ...`` chains are needed anywhere else.

All numbers are simulation values from config.py, not real protocol specs.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import math
from app import config
from app.models.enums import CommunicationType
from app.models.packet import DataPacket
from app.utils.validation import clamp


class CommunicationMode(ABC):
    """Template for a simulated radio link."""

    mode_type: CommunicationType
    display_name: str
    description: str

    def __init__(self):
        key = self.mode_type.value
        self._power_w = config.MODE_POWER_COSTS[key]
        self._data_rate_kbps = config.MODE_DATA_RATE_KBPS[key]
        self._min_signal = config.MODE_MIN_SIGNAL[key]

    @property
    def power_draw(self) -> float:
        """Additional transmitter load in watts."""
        return self._power_w

    @property
    def data_rate(self) -> float:
        """Nominal throughput in KB/s."""
        return self._data_rate_kbps

    @abstractmethod
    def minimum_signal_required(self) -> float:
        """Return the minimum usable signal."""

    @abstractmethod
    def estimate_transmission_time(self, packet: DataPacket, signal: float) -> float:
        """Estimate seconds to send a packet."""

    @abstractmethod
    def transmit(self, packet: DataPacket, signal: float, dt: float) -> float:
        """Return KB sent during a time slice."""

    def calculate_energy_cost(self, packet: DataPacket, signal: float) -> float:
        """Energy (J) = transmitter power (W) x transmission time (s).

        This is a *template method*: it is written once here but calls the
        subclass's own ``estimate_transmission_time``.
        """
        return self.power_draw * self.estimate_transmission_time(packet, signal)

    def can_transmit(self, signal: float) -> bool:
        """Check the mode's minimum signal requirement."""
        return signal >= self.minimum_signal_required()


class DigitalLinkMode(CommunicationMode):
    """Digital links: throughput = data rate x efficiency(signal).

    Subclasses only supply their own ``efficiency`` curve (another abstract
    method), so the shared maths is written once here.
    """

    def minimum_signal_required(self) -> float:
        return self._min_signal

    @abstractmethod
    def efficiency(self, signal: float) -> float:
        """Return a throughput multiplier."""

    def estimate_transmission_time(self, packet: DataPacket, signal: float) -> float:
        return packet.size_kb / (self.data_rate * self.efficiency(signal))

    def transmit(self, packet: DataPacket, signal: float, dt: float) -> float:
        # A corrupted packet must never be sent: the CRC check raises
        # TelemetryCorruptionError, which the controller catches and quarantines.
        packet.verify_integrity()
        return self.data_rate * self.efficiency(signal) * max(0.0, dt)


class TTCMode(DigitalLinkMode):
    """Robust forward-error-corrected control link."""

    mode_type, display_name, description = CommunicationType.TTC, "TT&C", "Robust control telemetry"

    def efficiency(self, signal: float) -> float:
        return 0.7 + 0.3 * clamp(signal, 0, 100) / 100


class SSTVMode(CommunicationMode):
    """Analog scan-line image link: weak signal adds noise, not delay."""

    mode_type, display_name, description = CommunicationType.SSTV, "SSTV", "Slow scan image downlink"

    def __init__(self):
        super().__init__()
        self._line_remainders: dict[int, float] = {}
        self._last_noise_level = 0.0

    @property
    def last_noise_level(self) -> float:
        """Latest visual noise estimate from 0 to 1."""
        return self._last_noise_level

    def minimum_signal_required(self) -> float:
        return self._min_signal

    def estimate_transmission_time(self, packet: DataPacket, signal: float) -> float:
        return packet.size_kb / self.data_rate

    def transmit(self, packet: DataPacket, signal: float, dt: float) -> float:
        """Send whole scan lines only (real SSTV draws the picture line by line).

        Unlike the digital modes, a weak signal does not slow SSTV down; it only
        makes the picture noisier. The UI uses ``last_noise_level`` for that.
        """
        packet.verify_integrity()
        self._last_noise_level = clamp((75 - signal) / 75, 0, 1)
        line_kb = packet.size_kb / config.SSTV_IMAGE_LINES
        available = self._line_remainders.get(packet.packet_id, 0.0) + self.data_rate * max(0, dt)
        lines = int(available / line_kb)
        sent = lines * line_kb
        self._line_remainders[packet.packet_id] = available - sent
        return sent

    def calculate_energy_cost(self, packet: DataPacket, signal: float) -> float:
        # Method overriding + super(): reuse the parent's formula, then add the
        # extra energy needed to encode the image.
        return super().calculate_energy_cost(packet, signal) + config.SSTV_ENCODER_OVERHEAD_J


class M17Mode(DigitalLinkMode):
    """Digital 4FSK link with a steep quality curve."""

    mode_type, display_name, description = CommunicationType.M17, "M17", "Digital radio voice"

    def efficiency(self, signal: float) -> float:
        # Logistic (S-shaped) curve: near its minimum signal M17 barely works,
        # ~10 points above it throughput jumps up. Digital modes behave this way.
        return 0.25 + 0.75 / (1 + math.exp(-((signal - self._min_signal - 10) / 6)))


class Codec2Mode(DigitalLinkMode):
    """Robust low-bitrate digital voice link."""

    mode_type, display_name, description = CommunicationType.CODEC2, "Codec2", "Low bitrate speech"

    def efficiency(self, signal: float) -> float:
        return 0.6 + 0.4 * clamp(signal, 0, 100) / 100


MODE_CLASSES: dict[CommunicationType, type[CommunicationMode]] = {
    CommunicationType.TTC: TTCMode,
    CommunicationType.SSTV: SSTVMode,
    CommunicationType.M17: M17Mode,
    CommunicationType.CODEC2: Codec2Mode,
}


def build_modes() -> dict[CommunicationType, CommunicationMode]:
    """Build one stateful mode object per radio type."""
    return {kind: cls() for kind, cls in MODE_CLASSES.items()}
