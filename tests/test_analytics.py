from matplotlib.figure import Figure
from app.analytics.analytics_engine import AnalyticsEngine
from app.database.database_manager import DatabaseManager
from app.models.telemetry import TelemetrySnapshot
from app.models.packet import create_packet
from app.core.router import AutonomousRouter, RouterContext
from app.models.communication_modes import build_modes
from app.models.enums import MissionState
from app.utils.helpers import now_iso

def test_empty_and_populated_plots_and_exports(tmp_path):
    db = DatabaseManager(":memory:")
    mid, _ = db.start_mission("LIVE")
    engine = AnalyticsEngine(db, tmp_path / "exports")
    plots = [engine.plot_timeline, engine.plot_packet_outcomes, engine.plot_mode_performance,
             engine.plot_correlation_heatmap, engine.plot_incident_distribution]
    for plot in plots:
        plot(Figure(), engine.load(mid))
    for t in (1, 2):
        db.insert_telemetry(mid, TelemetrySnapshot(t, 90 - t, 4, 27 + t, 80 + t, 1, 0, 0,
            "NOMINAL", "LINK READY", "ACTIVE PASS", True, True, now_iso()))
    packet = create_packet("ttc", 100, "critical", 3, 0)
    db.upsert_packet(mid, packet)
    decision = AutonomousRouter(build_modes()).evaluate([packet], RouterContext(90, 27, 80,
        MissionState.NOMINAL, True, 60, True, 1)).decision
    db.insert_decision(mid, decision)
    data = engine.load(mid)
    assert engine.summary(data)["packets_generated"] == 1
    assert engine.telemetry_stats(data)["battery"]["max"] == 89
    for plot in plots:
        plot(Figure(), data)
    assert engine.export_table(mid, "telemetry").exists()
    assert engine.save_summary(mid).exists()
    db.close()
