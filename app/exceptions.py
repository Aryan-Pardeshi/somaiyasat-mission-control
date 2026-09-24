"""Domain errors that callers can handle without hiding programming mistakes."""


class SomaiyaSatError(Exception):
    """Base error for mission operations."""


class TelemetryCorruptionError(SomaiyaSatError):
    """A sensor frame or packet checksum is invalid."""


class CommunicationFailureError(SomaiyaSatError):
    """The radio link failed during transfer."""


class InvalidPacketError(SomaiyaSatError):
    """Packet fields are invalid."""


class DatabaseOperationError(SomaiyaSatError):
    """A SQLite operation failed."""


class ReplayDataError(SomaiyaSatError):
    """A replay CSV cannot provide valid mission rows."""
