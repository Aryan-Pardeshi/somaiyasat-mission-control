"""Tests for DatabaseManager (SQLite persistence)."""
import sqlite3
from datetime import date

import pytest

from app.core.incident_manager import Incident
from app.models.enums import IncidentSeverity, IncidentType, MissionState
from app.models.packet import create_packet
from app.utils.helpers import mission_code, now_iso


def test_database_file_is_created_with_all_tables(tmp_path):
    from app.database.database_manager import DatabaseManager

    path = tmp_path / "nested" / "mission.db"
    DatabaseManager(path).close()
    assert path.exists()
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"missions", "telemetry", "packets", "decisions", "incidents", "state_transitions"} <= tables


def test_start_and_end_mission(db):
    mission_id, code = db.start_mission("LIVE", "Test mission")
    assert code == mission_code(date.today(), 1)
    assert code.startswith("SMC-")
    db.end_mission(mission_id, "COMPLETED")
    mission = db.get_mission(mission_id)
    assert mission["status"] == "COMPLETED"
    assert mission["ended_at"]


def test_insert_telemetry(db, make_snapshot):
    mission_id, _ = db.start_mission("LIVE")
    db.insert_telemetry(mission_id, make_snapshot(battery=77.123456))
    rows = db.fetch_table("telemetry", mission_id)
    assert len(rows) == 1
    assert rows[0]["battery"] == 77.12          # stored rounded


def test_packet_upsert_updates_existing_row(db):
    mission_id, _ = db.start_mission("LIVE")
    packet = create_packet("TTC", 100, "CRITICAL", 3, created_at=0)
    db.upsert_packet(mission_id, packet)
    packet.retry_count = 2
    db.upsert_packet(mission_id, packet)
    rows = db.fetch_table("packets", mission_id)
    assert len(rows) == 1 and rows[0]["retry_count"] == 2


def test_insert_decision(db, router, make_context):
    mission_id, _ = db.start_mission("LIVE")
    packet = create_packet("TTC", 100, "CRITICAL", 3, created_at=0)
    decision = router.evaluate([packet], make_context()).decision
    db.insert_decision(mission_id, decision)
    row = db.fetch_table("decisions", mission_id)[0]
    assert row["packet_id"] == 100
    assert row["reason"].startswith("Packet #100")
    assert row["total_score"] == pytest.approx(decision.total_score, abs=0.01)


def test_insert_and_resolve_incident(db):
    mission_id, _ = db.start_mission("LIVE")
    incident = Incident(None, IncidentType.COMM_FAILURE, IncidentSeverity.CRITICAL, "RF down", 1.0, now_iso())
    incident_id = db.insert_incident(mission_id, incident)
    assert db.fetch_table("incidents", mission_id)[0]["resolved"] == 0
    db.resolve_incident(incident_id)
    assert db.fetch_table("incidents", mission_id)[0]["resolved"] == 1


def test_state_transition_is_logged(db):
    mission_id, _ = db.start_mission("LIVE")
    db.insert_state_transition(mission_id, MissionState.NOMINAL, MissionState.LOW_POWER, "Battery low", 5.0)
    row = db.fetch_table("state_transitions", mission_id)[0]
    assert (row["from_state"], row["to_state"]) == ("NOMINAL", "LOW_POWER")


def test_mission_list_aggregates(db, router, make_context):
    mission_id, _ = db.start_mission("REPLAY", "stressful_mission.csv")
    packet = create_packet("TTC", 100, "CRITICAL", 3, created_at=0)
    db.insert_decision(mission_id, router.evaluate([packet], make_context()).decision)
    packet.status = packet.status.SENT
    db.upsert_packet(mission_id, packet)
    mission = db.get_missions(mode="REPLAY")[0]
    assert mission["packets"] == 1 and mission["attempts"] == 1
    assert mission["success_rate"] == 100.0


def test_unknown_table_is_rejected(db):
    # Table names cannot be SQL parameters, so they are checked against a whitelist.
    with pytest.raises(ValueError):
        db.fetch_table("missions; DROP TABLE missions", 1)
