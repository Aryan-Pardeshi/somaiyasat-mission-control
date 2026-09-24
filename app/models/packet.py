"""Packets, inheritance, and CRC checks for simulated data."""
from __future__ import annotations
import math
import zlib
from app import config
from app.exceptions import InvalidPacketError, TelemetryCorruptionError
from app.models.enums import PacketType, PacketPriority, PacketStatus, CommunicationType
from app.utils.helpers import now_iso
from app.utils.validation import normalize_label

class DataPacket:
    """Mutable transmission request with an immutable checksum header."""
    packet_type: PacketType
    preferred_mode: CommunicationType

    def __init__(self, packet_id: int, priority: PacketPriority, size_kb: float, created_at: float, metadata: dict | None = None):
        try:
            valid_size = math.isfinite(float(size_kb)) and float(size_kb) > 0
        except (TypeError, ValueError):
            valid_size = False
        if not isinstance(priority, PacketPriority) or not isinstance(packet_id, int) or packet_id < 0 or not valid_size:
            raise InvalidPacketError("Packet ID, priority, or size is invalid")
        self.packet_id, self.priority, self.size_kb, self.created_at = packet_id, priority, float(size_kb), float(created_at)
        self.created_iso = now_iso()
        self.status = PacketStatus.QUEUED
        self.retry_count = 0
        self.corrupted = False
        self.metadata = dict(metadata or {})
        self.score = 0.0
        self.hold_reason = ""
        self.selected_at: float | None = None
        self.transmitted_at: float | None = None
        self.mode_used: str | None = None
        self._payload = f"{packet_id}|{self.packet_type.value}|{priority.value}|{size_kb}|{created_at}".encode()
        self._checksum = zlib.crc32(self._payload)

    @property
    def urgency(self) -> float:
        """Intrinsic value of this packet type."""
        return config.URGENCY_SCORES[self.packet_type.value]

    @property
    def max_retries(self) -> int:
        """Critical telemetry has a larger retry budget."""
        return config.MAX_RETRIES_CRITICAL if self.priority is PacketPriority.CRITICAL else config.MAX_RETRIES

    @property
    def label(self) -> str:
        """Human readable packet identity."""
        return f"{self.packet_type.label} #{self.packet_id}"

    def age(self, now: float) -> float:
        """Return nonnegative mission age in seconds."""
        return max(0.0, now - self.created_at)

    def verify_integrity(self) -> None:
        """Detect an injected bit error before routing or transmitting."""
        if zlib.crc32(self._payload) != self._checksum:
            self.corrupted = True
            raise TelemetryCorruptionError(f"CRC mismatch for packet #{self.packet_id}")

    def corrupt(self) -> None:
        """Flip one header bit while preserving its original CRC."""
        raw = bytearray(self._payload)
        raw[0] ^= 1
        self._payload = bytes(raw)
        self.corrupted = True

    def describe(self) -> str:
        """Describe this type of packet."""
        return f"{self.packet_type.label} data packet"

    def to_record(self, now: float | None = None) -> dict:
        """Return the event and UI packet record."""
        return dict(packet_id=self.packet_id, packet_type=self.packet_type.value, type_label=self.packet_type.label,
                    priority=self.priority.value, size_kb=self.size_kb, status=self.status.value,
                    retry_count=self.retry_count, corrupted=bool(self.corrupted), score=self.score,
                    hold_reason=self.hold_reason, age=self.age(now) if now is not None else 0.0,
                    required_signal=config.MODE_MIN_SIGNAL[self.preferred_mode.value], mode=self.mode_used or self.preferred_mode.value,
                    created_at=self.created_iso)

class TTCPacket(DataPacket):
    """Command and control packet."""
    packet_type, preferred_mode = PacketType.TTC, CommunicationType.TTC
    def describe(self) -> str:
        return "Critical telemetry, tracking and command data"

class HousekeepingPacket(DataPacket):
    """Health and housekeeping packet."""
    packet_type, preferred_mode = PacketType.HOUSEKEEPING, CommunicationType.TTC
    def describe(self) -> str:
        return "Satellite housekeeping telemetry"

class SSTVPacket(DataPacket):
    """Image packet carried by simulated SSTV scan lines."""
    packet_type, preferred_mode = PacketType.SSTV, CommunicationType.SSTV
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_lines = config.SSTV_IMAGE_LINES
    def describe(self) -> str:
        return "Slow scan image downlink"

class VoicePacket(DataPacket):
    """Common base for digital voice codecs."""
    vocoder = ""
    def describe(self) -> str:
        return f"{self.vocoder} digital voice frame"

class M17Packet(VoicePacket):
    """M17 digital radio packet."""
    packet_type, preferred_mode, vocoder = PacketType.M17, CommunicationType.M17, "M17"

class Codec2Packet(VoicePacket):
    """Low bitrate Codec2 voice packet."""
    packet_type, preferred_mode, vocoder = PacketType.CODEC2, CommunicationType.CODEC2, "Codec2"

PACKET_CLASSES: dict[PacketType, type[DataPacket]] = {
    PacketType.TTC: TTCPacket, PacketType.HOUSEKEEPING: HousekeepingPacket,
    PacketType.SSTV: SSTVPacket, PacketType.M17: M17Packet, PacketType.CODEC2: Codec2Packet,
}

def create_packet(packet_type: PacketType | str, packet_id: int, priority: PacketPriority | str,
                  size_kb: float, created_at: float, metadata=None) -> DataPacket:
    """Normalise labels and construct the appropriate packet subclass."""
    try:
        kind = packet_type if isinstance(packet_type, PacketType) else PacketType(normalize_label(packet_type))
        level = priority if isinstance(priority, PacketPriority) else PacketPriority(normalize_label(priority))
        return PACKET_CLASSES[kind](packet_id, level, size_kb, created_at, metadata)
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidPacketError(f"Invalid packet type or priority: {packet_type}, {priority}") from exc
