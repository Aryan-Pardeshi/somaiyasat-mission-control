"""Tracks one active progressive transmission and radio statistics."""

from __future__ import annotations
from dataclasses import dataclass
from app import config
from app.exceptions import CommunicationFailureError
from app.models.communication_modes import CommunicationMode, build_modes
from app.models.enums import CommunicationType, PacketStatus
from app.models.packet import DataPacket


@dataclass
class Transmission:
    """Mutable progress of one selected packet."""

    packet: DataPacket
    mode: CommunicationMode
    started_at: float
    sent_kb: float = 0.0
    estimated_time: float = 0.0

    @property
    def progress(self) -> float:
        """Completed fraction from 0 to 1."""
        return min(1.0, self.sent_kb / self.packet.size_kb)

    @property
    def total_kb(self) -> float:
        """Total packet size."""
        return self.packet.size_kb

    @property
    def done(self) -> bool:
        """Whether all KB have been transmitted."""
        return self.sent_kb >= self.total_kb - 1e-9


class CommunicationSystem:
    """Simulated radio with a single active route."""

    available_routes = [
        CommunicationType.TTC,
        CommunicationType.SSTV,
        CommunicationType.M17,
        CommunicationType.CODEC2,
    ]
    supported_modes = config.SUPPORTED_MODES

    def __init__(self):
        self.modes = build_modes()
        self.active: Transmission | None = None
        self.stats = {mode.value: {"sent": 0, "failed": 0, "kb_sent": 0.0} for mode in CommunicationType}
        self._link_down_until = -1.0

    def mode_for(self, packet: DataPacket) -> CommunicationMode:
        """Find the polymorphic mode for a packet."""
        return self.modes[packet.preferred_mode]

    def begin(self, packet: DataPacket, now: float, signal: float) -> Transmission:
        """Start sending a selected packet."""
        mode = self.mode_for(packet)
        packet.status = PacketStatus.TRANSMITTING
        packet.mode_used = mode.mode_type.value
        self.active = Transmission(
            packet, mode, now, estimated_time=mode.estimate_transmission_time(packet, signal)
        )
        return self.active

    def step(self, dt: float, signal: float, now: float) -> Transmission:
        """Advance progress or raise when the RF link drops."""
        tx = self.active
        if tx is None:
            raise RuntimeError("No active transmission")
        if self.link_down(now) or signal < tx.mode.minimum_signal_required() - config.LINK_DROP_MARGIN:
            raise CommunicationFailureError("RF link lost during transmission")
        amount = tx.mode.transmit(tx.packet, signal, dt)
        tx.sent_kb = min(tx.total_kb, tx.sent_kb + amount)
        return tx

    def complete(self) -> Transmission:
        """Mark an active transmission sent and update mode stats."""
        tx = self.active
        if tx is None:
            raise RuntimeError("No active transmission")
        tx.packet.status = PacketStatus.SENT
        stats = self.stats[tx.mode.mode_type.value]
        stats["sent"] += 1
        stats["kb_sent"] += tx.total_kb
        self.active = None
        return tx

    def fail(self, reason: str) -> Transmission:
        """Count a failed attempt and release the radio."""
        tx = self.active
        if tx is None:
            raise RuntimeError("No active transmission")
        self.stats[tx.mode.mode_type.value]["failed"] += 1
        self.active = None
        return tx

    def abort(self) -> Transmission | None:
        """Suspend an unsafe mode without counting an RF failure."""
        tx, self.active = self.active, None
        return tx

    def trigger_link_failure(self, now: float, duration: float) -> None:
        """Disable the radio until mission time reaches a deadline."""
        self._link_down_until = max(self._link_down_until, now + duration)

    def link_down(self, now: float) -> bool:
        """Return whether a simulated outage is active."""
        return now < self._link_down_until

    def reset(self) -> None:
        """Clear radio state for a new mission."""
        self.__init__()
