"""Integration tests: real worker threads, real SQLite, real event bus."""
import threading
import time

from app.core.event_bus import EventBus, EventType
from app.core.mission_controller import MissionController
from app.database.database_manager import DatabaseManager
from app.models.enums import IncidentType, MissionState


def worker_threads_alive() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.endswith("Worker") and t.is_alive()]


def run_for(seconds: float, bus: EventBus, events: list) -> None:
    """Drain the event bus like the GUI would, for a few seconds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        events.extend(bus.drain(1000))
        time.sleep(0.05)


def test_live_mission_runs_threads_logs_to_database_and_shuts_down(tmp_path):
    db = DatabaseManager(tmp_path / "live.db")
    bus = EventBus()
    controller = MissionController(db, bus, rng_seed=4)
    events: list = []

    controller.start_live_mission()
    assert set(worker_threads_alive()) == {"TelemetryWorker", "HealthMonitorWorker",
                                           "RouterWorker", "TransmissionWorker"}
    controller.skip_to_next_pass()           # jump to AOS so the router can transmit
    run_for(6, bus, events)
    mission_id = controller.mission_id
    controller.stop_mission()
    events.extend(bus.drain(10000))

    kinds = {event.type for event in events}
    assert {EventType.MISSION_STARTED, EventType.TELEMETRY_UPDATE, EventType.PACKET_SELECTED,
            EventType.MISSION_ENDED} <= kinds
    assert len(db.fetch_table("telemetry", mission_id)) >= 4
    assert len(db.fetch_table("decisions", mission_id)) >= 1
    assert worker_threads_alive() == []      # graceful shutdown: no dangling threads
    db.close()


def test_thermal_spike_changes_state_and_is_logged(tmp_path):
    db = DatabaseManager(tmp_path / "thermal.db")
    bus = EventBus()
    controller = MissionController(db, bus, rng_seed=7)
    events: list = []
    controller.start_live_mission()
    controller.inject_incident(IncidentType.THERMAL_SPIKE)
    run_for(6, bus, events)
    assert controller.state is MissionState.THERMAL_ALERT
    mission_id = controller.mission_id
    controller.stop_mission()
    incident_types = {row["incident_type"] for row in db.fetch_table("incidents", mission_id)}
    assert {"THERMAL_SPIKE", "THERMAL_ALERT"} <= incident_types
    db.close()


def test_csv_replay_runs_to_completion(tmp_path):
    db = DatabaseManager(tmp_path / "replay.db")
    controller = MissionController(db, EventBus(), rng_seed=1)
    path = tmp_path / "replay.csv"
    header = "timestamp,battery,temp,signal,power_draw,packet_loss,packet_type,priority,size_kb,event\n"
    rows = [f"{i},90,27,80,1,0,{'TTC,HIGH,3' if i % 2 == 0 else ',,'},\n" for i in range(20)]
    path.write_text(header + "".join(rows))

    controller.replay.load_csv(path)
    controller.set_replay_speed(5.0)
    controller.start_replay_mission()
    deadline = time.monotonic() + 10
    while controller.mission_active and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not controller.mission_active
    assert db.get_mission(controller.mission_id)["status"] == "COMPLETED"
    assert worker_threads_alive() == []
    db.close()
