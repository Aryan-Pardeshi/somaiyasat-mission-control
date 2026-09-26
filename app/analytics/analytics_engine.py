"""Mission analytics: Pandas summaries, NumPy statistics and dark-themed charts.

Everything here reads from SQLite (through DatabaseManager), so the numbers in
the Analytics page, the Summary page and the CSV exports always describe what
was actually stored during a mission.

Charts are drawn on a ``matplotlib.figure.Figure`` supplied by the caller.
We never use pyplot's global state, which keeps plotting safe inside Tkinter.
Seaborn functions always receive ``ax=`` for the same reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from app import config
from app.database.database_manager import DatabaseManager
from app.utils.helpers import format_met, timestamped_filename

logger = logging.getLogger(__name__)

# Colours match the Tkinter theme so charts look like part of the app.
DARK_CHART = {
    "background": "#0F1624", "text": "#A7B3C8", "title": "#EDF2FA", "grid": "#1C2840",
    "battery": "#34D399", "signal": "#38D6F5", "temperature": "#FFB020",
    "power": "#A78BFA", "failed": "#FF5A6A", "sent": "#34D399",
    "deferred": "#FFB020", "queued": "#6C7A93", "dropped": "#C2414F",
}
STATUS_COLORS = {
    "SENT": DARK_CHART["sent"], "QUEUED": DARK_CHART["queued"], "DEFERRED": DARK_CHART["deferred"],
    "FAILED": DARK_CHART["failed"], "DROPPED": DARK_CHART["dropped"],
    "SELECTED": DARK_CHART["signal"], "TRANSMITTING": DARK_CHART["signal"],
}
TYPE_LABELS = {"TTC": "TT&C", "HOUSEKEEPING": "Housekeeping", "SSTV": "SSTV", "M17": "M17", "CODEC2": "Codec2"}
MODE_ORDER = ["TTC", "CODEC2", "M17", "SSTV"]
TELEMETRY_METRICS = ("battery", "temperature", "signal", "power_draw", "packet_loss")


def apply_dark_style(fig: Figure, axes) -> None:
    """Style every supplied axes for the dark UI (no pyplot global state)."""
    fig.patch.set_facecolor(DARK_CHART["background"])
    for ax in axes:
        ax.set_facecolor(DARK_CHART["background"])
        ax.tick_params(colors=DARK_CHART["text"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(DARK_CHART["grid"])
        ax.xaxis.label.set_color(DARK_CHART["text"])
        ax.yaxis.label.set_color(DARK_CHART["text"])
        ax.title.set_color(DARK_CHART["title"])
        ax.grid(color=DARK_CHART["grid"], alpha=0.8, linewidth=0.8)
        ax.set_axisbelow(True)          # grid lines behind bars, not on top of them


def _style_legend(ax, **kwargs) -> None:
    legend = ax.legend(facecolor=DARK_CHART["background"], edgecolor=DARK_CHART["grid"],
                       labelcolor=DARK_CHART["text"], fontsize=9, **kwargs)
    if legend and legend.get_title():
        legend.get_title().set_color(DARK_CHART["text"])


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
        """True when no rows at all have been stored for the mission yet."""
        return all(frame.empty for frame in (self.telemetry, self.packets, self.decisions, self.incidents))


class AnalyticsEngine:
    """Builds summaries, grouped statistics, charts and CSV exports from SQLite."""

    def __init__(self, db: DatabaseManager, exports_dir: Path = config.EXPORTS_DIR):
        self.db = db
        self.exports_dir = Path(exports_dir)

    # ------------------------------------------------------------------ data
    def load(self, mission_id: int) -> MissionData:
        """Load the four analysis tables of one mission as Pandas DataFrames."""
        frames = (self.db.read_dataframe(table, mission_id)
                  for table in ("telemetry", "packets", "decisions", "incidents"))
        return MissionData(self.db.get_mission(mission_id) or {}, *frames)

    def summary(self, data: MissionData) -> dict:
        """Calculate the mission summary KPIs from the stored records."""
        t, p, d, i = data.telemetry, data.packets, data.decisions, data.incidents

        def metric(frame: pd.DataFrame, column: str, operation: str) -> float:
            """Pandas aggregate (mean/min/max) that returns 0.0 for empty data."""
            if frame.empty or column not in frame:
                return 0.0
            return float(getattr(frame[column], operation)())

        def count_status(status: str) -> int:
            return int((p["status"] == status).sum()) if not p.empty else 0

        # Every transmission attempt starts with a routing decision, so
        # success rate = packets delivered / decisions made.
        attempts = len(d)
        sent = count_status("SENT")
        incident_counts = i["incident_type"].value_counts().to_dict() if not i.empty else {}
        duration = metric(t, "mission_time", "max")
        # Average link quality only makes sense while a ground pass is active.
        in_pass = t[t["signal"] >= config.REPLAY_PASS_SIGNAL_THRESHOLD] if not t.empty else t
        return {
            "mission_code": data.mission.get("mission_code", ""),
            "mode": data.mission.get("mode", ""),
            "duration_s": duration,
            "duration": format_met(duration),
            "packets_generated": len(p),
            "packets_transmitted": sent,
            "packets_failed": count_status("FAILED"),
            "packets_deferred": count_status("DEFERRED"),
            "packets_corrupted": int(p["corrupted"].sum()) if not p.empty else 0,
            "packets_dropped": count_status("DROPPED"),
            "attempts": attempts,
            "success_rate": sent / attempts * 100 if attempts else 0.0,
            "avg_signal": metric(in_pass, "signal", "mean"),
            "avg_battery": metric(t, "battery", "mean"),
            "min_battery": metric(t, "battery", "min"),
            "peak_temperature": metric(t, "temperature", "max"),
            "avg_power_draw": metric(t, "power_draw", "mean"),
            "battery_std": float(np.std(t["battery"])) if not t.empty else 0.0,
            "signal_std": float(np.std(t["signal"])) if not t.empty else 0.0,
            "count_by_type": p["packet_type"].value_counts().to_dict() if not p.empty else {},
            "sent_by_type": p.loc[p["status"] == "SENT", "packet_type"].value_counts().to_dict() if not p.empty else {},
            "safe_mode_activations": incident_counts.get("SAFE_MODE", 0),
            "communication_failures": incident_counts.get("COMM_FAILURE", 0),
            "thermal_alerts": incident_counts.get("THERMAL_ALERT", 0),
            "low_power_events": incident_counts.get("LOW_POWER", 0),
            "incident_count": len(i),
        }

    def telemetry_stats(self, data: MissionData) -> dict:
        """NumPy mean / std / min / max for every telemetry metric.

        ``map()`` applies the same statistics function to each metric name.
        """
        def stats(name: str) -> tuple[str, dict]:
            if name in data.telemetry:
                series = data.telemetry[name].dropna().to_numpy(dtype=float)
            else:
                series = np.array([])
            if not len(series):
                return name, {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
            return name, {"mean": float(np.mean(series)), "std": float(np.std(series)),
                          "min": float(np.min(series)), "max": float(np.max(series))}

        return dict(map(stats, TELEMETRY_METRICS))

    def success_by_type(self, data: MissionData) -> pd.DataFrame:
        """Packets generated / sent / failed and success % grouped by packet type."""
        if data.packets.empty:
            return pd.DataFrame(columns=["packet_type", "generated", "sent", "failed", "success_rate"])
        grouped = data.packets.groupby("packet_type").agg(
            generated=("packet_id", "count"),
            sent=("status", lambda s: int((s == "SENT").sum())),
            failed=("status", lambda s: int((s == "FAILED").sum())),
        ).reset_index()
        grouped["success_rate"] = grouped["sent"] / grouped["generated"] * 100
        return grouped

    def mode_performance(self, data: MissionData) -> pd.DataFrame:
        """Routing attempts, average score and average link quality per mode."""
        if data.decisions.empty:
            return pd.DataFrame(columns=["selected_mode", "attempts", "avg_score", "avg_signal"])
        return data.decisions.groupby("selected_mode").agg(
            attempts=("decision_id", "count"),
            avg_score=("total_score", "mean"),
            avg_signal=("signal", "mean"),
        ).reset_index()

    # ---------------------------------------------------------------- charts
    def _empty(self, fig: Figure, title: str) -> None:
        fig.clear()
        ax = fig.add_subplot(111)
        apply_dark_style(fig, [ax])
        ax.set_title(title, fontsize=11, loc="left", color=DARK_CHART["title"])
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color=DARK_CHART["text"], transform=ax.transAxes, fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)

    def plot_timeline(self, fig: Figure, data: MissionData) -> None:
        """Battery & signal (top) and temperature (bottom) against mission time."""
        if data.telemetry.empty:
            self._empty(fig, "Telemetry timeline")
            return
        fig.clear()
        axes = fig.subplots(2, 1, sharex=True)
        t = data.telemetry
        axes[0].plot(t["mission_time"], t["signal"], color=DARK_CHART["signal"], lw=1.3, label="Signal %")
        axes[0].fill_between(t["mission_time"], t["signal"], color=DARK_CHART["signal"], alpha=0.10)
        axes[0].plot(t["mission_time"], t["battery"], color=DARK_CHART["battery"], lw=2.0, label="Battery %")
        axes[0].axhline(config.BATTERY_LOW_THRESHOLD, color=DARK_CHART["deferred"], ls="--", lw=0.8, alpha=0.7)
        axes[0].axhline(config.BATTERY_CRITICAL_THRESHOLD, color=DARK_CHART["failed"], ls="--", lw=0.8, alpha=0.7)
        axes[0].set_ylim(0, 105)
        axes[0].set_title("Battery and link quality", fontsize=10, loc="left", color=DARK_CHART["title"])
        axes[1].plot(t["mission_time"], t["temperature"], color=DARK_CHART["temperature"], lw=1.8, label="Temperature °C")
        axes[1].axhline(config.TEMP_WARNING_THRESHOLD, color=DARK_CHART["deferred"], ls="--", lw=0.8, alpha=0.7)
        axes[1].axhline(config.TEMP_CRITICAL_THRESHOLD, color=DARK_CHART["failed"], ls="--", lw=0.8, alpha=0.7)
        axes[1].set_title("Onboard temperature", fontsize=10, loc="left", color=DARK_CHART["title"])
        axes[1].set_xlabel("Mission elapsed time (s)")
        apply_dark_style(fig, axes)
        for ax in axes:
            _style_legend(ax, loc="upper right", ncol=2)
        fig.tight_layout(pad=1.2)

    def plot_packet_outcomes(self, fig: Figure, data: MissionData) -> None:
        """Horizontal stacked bars: what happened to each packet type."""
        if data.packets.empty:
            self._empty(fig, "Packet outcomes")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        table = pd.crosstab(data.packets["packet_type"], data.packets["status"])
        order = [s for s in ("SENT", "QUEUED", "DEFERRED", "FAILED", "DROPPED") if s in table.columns]
        order += [s for s in table.columns if s not in order]
        table = table[order].rename(index=TYPE_LABELS)
        table.plot.barh(stacked=True, ax=ax, width=0.65,
                        color=[STATUS_COLORS.get(s, DARK_CHART["queued"]) for s in table.columns])
        ax.set_xlabel("Packets")
        ax.set_ylabel("")
        ax.set_title("Packet outcomes by type", fontsize=11, loc="left", color=DARK_CHART["title"])
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        apply_dark_style(fig, [ax])
        ax.grid(axis="y", visible=False)
        _style_legend(ax, loc="lower right", title="Status")
        fig.tight_layout(pad=1.2)

    def plot_mode_performance(self, fig: Figure, data: MissionData) -> None:
        """Seaborn bars per communication mode: attempts and average score."""
        perf = self.mode_performance(data)
        if perf.empty:
            self._empty(fig, "Communication mode performance")
            return
        # Show every mode, even ones never selected, so the comparison is fair.
        perf = perf.set_index("selected_mode").reindex(MODE_ORDER, fill_value=0).reset_index()
        perf["mode"] = perf["selected_mode"].map({"TTC": "TT&C", "CODEC2": "Codec2", "M17": "M17", "SSTV": "SSTV"})
        fig.clear()
        left, right = fig.subplots(1, 2)
        palette = {"TT&C": "#64D2FF", "Codec2": "#5E5CE6", "M17": "#0A84FF", "SSTV": "#BF5AF2"}
        sns.barplot(data=perf, x="mode", y="attempts", hue="mode", palette=palette, legend=False, ax=left)
        sns.barplot(data=perf, x="mode", y="avg_score", hue="mode", palette=palette, legend=False, ax=right)
        left.set_title("Transmission attempts per mode", fontsize=10, loc="left", color=DARK_CHART["title"])
        right.set_title("Average routing score per mode", fontsize=10, loc="left", color=DARK_CHART["title"])
        left.yaxis.set_major_locator(MaxNLocator(integer=True))
        right.set_ylim(0, 100)
        for ax in (left, right):
            ax.set_xlabel("")
            ax.set_ylabel("")
        apply_dark_style(fig, [left, right])
        fig.tight_layout(pad=1.2)

    def plot_correlation_heatmap(self, fig: Figure, data: MissionData) -> None:
        """Seaborn heatmap of how telemetry channels move together (Pearson r)."""
        cols = [c for c in TELEMETRY_METRICS if c in data.telemetry]
        if data.telemetry.empty or len(data.telemetry) < 3:
            self._empty(fig, "Telemetry correlation")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        labels = {"battery": "Battery", "temperature": "Temperature", "signal": "Signal",
                  "power_draw": "Power draw", "packet_loss": "Packet loss"}
        corr = data.telemetry[cols].corr().rename(index=labels, columns=labels)
        # A diverging palette that fades to dark (not white) in the middle suits the dark UI.
        cmap = sns.diverging_palette(245, 15, s=80, l=55, center="dark", as_cmap=True)
        sns.heatmap(corr, cmap=cmap, vmin=-1, vmax=1, center=0, ax=ax, annot=True, fmt=".2f",
                    linewidths=2, linecolor=DARK_CHART["background"], square=False,
                    annot_kws={"size": 10, "weight": "bold", "color": DARK_CHART["title"]},
                    cbar_kws={"shrink": 0.85})
        apply_dark_style(fig, [ax])
        ax.grid(False)
        ax.set_title("Telemetry correlation (Pearson r)", fontsize=11, loc="left", color=DARK_CHART["title"])
        ax.tick_params(axis="x", rotation=0)
        ax.tick_params(axis="y", rotation=0)
        colorbar = ax.collections[0].colorbar
        colorbar.ax.tick_params(colors=DARK_CHART["text"], labelsize=8)
        fig.tight_layout(pad=1.2)

    def plot_incident_distribution(self, fig: Figure, data: MissionData) -> None:
        """Seaborn count of incidents by type, coloured by severity."""
        if data.incidents.empty:
            self._empty(fig, "Incident distribution")
            return
        fig.clear()
        ax = fig.add_subplot(111)
        incidents = data.incidents.copy()
        incidents["incident"] = incidents["incident_type"].str.replace("_", " ").str.title()
        order = incidents["incident"].value_counts().index
        sns.countplot(data=incidents, y="incident", hue="severity", order=order, ax=ax,
                      palette={"INFO": DARK_CHART["signal"], "WARNING": DARK_CHART["deferred"],
                               "CRITICAL": DARK_CHART["failed"]})
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("Count")
        ax.set_ylabel("")
        ax.set_title("Incidents by type and severity", fontsize=11, loc="left", color=DARK_CHART["title"])
        apply_dark_style(fig, [ax])
        ax.grid(axis="y", visible=False)
        _style_legend(ax, loc="lower right", title="Severity")
        fig.tight_layout(pad=1.2)

    # --------------------------------------------------------------- exports
    def export_table(self, mission_id: int, table: str) -> Path:
        """Export one mission table (telemetry / packets / decisions / incidents) to CSV."""
        if table not in ("telemetry", "packets", "decisions", "incidents"):
            raise ValueError(f"Unsupported export table: {table}")
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.exports_dir / timestamped_filename(table, "csv")
        self.db.read_dataframe(table, mission_id).to_csv(path, index=False)
        logger.info("Exported %s for mission %s to %s", table, mission_id, path)
        return path

    def save_summary(self, mission_id: int) -> Path:
        """Save a formatted, human-readable mission summary text file."""
        s = self.summary(self.load(mission_id))
        by_type = "\n".join(
            f"  {TYPE_LABELS.get(kind, kind):<13} {s['sent_by_type'].get(kind, 0):>4} sent / "
            f"{count:>4} generated" for kind, count in sorted(s["count_by_type"].items()))
        text = f"""SOMAIYASAT MISSION CONTROL — MISSION SUMMARY
