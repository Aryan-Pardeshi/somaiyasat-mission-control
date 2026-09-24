"""One locked SQLite connection shared by mission worker threads."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import logging
import sqlite3
import threading
import pandas as pd
from app import config
from app.exceptions import DatabaseOperationError
from app.utils.helpers import mission_code, now_iso

logger = logging.getLogger(__name__)
TABLES = frozenset(("telemetry", "packets", "decisions", "incidents", "state_transitions"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS missions(mission_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_code TEXT,
 mission_name TEXT, mode TEXT, started_at TEXT, ended_at TEXT, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, timestamp TEXT,
 mission_time REAL, battery REAL, temperature REAL, signal REAL, power_draw REAL, packet_loss REAL,
 system_state TEXT, FOREIGN KEY(mission_id) REFERENCES missions(mission_id));
CREATE TABLE IF NOT EXISTS packets(packet_id INTEGER PRIMARY KEY, mission_id INTEGER, packet_type TEXT,
 priority TEXT, size_kb REAL, status TEXT, created_at TEXT, selected_at TEXT, transmitted_at TEXT,
 retry_count INTEGER, corrupted INTEGER, mode TEXT, score REAL,
 FOREIGN KEY(mission_id) REFERENCES missions(mission_id));
CREATE TABLE IF NOT EXISTS decisions(decision_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER,
 packet_id INTEGER, timestamp TEXT, mission_time REAL, selected_mode TEXT, total_score REAL,
 priority_score REAL, link_score REAL, urgency_score REAL, energy_score REAL, waiting_score REAL,
 battery REAL, temperature REAL, signal REAL, system_state TEXT, reason TEXT,
 FOREIGN KEY(mission_id) REFERENCES missions(mission_id));
CREATE TABLE IF NOT EXISTS incidents(incident_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER,
 timestamp TEXT, mission_time REAL, incident_type TEXT, severity TEXT, description TEXT,
 resolved INTEGER, FOREIGN KEY(mission_id) REFERENCES missions(mission_id));
CREATE TABLE IF NOT EXISTS state_transitions(id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER,
 timestamp TEXT, mission_time REAL, from_state TEXT, to_state TEXT, reason TEXT,
 FOREIGN KEY(mission_id) REFERENCES missions(mission_id));
CREATE INDEX IF NOT EXISTS idx_telemetry_mission ON telemetry(mission_id);
CREATE INDEX IF NOT EXISTS idx_packets_mission ON packets(mission_id);
CREATE INDEX IF NOT EXISTS idx_decisions_mission ON decisions(mission_id);
CREATE INDEX IF NOT EXISTS idx_incidents_mission ON incidents(mission_id);
CREATE INDEX IF NOT EXISTS idx_state_transitions_mission ON state_transitions(mission_id);
"""

