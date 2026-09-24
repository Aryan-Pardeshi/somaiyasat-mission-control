import threading
import time
from app.core.event_bus import EventBus, EventType
from app.core.mission_controller import MissionController
from app.database.database_manager import DatabaseManager

def test_live_threads_and_replay_completion(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    bus = EventBus()
    controller = MissionController(db, bus, rng_seed=4)
    controller.start_live_mission()
    controller.skip_to_next_pass()
    time.sleep(6)
    mid = controller.mission_id
    controller.stop_mission()
    events = bus.drain(10000)
    assert any(e.type is EventType.MISSION_STARTED for e in events)
    assert any(e.type is EventType.MISSION_ENDED for e in events)
    assert len(db.fetch_table("telemetry", mid)) > 0
    assert len(db.fetch_table("decisions", mid)) > 0
    assert not any(t.is_alive() and t.name.endswith("Worker") for t in threading.enumerate())
    path = tmp_path / "replay.csv"
    header = "timestamp,battery,temp,signal,power_draw,packet_loss,packet_type,priority,size_kb,event\n"
    rows = [f"{i},90,27,80,1,0,{ 'TTC' if i in (0, 2, 4) else ''},{'HIGH' if i in (0, 2, 4) else ''},{'3' if i in (0, 2, 4) else ''},\n" for i in range(20)]
    path.write_text(header + "".join(rows))
    controller.replay.load_csv(path)
    controller.set_replay_speed(5.0)
    controller.start_replay_mission()
    deadline = time.monotonic() + 7
    while controller.mission_active and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not controller.mission_active
    assert db.get_mission(controller.mission_id)["status"] == "COMPLETED"
    assert not any(t.is_alive() and t.name.endswith("Worker") for t in threading.enumerate())
    db.close()
