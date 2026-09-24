"""Incident history shared by operator actions and automatic health responses."""
from __future__ import annotations
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING
from app.exceptions import DatabaseOperationError
from app.models.enums import IncidentSeverity, IncidentType
from app.utils.helpers import format_met, now_iso
if TYPE_CHECKING:
    from app.database.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

@dataclass
class Incident:
    """One operator or autonomous mission incident."""
    incident_id: int | None
    incident_type: IncidentType
    severity: IncidentSeverity
    description: str
    mission_time: float
    timestamp: str
    resolved: bool = False
    def to_dict(self) -> dict:
        """Return a plain record for event consumers."""
        return dict(incident_id=self.incident_id, incident_type=self.incident_type.value,
                    severity=self.severity.value, description=self.description,
                    mission_time=self.mission_time, timestamp=self.timestamp,
                    resolved=self.resolved, met=format_met(self.mission_time))

class IncidentManager:
    """Keeps incidents in memory even if SQLite becomes unavailable."""
    def __init__(self, db: DatabaseManager | None = None):
        self.db = db
        self._history: list[Incident] = []
        self.db_failed = False
    def record(self, mission_id: int, incident_type: IncidentType, severity: IncidentSeverity,
               description: str, mission_time: float, resolved: bool = False) -> Incident:
        """Record an incident and persist it when possible."""
        incident = Incident(None, incident_type, severity, description, mission_time, now_iso(), resolved)
        self._history.append(incident)
        if self.db:
            try:
                incident.incident_id = self.db.insert_incident(mission_id, incident)
                self.db_failed = False
            except DatabaseOperationError:
                self.db_failed = True
                logger.exception("Could not persist incident")
        return incident
    def resolve_open(self, mission_id: int, incident_type: IncidentType) -> list[Incident]:
        """Resolve all open incidents of one type."""
        resolved = []
        for incident in self._history:
            if incident.incident_type is incident_type and not incident.resolved:
                incident.resolved = True
                resolved.append(incident)
                if self.db and incident.incident_id is not None:
                    try:
                        self.db.resolve_incident(incident.incident_id)
                        self.db_failed = False
                    except DatabaseOperationError:
                        self.db_failed = True
                        logger.exception("Could not resolve incident in database")
        return resolved
    @property
    def history(self) -> list[Incident]:
        """Return a copy of mission incident history."""
        return list(self._history)
    def counts_by_type(self) -> dict[str, int]:
        """Count incidents by stable type value."""
        counts: dict[str, int] = {}
        for incident in self._history:
            key = incident.incident_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts
    def clear(self) -> None:
        """Clear history for a new mission."""
        self._history.clear()
        self.db_failed = False