class DatabaseManager:
    """Parameterised persistence API that wraps SQLite errors for callers."""
    def __init__(self, db_path: str | Path):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._lock = threading.Lock()
            with self._lock, self._conn:
                self._conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise DatabaseOperationError(str(exc)) from exc
    def _write(self, sql: str, params: tuple) -> int:
        try:
            with self._lock, self._conn:
                cursor = self._conn.execute(sql, params)
                return int(cursor.lastrowid or 0)
        except sqlite3.Error as exc:
            raise DatabaseOperationError(str(exc)) from exc
    def _read(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with self._lock:
                return [dict(row) for row in self._conn.execute(sql, params).fetchall()]
        except sqlite3.Error as exc:
            raise DatabaseOperationError(str(exc)) from exc
    def start_mission(self, mode: str, name: str = "", notes: str = "") -> tuple[int, str]:
        """Insert a mission and assign its daily human-readable code."""
        today = date.today()
        try:
            with self._lock, self._conn:
                count = self._conn.execute("SELECT COUNT(*) FROM missions WHERE mission_code LIKE ?", (f"{config.MISSION_CODE_PREFIX}-{today:%Y%m%d}-%",)).fetchone()[0]
                code = mission_code(today, count + 1)
                cur = self._conn.execute("INSERT INTO missions(mission_code,mission_name,mode,started_at,status,notes) VALUES(?,?,?,?,?,?)",
                                         (code, name, mode, now_iso(), "RUNNING", notes))
                return int(cur.lastrowid), code
        except sqlite3.Error as exc:
            raise DatabaseOperationError(str(exc)) from exc
    def end_mission(self, mission_id: int, status: str) -> None:
        """Mark a mission's final status and wall end time."""
        self._write("UPDATE missions SET ended_at=?,status=? WHERE mission_id=?", (now_iso(), status, mission_id))
    def insert_telemetry(self, mission_id, snapshot) -> None:
        """Persist the sensor values used by analytics."""
        self._write("INSERT INTO telemetry(mission_id,timestamp,mission_time,battery,temperature,signal,power_draw,packet_loss,system_state) VALUES(?,?,?,?,?,?,?,?,?)",
                    (mission_id, snapshot.timestamp, snapshot.mission_time, snapshot.battery, snapshot.temperature,
                     snapshot.signal, snapshot.power_draw, snapshot.packet_loss, snapshot.system_state))
    def upsert_packet(self, mission_id, packet) -> None:
        """Insert or refresh a packet's current lifecycle state."""
        self._write("""INSERT INTO packets(packet_id,mission_id,packet_type,priority,size_kb,status,created_at,
                    selected_at,transmitted_at,retry_count,corrupted,mode,score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(packet_id) DO UPDATE SET status=excluded.status, selected_at=excluded.selected_at,
                    transmitted_at=excluded.transmitted_at,retry_count=excluded.retry_count,
                    corrupted=excluded.corrupted,mode=excluded.mode,score=excluded.score""",
                    (packet.packet_id, mission_id, packet.packet_type.value, packet.priority.value, packet.size_kb,
                     packet.status.value, packet.created_iso, str(packet.selected_at) if packet.selected_at is not None else None,
                     str(packet.transmitted_at) if packet.transmitted_at is not None else None, packet.retry_count,
                     int(packet.corrupted), packet.mode_used, packet.score))
    def insert_decision(self, mission_id, decision) -> int:
        """Persist a scored routing selection."""
        return self._write("""INSERT INTO decisions(mission_id,packet_id,timestamp,mission_time,selected_mode,
            total_score,priority_score,link_score,urgency_score,energy_score,waiting_score,battery,temperature,
            signal,system_state,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mission_id, decision.packet_id, decision.timestamp, decision.mission_time, decision.selected_mode,
             decision.total_score, decision.priority_score, decision.link_score, decision.urgency_score,
             decision.energy_score, decision.waiting_score, decision.battery, decision.temperature,
             decision.signal, decision.system_state, decision.reason))
    def insert_incident(self, mission_id, incident) -> int:
        """Persist an incident and return its row ID."""
        return self._write("INSERT INTO incidents(mission_id,timestamp,mission_time,incident_type,severity,description,resolved) VALUES(?,?,?,?,?,?,?)",
                           (mission_id, incident.timestamp, incident.mission_time, incident.incident_type.value,
                            incident.severity.value, incident.description, int(incident.resolved)))
    def resolve_incident(self, incident_id: int) -> None:
        """Mark one incident resolved."""
        self._write("UPDATE incidents SET resolved=1 WHERE incident_id=?", (incident_id,))
    def insert_state_transition(self, mission_id, old, new, reason, mission_time) -> None:
        """Archive a health state change."""
        self._write("INSERT INTO state_transitions(mission_id,timestamp,mission_time,from_state,to_state,reason) VALUES(?,?,?,?,?,?)",
                    (mission_id, now_iso(), mission_time, old.value, new.value, reason))
    def next_packet_id(self) -> int:
        """Return a globally unique packet ID seed."""
        rows = self._read("SELECT COALESCE(MAX(packet_id)+1,100) AS next_id FROM packets")
        return int(rows[0]["next_id"])
    def get_missions(self, search: str = "", mode: str | None = None) -> list[dict]:
        """List missions with packet, decision, and incident aggregates."""
        rows = self._read("""SELECT m.*, (SELECT COUNT(*) FROM packets p WHERE p.mission_id=m.mission_id) packets,
            (SELECT COUNT(*) FROM packets p WHERE p.mission_id=m.mission_id AND p.status='SENT') sent,
            (SELECT COUNT(*) FROM decisions d WHERE d.mission_id=m.mission_id) attempts,
            (SELECT COUNT(*) FROM incidents i WHERE i.mission_id=m.mission_id) incidents,
            (SELECT COALESCE(MAX(t.mission_time),0) FROM telemetry t WHERE t.mission_id=m.mission_id) duration_s
            FROM missions m WHERE (m.mission_code LIKE ? OR m.mission_name LIKE ?) AND (? IS NULL OR m.mode=?)
            ORDER BY m.mission_id DESC""", (f"%{search}%", f"%{search}%", mode, mode))
        for row in rows:
            row["success_rate"] = row["sent"] / row["attempts"] * 100 if row["attempts"] else None
        return rows
    def get_mission(self, mission_id: int) -> dict | None:
        """Find one mission record."""
        rows = self._read("SELECT * FROM missions WHERE mission_id=?", (mission_id,))
        return rows[0] if rows else None
    def fetch_table(self, table: str, mission_id: int, limit: int | None = None) -> list[dict]:
        """Read a whitelisted child table for one mission."""
        if table not in TABLES:
            raise ValueError(f"Unknown table: {table}")
        sql = f"SELECT * FROM {table} WHERE mission_id=? ORDER BY 1"
        params: tuple = (mission_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (max(0, limit),)
        return self._read(sql, params)
    def read_dataframe(self, table: str, mission_id: int) -> pd.DataFrame:
        """Read a whitelisted child table as a pandas DataFrame."""
        if table not in TABLES:
            raise ValueError(f"Unknown table: {table}")
        try:
            with self._lock:
                return pd.read_sql_query(f"SELECT * FROM {table} WHERE mission_id=?", self._conn, params=(mission_id,))
        except (sqlite3.Error, pd.errors.DatabaseError) as exc:
            raise DatabaseOperationError(str(exc)) from exc
    def close(self) -> None:
        """Close the connection; repeated calls are harmless."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
