"""Pandas summaries and Figure-only dark charts for mission archives."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure
from app import config
from app.database.database_manager import DatabaseManager
from app.utils.helpers import format_met, timestamped_filename

logger = logging.getLogger(__name__)
DARK_CHART = {"background": "#12161C", "text": "#B4BCC8", "grid": "#252C36",
              "battery": "#30D158", "signal": "#64D2FF", "temperature": "#FF9F0A",
              "power": "#BF5AF2", "failed": "#FF453A", "sent": "#30D158",
              "deferred": "#FF9F0A", "queued": "#7B8594"}

def apply_dark_style(fig: Figure, axes) -> None:
    """Style every supplied axes without touching pyplot global state."""
    fig.patch.set_facecolor(DARK_CHART["background"])
    for ax in axes:
        ax.set_facecolor(DARK_CHART["background"])
        ax.tick_params(colors=DARK_CHART["text"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(DARK_CHART["grid"])
        ax.xaxis.label.set_color(DARK_CHART["text"])
        ax.yaxis.label.set_color(DARK_CHART["text"])
        ax.title.set_color(DARK_CHART["text"])
        ax.grid(color=DARK_CHART["grid"], alpha=0.7)

@dataclass
class MissionData:
    """All archive tables needed for one mission's analytics."""
    mission: dict
    telemetry: pd.DataFrame
    packets: pd.DataFrame
    decisions: pd.DataFrame
    incidents: pd.DataFrame
    @property
    def empty(self) -> bool:
        """Whether no archive rows exist yet."""
        return all(frame.empty for frame in (self.telemetry, self.packets, self.decisions, self.incidents))

