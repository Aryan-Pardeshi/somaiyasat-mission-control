"""Thread-safe event handoff to the Tk main thread."""
from dataclasses import dataclass, field
from enum import Enum
import logging
import queue
import time

logger = logging.getLogger(__name__)

class EventType(str, Enum):
    TELEMETRY_UPDATE = "TELEMETRY_UPDATE"
    QUEUE_UPDATE = "QUEUE_UPDATE"
    PACKET_ADDED = "PACKET_ADDED"
    PACKET_SELECTED = "PACKET_SELECTED"
    TRANSMISSION_STARTED = "TRANSMISSION_STARTED"
    TRANSMISSION_PROGRESS = "TRANSMISSION_PROGRESS"
    TRANSMISSION_COMPLETE = "TRANSMISSION_COMPLETE"
    TRANSMISSION_FAILED = "TRANSMISSION_FAILED"
    STATE_CHANGED = "STATE_CHANGED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"
    GROUND_PASS_CHANGED = "GROUND_PASS_CHANGED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_ENDED = "MISSION_ENDED"
    REPLAY_PROGRESS = "REPLAY_PROGRESS"
    LOG = "LOG"

@dataclass
class Event:
    """One immutable-by-convention plain-data notification."""
    type: EventType
    data: dict
    created: float = field(default_factory=time.time)

class EventBus:
    """Bounded queue keeps worker threads separate from Tk widgets."""
    def __init__(self, maxsize: int = 10000):
        self._queue: queue.Queue[Event] = queue.Queue(maxsize)
        self._warned = False
    def publish(self, event_type: EventType, **data) -> None:
        """Enqueue an event without ever blocking a worker."""
        try:
            self._queue.put_nowait(Event(event_type, data))
        except queue.Full:
            if not self._warned:
                logger.warning("Event bus full; dropping events")
                self._warned = True
    def drain(self, max_events: int) -> list[Event]:
        """Pull at most max_events for a UI poll cycle."""
        events = []
        for _ in range(max(0, max_events)):
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if self._queue.qsize() < self._queue.maxsize:
            self._warned = False
        return events
    def clear(self) -> None:
        """Discard pending events before a fresh mission."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
