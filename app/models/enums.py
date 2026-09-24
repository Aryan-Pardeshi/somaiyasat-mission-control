"""Stable string values used by events and SQLite."""
from enum import Enum

class PacketType(str, Enum):
    TTC = "TTC"
    HOUSEKEEPING = "HOUSEKEEPING"
    SSTV = "SSTV"
    M17 = "M17"
    CODEC2 = "CODEC2"
    @property
    def label(self) -> str:
        return {self.TTC: "TT&C", self.HOUSEKEEPING: "Housekeeping", self.SSTV: "SSTV", self.M17: "M17", self.CODEC2: "Codec2"}[self]

class PacketPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class PacketStatus(str, Enum):
    QUEUED = "QUEUED"
    SELECTED = "SELECTED"
    TRANSMITTING = "TRANSMITTING"
    SENT = "SENT"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    DROPPED = "DROPPED"

class CommunicationType(str, Enum):
    TTC = "TTC"
    SSTV = "SSTV"
    M17 = "M17"
    CODEC2 = "CODEC2"
    @property
    def label(self) -> str:
        return "TT&C" if self is self.TTC else "Codec2" if self is self.CODEC2 else self.value

class MissionState(str, Enum):
    NOMINAL = "NOMINAL"
    LOW_POWER = "LOW_POWER"
    DEGRADED_LINK = "DEGRADED_LINK"
    THERMAL_ALERT = "THERMAL_ALERT"
    SAFE_MODE = "SAFE_MODE"
    COMMUNICATION_LOSS = "COMMUNICATION_LOSS"
    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title().replace("Communication Loss", "Comm Loss")
    @property
    def severity(self) -> str:
        return "nominal" if self is self.NOMINAL else "critical" if self in (self.SAFE_MODE, self.COMMUNICATION_LOSS) else "warning"

class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class IncidentType(str, Enum):
    BATTERY_DRAIN = "BATTERY_DRAIN"
    THERMAL_SPIKE = "THERMAL_SPIKE"
    SIGNAL_LOSS = "SIGNAL_LOSS"
    COMM_FAILURE = "COMM_FAILURE"
    CORRUPTED_PACKET = "CORRUPTED_PACKET"
    PACKET_BURST = "PACKET_BURST"
    FORCE_SAFE_MODE = "FORCE_SAFE_MODE"
    RESTORE_NOMINAL = "RESTORE_NOMINAL"
    LOW_POWER = "LOW_POWER"
    THERMAL_ALERT = "THERMAL_ALERT"
    SAFE_MODE = "SAFE_MODE"
    TELEMETRY_CORRUPTION = "TELEMETRY_CORRUPTION"
    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

class PassPhase(str, Enum):
    PRE_PASS = "PRE-PASS"
    AOS = "AOS"
    ACTIVE = "ACTIVE PASS"
    LOS = "LOS"

class MissionMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"