class AnalyticsEngine:
    """Builds summaries, tables, charts, and export files from SQLite."""
    def __init__(self, db: DatabaseManager, exports_dir: Path = config.EXPORTS_DIR):
        self.db, self.exports_dir = db, Path(exports_dir)
    def load(self, mission_id: int) -> MissionData:
        """Load all analysis tables for one mission."""
        return MissionData(self.db.get_mission(mission_id) or {}, *(self.db.read_dataframe(table, mission_id)
                           for table in ("telemetry", "packets", "decisions", "incidents")))
    def summary(self, data: MissionData) -> dict:
        """Calculate display and export KPIs from actual stored records."""
        t, p, d, i = data.telemetry, data.packets, data.decisions, data.incidents
        metric = lambda frame, col, op: float(getattr(frame[col], op)()) if not frame.empty and col in frame else 0.0
        attempts = len(d)
        sent = int((p["status"] == "SENT").sum()) if not p.empty else 0
        incident_counts = i["incident_type"].value_counts().to_dict() if not i.empty else {}
        duration = metric(t, "mission_time", "max")
        in_pass = t[t["signal"] >= config.REPLAY_PASS_SIGNAL_THRESHOLD] if not t.empty else t
        return dict(mission_code=data.mission.get("mission_code", ""), mode=data.mission.get("mode", ""),
                    duration_s=duration, duration=format_met(duration), packets_generated=len(p),
                    packets_transmitted=sent, packets_failed=int((p["status"] == "FAILED").sum()) if not p.empty else 0,
                    packets_deferred=int((p["status"] == "DEFERRED").sum()) if not p.empty else 0,
                    packets_corrupted=int(p["corrupted"].sum()) if not p.empty else 0,
                    packets_dropped=int((p["status"] == "DROPPED").sum()) if not p.empty else 0,
                    attempts=attempts, success_rate=sent / attempts * 100 if attempts else 0.0,
                    avg_signal=metric(in_pass, "signal", "mean"), avg_battery=metric(t, "battery", "mean"),
                    min_battery=metric(t, "battery", "min"), peak_temperature=metric(t, "temperature", "max"),
                    avg_power_draw=metric(t, "power_draw", "mean"),
                    battery_std=float(np.std(t["battery"])) if not t.empty else 0.0,
                    signal_std=float(np.std(t["signal"])) if not t.empty else 0.0,
                    count_by_type=p["packet_type"].value_counts().to_dict() if not p.empty else {},
                    sent_by_type=p.loc[p["status"] == "SENT", "packet_type"].value_counts().to_dict() if not p.empty else {},
                    safe_mode_activations=incident_counts.get("SAFE_MODE", 0),
                    communication_failures=incident_counts.get("COMM_FAILURE", 0),
                    thermal_alerts=incident_counts.get("THERMAL_ALERT", 0),
                    low_power_events=incident_counts.get("LOW_POWER", 0), incident_count=len(i))
    def telemetry_stats(self, data: MissionData) -> dict:
        """Calculate NumPy statistics across every stored sensor metric."""
        names = ("battery", "temperature", "signal", "power_draw", "packet_loss")
        def stats(name):
            series = data.telemetry[name].dropna().to_numpy(dtype=float) if name in data.telemetry else np.array([])
            return name, dict(mean=float(np.mean(series)) if len(series) else 0.0,
                              std=float(np.std(series)) if len(series) else 0.0,
                              min=float(np.min(series)) if len(series) else 0.0,
                              max=float(np.max(series)) if len(series) else 0.0)
        return dict(map(stats, names))
    def success_by_type(self, data: MissionData) -> pd.DataFrame:
        """Group packet outcomes by type."""
        if data.packets.empty:
            return pd.DataFrame(columns=["packet_type", "generated", "sent", "failed", "success_rate"])
        grouped = data.packets.groupby("packet_type").agg(generated=("packet_id", "count"),
            sent=("status", lambda s: int((s == "SENT").sum())),
            failed=("status", lambda s: int((s == "FAILED").sum()))).reset_index()
        grouped["success_rate"] = grouped["sent"] / grouped["generated"] * 100
        return grouped
    def mode_performance(self, data: MissionData) -> pd.DataFrame:
        """Group router attempts, score, and signal by selected mode."""
        if data.decisions.empty:
            return pd.DataFrame(columns=["selected_mode", "attempts", "avg_score", "avg_signal"])
        return data.decisions.groupby("selected_mode").agg(attempts=("decision_id", "count"),
            avg_score=("total_score", "mean"), avg_signal=("signal", "mean")).reset_index()
    def _empty(self, fig: Figure, title: str) -> None:
        fig.clear()
        ax = fig.add_subplot(111)
        apply_dark_style(fig, [ax])
        ax.set_title(title, fontsize=11)
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", color=DARK_CHART["text"], transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    def plot_timeline(self, fig: Figure, data: MissionData) -> None:
        """Draw battery, signal, and temperature versus mission time."""
        if data.telemetry.empty:
            self._empty(fig, "Telemetry timeline")
            return
        fig.clear()
        axes = fig.subplots(2, 1, sharex=True)
        t = data.telemetry
        axes[0].plot(t["mission_time"], t["battery"], color=DARK_CHART["battery"], label="Battery")
        axes[0].plot(t["mission_time"], t["signal"], color=DARK_CHART["signal"], label="Signal")
        axes[1].plot(t["mission_time"], t["temperature"], color=DARK_CHART["temperature"], label="Temperature")
        apply_dark_style(fig, axes)
        for ax in axes:
            ax.legend(facecolor=DARK_CHART["background"], labelcolor=DARK_CHART["text"], fontsize=9)
        axes[1].set_xlabel("Mission time (s)")
        fig.tight_layout()
    def plot_packet_outcomes(self, fig: Figure, data: MissionData) -> None:
        """Draw stacked status counts by packet type."""
        if data.packets.empty:
            self._empty(fig, "Packet outcomes")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        table = pd.crosstab(data.packets["packet_type"], data.packets["status"])
        colors = {"SENT": DARK_CHART["sent"], "FAILED": DARK_CHART["failed"],
                  "DEFERRED": DARK_CHART["deferred"], "QUEUED": DARK_CHART["queued"]}
        table.plot.bar(stacked=True, ax=ax, color=[colors.get(s, DARK_CHART["signal"]) for s in table.columns])
        apply_dark_style(fig, [ax])
        ax.legend(facecolor=DARK_CHART["background"], labelcolor=DARK_CHART["text"], fontsize=9)
        fig.tight_layout()
    def plot_mode_performance(self, fig: Figure, data: MissionData) -> None:
        """Draw average routing score per communication mode."""
        perf = self.mode_performance(data)
        if perf.empty:
            self._empty(fig, "Mode performance")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        sns.barplot(data=perf, x="selected_mode", y="avg_score", color=DARK_CHART["signal"], ax=ax)
        apply_dark_style(fig, [ax])
        fig.tight_layout()
    def plot_correlation_heatmap(self, fig: Figure, data: MissionData) -> None:
        """Draw a dark Seaborn correlation heatmap."""
        cols = [c for c in ("battery", "temperature", "signal", "power_draw", "packet_loss") if c in data.telemetry]
        if data.telemetry.empty or len(data.telemetry) < 2:
            self._empty(fig, "Telemetry correlation")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        sns.heatmap(data.telemetry[cols].corr(), cmap="mako", ax=ax, annot=True, fmt=".2f",
                    annot_kws={"color": DARK_CHART["text"], "size": 9})
        apply_dark_style(fig, [ax])
        fig.tight_layout()
    def plot_incident_distribution(self, fig: Figure, data: MissionData) -> None:
        """Draw incident counts by type and severity."""
        if data.incidents.empty:
            self._empty(fig, "Incident distribution")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        sns.countplot(data=data.incidents, x="incident_type", hue="severity", ax=ax,
                      palette={"INFO": DARK_CHART["signal"], "WARNING": DARK_CHART["deferred"], "CRITICAL": DARK_CHART["failed"]})
        apply_dark_style(fig, [ax])
        ax.tick_params(axis="x", rotation=30)
        fig.tight_layout()
    def export_table(self, mission_id: int, table: str) -> Path:
        """Export one whitelisted mission table to CSV."""
        if table not in ("telemetry", "packets", "decisions"):
            raise ValueError(f"Unsupported export table: {table}")
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.exports_dir / timestamped_filename(table, "csv")
        self.db.read_dataframe(table, mission_id).to_csv(path, index=False)
        return path
    def save_summary(self, mission_id: int) -> Path:
        """Save a human-readable mission KPI summary."""
        summary = self.summary(self.load(mission_id))
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.exports_dir / timestamped_filename(f"summary_{summary['mission_code']}", "txt")
        path.write_text("\n".join(f"{key}: {value}" for key, value in summary.items()), encoding="utf-8")
        return path