============================================
Mission            {s['mission_code']}  ({s['mode']})
Duration           {s['duration']}

PACKETS
  Generated        {s['packets_generated']}
  Transmitted      {s['packets_transmitted']}
  Failed           {s['packets_failed']}
  Deferred (end)   {s['packets_deferred']}
  Corrupted        {s['packets_corrupted']}
  Dropped          {s['packets_dropped']}
  Attempts         {s['attempts']}
  Success rate     {s['success_rate']:.1f} %

TELEMETRY
  Avg link quality {s['avg_signal']:.1f} %   (in-pass rows)
  Avg battery      {s['avg_battery']:.1f} %   (std {s['battery_std']:.1f})
  Min battery      {s['min_battery']:.1f} %
  Peak temperature {s['peak_temperature']:.1f} °C
  Avg power draw   {s['avg_power_draw']:.2f} W

BY PACKET TYPE
{by_type or '  (none)'}

EVENTS
  Safe-mode activations   {s['safe_mode_activations']}
  Communication failures  {s['communication_failures']}
  Thermal alerts          {s['thermal_alerts']}
  Low-power events        {s['low_power_events']}
  Total incidents         {s['incident_count']}

Educational digital twin — not connected to real spacecraft.
"""
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.exports_dir / timestamped_filename(f"summary_{s['mission_code']}", "txt")
        path.write_text(text, encoding="utf-8")
        logger.info("Saved mission summary to %s", path)
        return path
