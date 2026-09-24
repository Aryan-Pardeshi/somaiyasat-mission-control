"""Tk-independent, bounded view of mission events for all UI pages."""
from __future__ import annotations

from collections import deque

from app import config

METRICS = ("mission_time", "battery", "temperature", "signal", "power_draw",
           "packet_loss", "voltage")


class UIState:
    """Apply plain event payloads; widgets can read one consistent snapshot."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Discard all information from the previous mission."""
        self.snapshot: dict | None = None
        self.pass_info: dict | None = None
        self.met = "00:00:00"
        self.counters: dict = {}
        self.history = {key: deque(maxlen=config.TELEMETRY_HISTORY_LENGTH) for key in METRICS}
        self.minmax: dict[str, dict[str, float]] = {}
        self.queue: list[dict] = []
        self.hold_reason = ""
        self.active_rules: list[str] = []
        self.transmitting_id: int | None = None
        self.last_decision: dict | None = None
        self.decisions: deque[dict] = deque(maxlen=50)
        self.transmission: dict | None = None
        self.comm_stats: dict[str, dict[str, int]] = {}
        self.incidents: list[dict] = []
        self.feed: deque[tuple[str, str, str]] = deque(maxlen=config.EVENT_FEED_MAX_LINES)
        self.state = "NOMINAL"
        self.mission: dict = {}
        self.mission_active = False
        self.replay_progress: dict | None = None

    def apply(self, event) -> None:
        """Update one slice of state from the documented event bus contract."""
        kind = getattr(event.type, "value", event.type)
        data = event.data
        if kind == "MISSION_STARTED":
            self.reset()
            self.mission = dict(data)
            self.mission_active = True
        elif kind == "MISSION_ENDED":
            self.mission_active = False
            self.mission.update(data)
        elif kind == "TELEMETRY_UPDATE":
            self.snapshot = dict(data.get("snapshot") or {})
            self.pass_info = dict(data.get("pass") or {})
            self.met = data.get("met", self.met)
            self.counters = dict(data.get("counters") or {})
            self.state = self.snapshot.get("system_state", self.state)
            for key in METRICS:
                value = self.snapshot.get(key)
                if isinstance(value, (int, float)):
                    self.history[key].append(value)
                    bounds = self.minmax.setdefault(key, {"min": value, "max": value})
                    bounds["min"] = min(bounds["min"], value)
                    bounds["max"] = max(bounds["max"], value)
        elif kind == "GROUND_PASS_CHANGED":
            self.pass_info = dict(data.get("pass") or {})
        elif kind == "QUEUE_UPDATE":
            self.queue = list(data.get("packets") or [])
            self.hold_reason = data.get("hold_reason", "")
            self.active_rules = list(data.get("active_rules") or [])
            self.transmitting_id = data.get("transmitting_id")
        elif kind == "PACKET_ADDED":
            packet = data.get("packet")
            if packet and all(x.get("packet_id") != packet.get("packet_id") for x in self.queue):
                self.queue.append(dict(packet))
        elif kind == "PACKET_SELECTED":
            self.last_decision = dict(data.get("decision") or {})
            self.decisions.appendleft(self.last_decision)
        elif kind == "TRANSMISSION_STARTED":
            packet = data.get("packet") or {}
            self.transmitting_id = packet.get("packet_id")
            self.transmission = dict(data)
        elif kind == "TRANSMISSION_PROGRESS":
            self.transmission = dict(data)
        elif kind in ("TRANSMISSION_COMPLETE", "TRANSMISSION_FAILED"):
            mode = str(data.get("mode", ""))
            stats = self.comm_stats.setdefault(mode, {"sent": 0, "failed": 0})
            stats["sent" if kind == "TRANSMISSION_COMPLETE" else "failed"] += 1
            self.transmission = None
            self.transmitting_id = None
            packet = data.get("packet") or {}
            packet_id = packet.get("packet_id")
            if kind == "TRANSMISSION_COMPLETE":
                self.queue = [p for p in self.queue if p.get("packet_id") != packet_id]
            else:
                for index, old in enumerate(self.queue):
                    if old.get("packet_id") == packet_id:
                        self.queue[index] = dict(packet)
                        break
        elif kind == "STATE_CHANGED":
            self.state = str(data.get("new", self.state))
        elif kind == "INCIDENT_CREATED":
            self.incidents.insert(0, dict(data.get("incident") or {}))
        elif kind == "INCIDENT_RESOLVED":
            for incident in self.incidents:
                if incident.get("incident_id") == data.get("incident_id"):
                    incident["resolved"] = True
                    break
        elif kind == "REPLAY_PROGRESS":
            self.replay_progress = dict(data)
        elif kind == "LOG":
            self.feed.appendleft((str(data.get("met", self.met)),
                                  str(data.get("severity", "INFO")),
                                  str(data.get("message", ""))))
