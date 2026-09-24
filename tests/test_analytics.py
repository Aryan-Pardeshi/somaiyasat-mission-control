"""Tests for the analytics engine (Pandas, NumPy, Matplotlib, Seaborn)."""
from matplotlib.figure import Figure

from app.analytics.analytics_engine import AnalyticsEngine
from app.models.packet import create_packet


def populated_mission(db, router, make_context, make_snapshot):
    mission_id, _ = db.start_mission("LIVE")
    for t in range(1, 6):
        db.insert_telemetry(mission_id, make_snapshot(mission_time=t, battery=90 - t, temperature=30 + t))
    packet = create_packet("TTC", 100, "CRITICAL", 3, created_at=0)
    db.insert_decision(mission_id, router.evaluate([packet], make_context()).decision)
    packet.status = packet.status.SENT
    db.upsert_packet(mission_id, packet)
    return mission_id


def test_summary_and_numpy_statistics(db, router, make_context, make_snapshot, tmp_path):
    engine = AnalyticsEngine(db, tmp_path)
    data = engine.load(populated_mission(db, router, make_context, make_snapshot))
    summary = engine.summary(data)
    assert summary["packets_generated"] == 1
    assert summary["packets_transmitted"] == 1
    assert summary["success_rate"] == 100.0
    assert summary["min_battery"] == 85
    stats = engine.telemetry_stats(data)
    assert stats["battery"]["max"] == 89 and stats["temperature"]["mean"] == 33


def test_every_chart_draws_with_and_without_data(db, router, make_context, make_snapshot, tmp_path):
    engine = AnalyticsEngine(db, tmp_path)
    empty_id, _ = db.start_mission("LIVE")
    full_id = populated_mission(db, router, make_context, make_snapshot)
    charts = (engine.plot_timeline, engine.plot_packet_outcomes, engine.plot_mode_performance,
              engine.plot_correlation_heatmap, engine.plot_incident_distribution)
    for mission_id in (empty_id, full_id):
        data = engine.load(mission_id)
        for draw in charts:
            figure = Figure()
            draw(figure, data)
            assert figure.axes                     # something was drawn


def test_exports_write_timestamped_files(db, router, make_context, make_snapshot, tmp_path):
    engine = AnalyticsEngine(db, tmp_path / "exports")
    mission_id = populated_mission(db, router, make_context, make_snapshot)
    for table in ("telemetry", "packets", "decisions"):
        path = engine.export_table(mission_id, table)
        assert path.exists() and path.name.startswith(table)
    summary = engine.save_summary(mission_id)
    assert "MISSION SUMMARY" in summary.read_text(encoding="utf-8")
