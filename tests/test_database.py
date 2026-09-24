from datetime import date
import pytest
from app.database.database_manager import DatabaseManager
from app.models.packet import create_packet
from app.models.telemetry import TelemetrySnapshot
from app.models.enums import IncidentType, IncidentSeverity
from app.core.incident_manager import Incident
from app.core.router import AutonomousRouter, RouterContext
from app.models.communication_modes import build_modes
from app.models.enums import MissionState
from app.utils.helpers import mission_code, now_iso

@pytest.mark.parametrize("location", [":memory:", "file"])
def test_schema_and_records(tmp_path, location):
    db = DatabaseManager(":memory:" if location == ":memory:" else tmp_path / "mission.db")
    mid, code = db.start_mission("LIVE", "Test")
    assert code == mission_code(date.today(), 1)
    snap = TelemetrySnapshot(1, 90, 4, 27, 80, 1, 0, 0, "NOMINAL", "LINK READY", "AOS", True, True, now_iso())
    db.insert_telemetry(mid, snap)
    packet = create_packet("ttc", 100, "critical", 3, 0)
    db.upsert_packet(mid, packet)
    packet.retry_count = 1
    db.upsert_packet(mid, packet)
    assert db.fetch_table("packets", mid)[0]["retry_count"] == 1
    router = AutonomousRouter(build_modes())
    decision = router.evaluate([packet], RouterContext(90, 27, 80, MissionState.NOMINAL,
        True, 60, True, 1)).decision
    db.insert_decision(mid, decision)
    db.insert_state_transition(mid, MissionState.NOMINAL, MissionState.LOW_POWER, "Battery low", 1)
    assert len(db.fetch_table("decisions", mid)) == 1
    assert len(db.fetch_table("state_transitions", mid)) == 1
    incident = Incident(None, IncidentType.COMM_FAILURE, IncidentSeverity.CRITICAL, "RF down", 1, now_iso())
    iid = db.insert_incident(mid, incident)
    db.resolve_incident(iid)
    assert db.fetch_table("incidents", mid)[0]["resolved"] == 1
    db.end_mission(mid, "COMPLETED")
    assert db.get_missions()[0]["mission_code"] == code
    assert len(db.fetch_table("telemetry", mid)) == 1
    with pytest.raises(ValueError): db.fetch_table("missions; DROP TABLE missions", mid)
    db.close()
