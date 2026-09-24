"""CSV replay operation, mission charts, and exportable summaries."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

from app import config
from app.exceptions import ReplayDataError
from app.models.enums import MissionMode
from app.utils.helpers import format_met
from .base_page import BasePage
from .chart_panel import ChartPanel
from .components import Card, DataTable, KeyValueList, MetricCard, ModernButton, ProgressBar, ScrollableFrame, SegmentedControl
from .theme import COLORS, FONTS, px

LOG = logging.getLogger(__name__)
CHARTS = {
    "Timeline": "plot_timeline",
    "Packet outcomes": "plot_packet_outcomes",
    "Mode performance": "plot_mode_performance",
    "Correlation": "plot_correlation_heatmap",
    "Incidents": "plot_incident_distribution",
}


class AnalyticsPage(BasePage):
    """Switch between validated CSV replay, on-demand charts and summary."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.build_header("Mission Analytics & Replay", "Validate a CSV, explore saved outcomes, and export mission evidence")
        self._section = "Replay"
        self._mission_id: int | None = None
        self._mission_labels: dict[str, int | None] = {}
        self._data = None
        self._summary: dict = {}
        self._last_refresh = 0.0
        self._csv_ready = False
        tabs = tk.Frame(self, bg=COLORS["bg"])
        tabs.pack(fill="x", padx=px(24), pady=(0, px(11)))
        self.tabs_row = tabs
        self.sections = SegmentedControl(tabs, ("Replay", "Analytics", "Summary"), command=self._switch)
        self.sections.pack(side="left")
        self.host = tk.Frame(self, bg=COLORS["bg"])
        self.host.pack(fill="both", expand=True, padx=px(24), pady=(0, px(15)))
        self.host.grid_rowconfigure(0, weight=1)
        self.host.grid_columnconfigure(0, weight=1)
        self._build_replay()
        self._build_analytics()
        self._build_summary()
        self._switch("Replay")

    def _build_replay(self) -> None:
        scroll = ScrollableFrame(self.host)
        scroll.grid(row=0, column=0, sticky="nsew")
        self.replay_section = scroll
        body = scroll.body
        picker = Card(body, title="Import mission CSV", padding=px(12))
        picker.pack(fill="x", pady=(0, px(10)))
        row = tk.Frame(picker.body, bg=COLORS["card"])
        row.pack(fill="x")
        ModernButton(row, "IMPORT MISSION CSV", command=self._choose_csv, kind="primary", bg=COLORS["card"]).pack(side="left", padx=(0, px(8)))
        ModernButton(row, "sample_mission.csv", command=lambda: self.load_csv(config.SAMPLE_MISSION_CSV), bg=COLORS["card"]).pack(side="left", padx=(0, px(8)))
        ModernButton(row, "stressful_mission.csv", command=lambda: self.load_csv(config.STRESSFUL_MISSION_CSV), bg=COLORS["card"]).pack(side="left")
        self.source = tk.Label(picker.body, text="Select a CSV to validate and preview", bg=COLORS["card"],
                               fg=COLORS["text_2"], font=FONTS["small"], anchor="w")
        self.source.pack(fill="x", pady=(px(8), 0))
        report = Card(body, title="Validation report", padding=px(12))
        report.pack(fill="x", pady=(0, px(10)))
        self.report_card = report
        self.report = tk.Label(report.body, text="No CSV loaded", bg=COLORS["card"],
                               fg=COLORS["text_2"], font=FONTS["body"], justify="left", anchor="w")
        self.report.pack(fill="x")
        self.errors = tk.Label(report.body, text="", bg=COLORS["card"], fg=COLORS["red"],
                               font=FONTS["small"], justify="left", anchor="w")
        self.errors.pack(fill="x", pady=(px(4), 0))
        preview = Card(body, title="Validated row preview", padding=px(11))
        preview.pack(fill="x", pady=(0, px(10)))
        preview.configure(height=px(193))
        preview.pack_propagate(False)
        columns = ("timestamp", "battery", "temp", "signal", "power_draw", "packet_loss", "packet_type", "priority", "size_kb", "event")
        headings = {"power_draw": "POWER W", "packet_loss": "LOSS %", "packet_type": "PACKET",
                    "size_kb": "SIZE KB"}
        self.preview = DataTable(preview.body, [(name, headings.get(name, name.upper()), 90, "w") for name in columns])
        self.preview.pack(fill="both", expand=True)
        controls = Card(body, title="Replay controls", padding=px(12))
        controls.pack(fill="x")
        buttons = tk.Frame(controls.body, bg=COLORS["card"])
        buttons.pack(fill="x")
        self.start_button = ModernButton(buttons, "START REPLAY", command=self._start_replay, kind="primary", bg=COLORS["card"])
        self.start_button.pack(side="left", padx=(0, px(7)))
        self.pause_button = ModernButton(buttons, "PAUSE", command=self._toggle_pause, bg=COLORS["card"])
        self.pause_button.pack(side="left", padx=(0, px(7)))
        self.reset_button = ModernButton(buttons, "RESET", command=self._reset_replay, bg=COLORS["card"])
        self.reset_button.pack(side="left", padx=(0, px(12)))
        self.speeds = SegmentedControl(buttons, ("0.5x", "1x", "2x", "5x"), selected="1x", command=self._set_speed)
        self.speeds.pack(side="left")
        self.progress_text = tk.Label(controls.body, text="row 0/0 · 00:00:00 / 00:00:00", bg=COLORS["card"],
                                      fg=COLORS["text_2"], font=FONTS["small"], anchor="w")
        self.progress_text.pack(fill="x", pady=(px(9), px(4)))
        self.progress = ProgressBar(controls.body, bg=COLORS["card"])
        self.progress.pack(fill="x")
        nav = tk.Frame(controls.body, bg=COLORS["card"])
        nav.pack(fill="x", pady=(px(8), 0))
        ModernButton(nav, "Watch on Overview", command=lambda: self.app.show_page("overview"), kind="ghost", bg=COLORS["card"]).pack(side="left")
        ModernButton(nav, "Open Router", command=lambda: self.app.show_page("router"), kind="ghost", bg=COLORS["card"]).pack(side="left", padx=px(9))
        controls.pack(before=preview)
        self._sync_replay()

    def _build_analytics(self) -> None:
        frame = tk.Frame(self.host, bg=COLORS["bg"])
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.analytics_section = frame
        selector = tk.Frame(self.tabs_row, bg=COLORS["bg"])
        selector.pack(side="right")
        tk.Label(selector, text="MISSION", bg=COLORS["bg"], fg=COLORS["muted"], font=FONTS["caption"]).pack(side="left", padx=(0, px(7)))
        self.mission_var = tk.StringVar(value="Current mission")
        self.mission_choice = ttk.Combobox(selector, textvariable=self.mission_var, state="readonly", width=35)
        self.mission_choice.pack(side="left", padx=(0, px(9)))
        self.mission_choice.bind("<<ComboboxSelected>>", lambda _: self._choose_mission())
        ModernButton(selector, "REFRESH", command=self.refresh_analytics, bg=COLORS["bg"]).pack(side="left")
        kpi = tk.Frame(frame, bg=COLORS["bg"])
        kpi.grid(row=0, column=0, sticky="ew", pady=(0, px(9)))
        self.metrics: dict[str, MetricCard] = {}
        for i, (key, title, unit) in enumerate((
            ("packets_generated", "TOTAL PACKETS", ""), ("success_rate", "SUCCESS RATE", "%"),
            ("avg_signal", "AVG SIGNAL", "%"), ("avg_battery", "AVG BATTERY", "%"),
            ("peak_temperature", "PEAK TEMP", "°C"), ("incident_count", "INCIDENTS", ""))):
            kpi.grid_columnconfigure(i, weight=1, uniform="kpi")
            card = MetricCard(kpi, title, value="—", unit=unit, status="INFO",
                              subtitle="From SQLite", level=0,
                              format_string="{:.0f}" if key in ("packets_generated", "incident_count") else "{:.1f}")
            card.grid(row=0, column=i, sticky="nsew", padx=(0, px(7)) if i < 5 else 0)
            card.badge.pack_forget()
            card.level_bar.pack_forget()
            card.subtitle_label.pack_forget()
            self.metrics[key] = card
        chart = Card(frame, title="Mission charts", padding=px(10))
        chart.grid(row=1, column=0, sticky="nsew")
        self.chart_choice = SegmentedControl(chart.body, list(CHARTS), command=lambda _: self._render_chart())
        self.chart_choice.pack(anchor="w", pady=(0, px(7)))
        self.chart = ChartPanel(chart.body)
        self.chart.pack(fill="both", expand=True)

    def _build_summary(self) -> None:
        scroll = ScrollableFrame(self.host)
        scroll.grid(row=0, column=0, sticky="nsew")
        self.summary_section = scroll
        body = scroll.body
        self.summary_title = tk.Label(body, text="MISSION SUMMARY", bg=COLORS["bg"],
                                      fg=COLORS["text"], font=FONTS["h2"], anchor="w")
        self.summary_title.pack(fill="x", pady=(0, px(10)))
        grid = tk.Frame(body, bg=COLORS["bg"])
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="summary")
        left = tk.Frame(grid, bg=COLORS["bg"])
        right = tk.Frame(grid, bg=COLORS["bg"])
        left.grid(row=0, column=0, sticky="new", padx=(0, px(7)))
        right.grid(row=0, column=1, sticky="new", padx=(px(7), 0))
        self.facts: dict[str, KeyValueList] = {}
        for column, names in ((left, ("Mission", "Telemetry", "Events")),
                              (right, ("Packets", "By type"))):
            for name in names:
                card = Card(column, title=name, padding=px(12))
                card.pack(fill="x", pady=(0, px(10)))
                facts = KeyValueList(card.body)
                facts.pack(fill="x")
                self.facts[name] = facts
        exports = Card(body, title="Export mission evidence", padding=px(11))
        exports.pack(fill="x", pady=(px(2), px(10)))
        for title, table in (("EXPORT TELEMETRY CSV", "telemetry"),
                             ("EXPORT PACKET LOG CSV", "packets"),
                             ("EXPORT DECISION LOG CSV", "decisions")):
            ModernButton(exports.body, title, command=lambda name=table: self._export(name),
                         bg=COLORS["card"]).pack(side="left", padx=(0, px(7)))
        ModernButton(exports.body, "SAVE SUMMARY", command=self._save_summary,
                     kind="primary", bg=COLORS["card"]).pack(side="left", padx=(0, px(7)))
        ModernButton(exports.body, "Open exports folder", command=self._open_exports,
                     kind="ghost", bg=COLORS["card"]).pack(side="left")

    def _switch(self, section: str) -> None:
        self._section = section
        {"Replay": self.replay_section, "Analytics": self.analytics_section,
         "Summary": self.summary_section}[section].tkraise()
        if self.visible and section != "Replay":
            self.refresh_analytics()

    def _choose_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Import mission CSV", initialdir=config.DATA_DIR,
                                          filetypes=[("Mission CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.load_csv(path)

    def load_csv(self, path: str | Path) -> None:
        """Show ReplayEngine's report and preview, including rejected row reasons."""
        try:
            report = self.app.controller.replay.load_csv(path)
        except ReplayDataError as exc:
            self._csv_ready = False
            self.report_card.border_color = COLORS["red"]
            self.report_card._draw()
            self.report.configure(text="CSV VALIDATION FAILED", fg=COLORS["red"])
            self.errors.configure(text=str(exc))
            self.source.configure(text=str(Path(path).name))
            self.preview.set_rows([])
            self._sync_replay()
            return
        self._csv_ready = True
        self.report_card.border_color = COLORS["green"] if not report.invalid_rows else COLORS["amber"]
        self.report_card._draw()
        self.report.configure(text=(f"{report.valid_rows} valid rows  ·  {report.invalid_rows} invalid rows  ·  "
                                    f"{format_met(report.duration)} duration  ·  {len(report.pass_windows)} pass windows"),
                              fg=COLORS["text"])
        self.errors.configure(text="\n".join(report.errors[:8]))
        self.source.configure(text=f"Loaded {Path(path).name}")
        self.preview.set_rows(self.app.controller.replay.preview().fillna("").to_dict("records"))
        self.progress.set(0)
        self.progress_text.configure(text=f"row 0/{report.valid_rows} · 00:00:00 / {format_met(report.duration)}")
        self._sync_replay()
        self.app.notify(f"{Path(path).name}: {report.valid_rows} valid rows",
                        "success" if not report.invalid_rows else "warning")

    def _start_replay(self) -> None:
        ctl = self.app.controller
        if not self._csv_ready:
            self.app.notify("Import a valid CSV first", "warning")
            return
        if ctl.mission_active and ctl.mode is MissionMode.LIVE:
            if not self.app.confirm("Start replay", "End the live mission and start replay?"):
                return
        try:
            ctl.start_replay_mission()
            self._mission_id = None
            self.mission_var.set("Current mission")
            self.app.notify(f"Replay started: {ctl.replay.source_name}", "success")
        except (ValueError, RuntimeError) as exc:
            self.app.notify(str(exc), "critical")
        self._sync_replay()

    def _toggle_pause(self) -> None:
        ctl = self.app.controller
        if ctl.paused:
            ctl.resume_replay()
        else:
            ctl.pause_replay()
        self._sync_replay()

    def _reset_replay(self) -> None:
        controller = self.app.controller
        if controller.mission_active and controller.mode is MissionMode.LIVE:
            controller.replay.reset()
        else:
            controller.reset_replay()
        self.progress.set(0)
        report = self.app.controller.replay.report
        self.progress_text.configure(text=f"row 0/{report.valid_rows if report else 0} · 00:00:00 / {format_met(report.duration) if report else '00:00:00'}")
        self._sync_replay()

    def _set_speed(self, label: str) -> None:
        try:
            self.app.controller.set_replay_speed(float(label[:-1]))
        except ValueError as exc:
            self.app.notify(str(exc), "critical")

    def _sync_replay(self) -> None:
        ctl = self.app.controller
        playing = ctl.mission_active and ctl.mode is MissionMode.REPLAY
        self.start_button.set_enabled(self._csv_ready and not playing)
        self.pause_button.set_enabled(playing)
        self.pause_button.set_text("RESUME" if ctl.paused else "PAUSE")
        self.reset_button.set_enabled(self._csv_ready)

    def _refresh_missions(self) -> None:
        previous = self.mission_var.get()
        mapping: dict[str, int | None] = {"Current mission": self.app.controller.mission_id}
        for mission in self.app.db.get_missions():
            label = f"{mission['mission_code']} · {mission['mode']} · {str(mission['started_at'])[:16].replace('T', ' ')}"
            mapping[label] = mission["mission_id"]
        self._mission_labels = mapping
        self.mission_choice.configure(values=list(mapping))
        if self._mission_id is not None:
            previous = next((label for label, mid in mapping.items()
                             if mid == self._mission_id and label != "Current mission"), previous)
        self.mission_var.set(previous if previous in mapping else "Current mission")

    def _choose_mission(self) -> None:
        self._mission_id = None if self.mission_var.get() == "Current mission" else self._mission_labels.get(self.mission_var.get())
        self.refresh_analytics()

    def refresh_analytics(self) -> None:
        """Read saved rows only on demand or at a five-second live cadence."""
        self._refresh_missions()
        mission_id = self._mission_id or self.app.controller.mission_id
        if mission_id is None:
            self._data, self._summary = None, {}
        else:
            try:
                self._data = self.app.analytics.load(mission_id)
                self._summary = self.app.analytics.summary(self._data)
            except Exception as exc:
                LOG.exception("Analytics read failed")
                self.app.notify(f"Analytics unavailable: {exc}", "critical")
                return
        self._last_refresh = time.monotonic()
        if self._section == "Analytics":
            for key, card in self.metrics.items():
                value = self._summary.get(key)
                card.update(round(value, 1) if isinstance(value, float) else value if value is not None else "—",
                            subtitle="From SQLite")
            self._render_chart()
        elif self._section == "Summary":
            self._render_summary()

    def _render_chart(self) -> None:
        if self._section != "Analytics":
            return
        if self._data is None:
            self.chart.render(lambda fig: fig.text(.5, .5, "No mission selected", ha="center",
                                                   va="center", color=COLORS["text_2"]))
        else:
            builder = getattr(self.app.analytics, CHARTS[self.chart_choice.selected])
            self.chart.render(lambda fig: builder(fig, self._data))
            fig = self.chart.figure
            name = self.chart_choice.selected
            if name == "Timeline":
                fig.subplots_adjust(left=.08, right=.97, bottom=.14, top=.96, hspace=.20)
            elif name == "Packet outcomes":
                fig.axes[0].tick_params(axis="x", labelrotation=0)
                fig.axes[0].set_xlabel("")
                fig.subplots_adjust(left=.10, right=.97, bottom=.15, top=.96)
            elif name == "Mode performance":
                fig.axes[0].set_xlabel("")
                fig.axes[0].set_ylabel("Average score")
                fig.subplots_adjust(left=.10, right=.97, bottom=.13, top=.96)
            elif name == "Correlation":
                labels = ("Battery", "Temp", "Signal", "Power", "Loss")
                if len(self._data.telemetry) >= 2:
                    for axis in ("x", "y"):
                        getattr(fig.axes[0], f"set_{axis}ticks")(
                            [index + .5 for index in range(5)], labels=labels, rotation=0, fontsize=8)
                fig.subplots_adjust(left=.15, right=.91, bottom=.18, top=.96)
            elif name == "Incidents":
                ax = fig.axes[0]
                short = {"COMM_FAILURE": "Comm fail", "CORRUPTED_PACKET": "Corrupted",
                         "PACKET_BURST": "Burst", "SIGNAL_LOSS": "Signal loss",
                         "THERMAL_ALERT": "Thermal", "SAFE_MODE": "Safe mode"}
                names = [short.get(t.get_text(), t.get_text().replace("_", " ").title())
                         for t in ax.get_xticklabels()]
                ax.set_xticks(ax.get_xticks(), labels=names, rotation=25, ha="right", fontsize=8)
                fig.subplots_adjust(left=.10, right=.97, bottom=.29, top=.96)
            for ax in fig.axes:
                legend = ax.get_legend()
                if legend:
                    legend.get_frame().set_facecolor(COLORS["card"])
                    legend.get_frame().set_edgecolor(COLORS["border"])
                    legend.get_frame().set_alpha(.9)
                    if legend.get_title():
                        legend.get_title().set_color(COLORS["text_2"])
                    for label in legend.get_texts():
                        label.set_fontsize(8)
                        label.set_color(COLORS["text_2"])
            self.chart.canvas.draw_idle()

    def _render_summary(self) -> None:
        data = self._summary
        self.summary_title.configure(text=f"MISSION SUMMARY  ·  {data.get('mission_code', 'No mission selected')}")
        groups = {
            "Mission": (("Code", "mission_code"), ("Mode", "mode"), ("Duration", "duration")),
            "Packets": (("Generated", "packets_generated"), ("Transmitted", "packets_transmitted"),
                        ("Failed", "packets_failed"), ("Deferred", "packets_deferred"),
                        ("Corrupted", "packets_corrupted"), ("Dropped", "packets_dropped"),
                        ("Attempts", "attempts"), ("Success", "success_rate")),
            "Telemetry": (("Avg link", "avg_signal"), ("Avg battery", "avg_battery"),
                          ("Min battery", "min_battery"), ("Peak temp", "peak_temperature"),
                          ("Avg power", "avg_power_draw"), ("Battery std dev", "battery_std"),
                          ("Signal std dev", "signal_std")),
            "Events": (("Safe mode", "safe_mode_activations"), ("Comm failures", "communication_failures"),
                       ("Thermal alerts", "thermal_alerts"), ("Low power", "low_power_events"),
                       ("Incidents", "incident_count")),
        }
        units = {"success_rate": "%", "avg_signal": "%", "avg_battery": "%",
                 "min_battery": "%", "peak_temperature": " °C", "avg_power_draw": " W",
                 "battery_std": "%", "signal_std": "%"}
        for group, entries in groups.items():
            for label, key in entries:
                value = data.get(key, "—")
                if isinstance(value, float):
                    value = f"{value:.1f}{units.get(key, '')}"
                self.facts[group].set(label, value)
        generated, sent = data.get("count_by_type", {}), data.get("sent_by_type", {})
        for kind in ("TTC", "HOUSEKEEPING", "SSTV", "M17", "CODEC2"):
            name = "TT&C" if kind == "TTC" else "Codec2" if kind == "CODEC2" else kind.title()
            self.facts["By type"].set(name, f"{sent.get(kind, 0)} sent / {generated.get(kind, 0)} generated")

    def _export(self, table: str) -> Path | None:
        mission_id = self._mission_id or self.app.controller.mission_id
        if mission_id is None:
            self.app.notify("Select a mission first", "warning")
            return None
        try:
            path = self.app.analytics.export_table(mission_id, table)
            self.app.notify(f"Saved {path.name}", "success")
            return path
        except Exception as exc:
            LOG.exception("Export failed")
            self.app.notify(f"Export failed: {exc}", "critical")
            return None

    def _save_summary(self) -> Path | None:
        mission_id = self._mission_id or self.app.controller.mission_id
        if mission_id is None:
            self.app.notify("Select a mission first", "warning")
            return None
        try:
            path = self.app.analytics.save_summary(mission_id)
            self.app.notify(f"Saved {path.name}", "success")
            return path
        except Exception as exc:
            LOG.exception("Summary export failed")
            self.app.notify(f"Summary failed: {exc}", "critical")
            return None

    def _open_exports(self) -> None:
        try:
            config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(config.EXPORTS_DIR)
        except (OSError, AttributeError) as exc:
            self.app.notify(f"Cannot open exports folder: {exc}", "critical")

    def show_summary(self, mission_id: int) -> None:
        """Select a completed replay and reveal its summary."""
        self._mission_id = mission_id
        self.sections.set("Summary")
        if self.visible:
            self.refresh_analytics()

    def on_show(self) -> None:
        super().on_show()
        self._refresh_missions()
        if self._section != "Replay":
            self.refresh_analytics()
        self._sync_replay()

    def on_hide(self) -> None:
        super().on_hide()

    def handle_event(self, event) -> None:
        """The shell applies UIState first; chart redraws stay on Tk's thread."""
        kind = getattr(event.type, "value", event.type)
        if kind == "REPLAY_PROGRESS" and self.visible:
            report = self.app.controller.replay.report
            progress = event.data
            self.progress.set(float(progress.get("fraction", 0)))
            self.progress_text.configure(
                text=f"row {progress.get('index', 0)}/{progress.get('total', 0)} · "
                     f"{format_met(progress.get('replay_time', 0))} / "
                     f"{format_met(report.duration if report else 0)}")
        elif kind in ("MISSION_STARTED", "MISSION_ENDED"):
            if self.visible:
                self._sync_replay()
                self._refresh_missions()
                if self._section != "Replay":
                    self.refresh_analytics()
        elif kind == "TELEMETRY_UPDATE" and self.visible and self._section != "Replay":
            if self._mission_id is None and time.monotonic() - self._last_refresh >= 5:
                self.refresh_analytics()
