"""SQLite mission archive with search, filters, and per-table inspection."""
from __future__ import annotations

import logging
import tkinter as tk

from app.utils.helpers import format_met
from .base_page import BasePage
from .components import Card, DataTable, ModernButton, ScrollableFrame, SegmentedControl, StatusBadge
from .theme import COLORS, FONTS, px

LOG = logging.getLogger(__name__)
TABS = {"Telemetry": "telemetry", "Packets": "packets", "Decisions": "decisions",
        "Incidents": "incidents", "State transitions": "state_transitions"}
COLUMNS = {
    "telemetry": [("mission_time", "MET (S)", 90, "e"), ("battery", "BATTERY %", 90, "e"),
                  ("temperature", "TEMP °C", 90, "e"), ("signal", "SIGNAL %", 90, "e"),
                  ("power_draw", "POWER W", 90, "e"), ("packet_loss", "LOSS %", 90, "e"),
                  ("system_state", "STATE", 140, "w")],
    "packets": [("packet_id", "ID", 70, "e"), ("packet_type", "TYPE", 150, "w"),
                ("priority", "PRIORITY", 100, "w"), ("size_kb", "SIZE KB", 90, "e"),
                ("status", "STATUS", 110, "w"), ("mode", "MODE", 90, "w"),
                ("retry_count", "RETRIES", 75, "e"), ("corrupted", "CORRUPTED", 95, "center")],
    "decisions": [("mission_time", "MET (S)", 65, "e"), ("packet_id", "PACKET", 65, "e"),
                  ("selected_mode", "MODE", 70, "w"), ("total_score", "SCORE", 65, "e"),
                  ("signal", "SIGNAL %", 70, "e"), ("system_state", "STATE", 105, "w"),
                  ("reason", "REASON", 370, "w")],
    "incidents": [("mission_time", "MET (S)", 90, "e"), ("incident_type", "TYPE", 190, "w"),
                  ("severity", "SEVERITY", 110, "w"), ("description", "DESCRIPTION", 420, "w"),
                  ("resolved", "RESOLVED", 100, "center")],
    "state_transitions": [("mission_time", "MET (S)", 100, "e"), ("from_state", "FROM", 180, "w"),
                          ("to_state", "TO", 180, "w"), ("reason", "REASON", 440, "w")],
}


class ArchivePage(BasePage):
    """Load mission aggregates on show and child records only on selection."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.build_header("Mission Archive", "Search persisted missions and inspect their decision trail")
        self._mission_id: int | None = None
        self._tab = "Telemetry"
        self._search_job: str | None = None
        self._rows: list[dict] = []
        controls = tk.Frame(self, bg=COLORS["bg"])
        controls.pack(fill="x", padx=px(17), pady=(0, px(10)))
        tk.Label(controls, text="SEARCH", bg=COLORS["bg"], fg=COLORS["muted"],
                 font=FONTS["caption"]).pack(side="left", padx=(0, px(7)))
        self.search_var = tk.StringVar()
        self.search = tk.Entry(controls, textvariable=self.search_var, bg=COLORS["card_hi"],
                               fg=COLORS["text"], insertbackground=COLORS["text"],
                               font=FONTS["body"], relief="flat", width=26)
        self.search.pack(side="left", ipady=px(7), padx=(0, px(12)))
        self.search_var.trace_add("write", self._schedule_search)
        self.mode_filter = SegmentedControl(controls, ("All", "LIVE", "REPLAY"), command=lambda _: self.refresh())
        self.mode_filter.pack(side="left", padx=(0, px(10)))
        ModernButton(controls, "Refresh", command=self.refresh, bg=COLORS["bg"]).pack(side="left")
        self.count_label = tk.Label(controls, text="0 missions", bg=COLORS["bg"],
                                    fg=COLORS["text_2"], font=FONTS["small"])
        self.count_label.pack(side="right")
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True, padx=px(17), pady=(0, px(14)))
        content = self.scroller.body
        listing = Card(content, title="Missions", padding=px(11))
        listing.pack(fill="x", pady=(0, px(10)))
        listing.configure(height=px(265))
        listing.pack_propagate(False)
        self.missions = DataTable(listing.body, [
            ("mission_code", "MISSION", 160, "w"), ("mode", "MODE", 60, "w"),
            ("started_at", "STARTED", 140, "w"), ("duration", "DURATION", 70, "w"),
            ("packets", "PACKETS", 65, "e"), ("success", "SUCCESS %", 80, "e"),
            ("incidents", "INCIDENTS", 75, "e"), ("status", "STATUS", 85, "w")])
        self.missions.pack(fill="both", expand=True)
        self.missions.on_select(self._select_mission)
        detail = Card(content, title="Mission detail", padding=px(11))
        detail.pack(fill="x")
        detail.configure(height=px(400))
        detail.pack_propagate(False)
        heading = tk.Frame(detail.body, bg=COLORS["card"])
        heading.pack(fill="x", pady=(0, px(6)))
        self.detail_title = tk.Label(heading, text="Select a mission", bg=COLORS["card"],
                                     fg=COLORS["text"], font=FONTS["h2"])
        self.detail_title.pack(side="left")
        self.detail_mode = StatusBadge(heading, "—", kind="neutral", bg=COLORS["card"])
        self.detail_mode.pack(side="left", padx=px(9))
        ModernButton(heading, "Export CSV", command=self._export, bg=COLORS["card"]).pack(side="right")
        ModernButton(heading, "Open in analytics", command=self._analyze,
                     kind="primary", bg=COLORS["card"]).pack(side="right", padx=(0, px(7)))
        self.detail_dates = tk.Label(detail.body, text="", bg=COLORS["card"], fg=COLORS["text_2"],
                                      font=FONTS["small"], anchor="w")
        self.detail_dates.pack(fill="x", pady=(0, px(6)))
        tabs = tk.Frame(detail.body, bg=COLORS["card"])
        tabs.pack(fill="x", pady=(0, px(6)))
        self.tab_control = SegmentedControl(tabs, list(TABS), command=self._choose_tab)
        self.tab_control.pack(side="left")
        for button, width in zip(self.tab_control._buttons, (72, 63, 75, 70, 126)):
            button.configure(width=px(width))
        tk.Label(tabs, text="FILTER ROWS", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["caption"]).pack(side="left", padx=(px(12), px(6)))
        self.row_filter_var = tk.StringVar()
        self.row_filter = tk.Entry(tabs, textvariable=self.row_filter_var, bg=COLORS["card_hi"],
                                   fg=COLORS["text"], insertbackground=COLORS["text"],
                                   font=FONTS["small"], relief="flat", width=17)
        self.row_filter.pack(side="left", ipady=px(6))
        self.row_filter_var.trace_add("write", lambda *_: self._filter_rows())
        self.row_count = tk.Label(tabs, text="0 rows", bg=COLORS["card"],
                                  fg=COLORS["text_2"], font=FONTS["small"])
        self.row_count.pack(side="right")
        table_host = tk.Frame(detail.body, bg=COLORS["card"])
        table_host.pack(fill="both", expand=True)
        self.tables: dict[str, DataTable] = {}
        for tab, table in TABS.items():
            widget = DataTable(table_host, COLUMNS[table])
            widget.place(relwidth=1, relheight=1)
            self.tables[tab] = widget
            if tab == "Decisions":
                widget.on_select(lambda row: self.decision_reason.configure(text=str(row.get("reason", ""))))
        self.tables[self._tab].lift()
        self.decision_reason = tk.Label(detail.body, text="", bg=COLORS["card"],
                                        fg=COLORS["text_2"], font=FONTS["small"],
                                        anchor="w", justify="left", wraplength=px(800))
        self.decision_reason.pack(fill="x", pady=(px(4), 0))

    def _schedule_search(self, *_args) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
        # The Tk timer avoids one SQLite query for every keystroke.
        self._search_job = self.after(250, self.refresh)

    def refresh(self) -> None:
        """Query mission aggregates on demand and after lifecycle events."""
        self._search_job = None
        mode = None if self.mode_filter.selected == "All" else self.mode_filter.selected
        search = self.search_var.get().strip()
        try:
            missions = self.app.db.get_missions(search, mode)
            if search:
                # DatabaseManager searches code/name; include status without SQL in this page.
                status_matches = [row for row in self.app.db.get_missions("", mode)
                                  if search.casefold() in str(row.get("status", "")).casefold()]
                missions = sorted({row["mission_id"]: row for row in missions + status_matches}.values(),
                                  key=lambda row: row["mission_id"], reverse=True)
        except Exception as exc:
            LOG.exception("Archive query failed")
            self.app.notify(f"Archive unavailable: {exc}", "critical")
            return
        display = [{**row,
                    "started_at": str(row.get("started_at", "")).replace("T", " ")[:19],
                    "duration": format_met(row.get("duration_s") or 0),
                    "success": f"{row['success_rate']:.1f}" if row.get("success_rate") is not None else "—"}
                   for row in missions]
        self.missions.set_rows(display, iid_key="mission_id", tag_key="status")
        live = sum(row.get("mode") == "LIVE" for row in missions)
        replay = sum(row.get("mode") == "REPLAY" for row in missions)
        self.count_label.configure(text=f"{len(missions)} missions · {live} live · {replay} replay")
        chosen = next((row for row in missions if row["mission_id"] == self._mission_id), None)
        if chosen is None and missions:
            chosen = missions[0]
        if chosen:
            self._select_mission(chosen)
            self.missions.tree.selection_set(str(chosen["mission_id"]))
            self.after_idle(lambda: self.scroller.canvas.yview_moveto(0))
        else:
            self._mission_id = None
            self.detail_title.configure(text="Select a mission")
            self._rows = []
            self._filter_rows()

    def _select_mission(self, row: dict) -> None:
        mission_id = int(row["mission_id"])
        changed = mission_id != self._mission_id
        self._mission_id = mission_id
        if (str(mission_id) in self.missions.tree.get_children("")
                and self.missions.tree.selection() != (str(mission_id),)):
            self.missions.tree.selection_set(str(mission_id))
        self.detail_title.configure(text=str(row.get("mission_code", "")))
        self.detail_mode.set(str(row.get("mode", "—")))
        started = str(row.get("started_at", "")).replace("T", " ")[:16]
        ended = str(row.get("ended_at") or "Running").replace("T", " ")[:16]
        self.detail_dates.configure(text=f"{started} → {ended}   ·   {row.get('status', '—')}")
        if changed or not self._rows:
            self._load_tab()

    def _choose_tab(self, tab: str) -> None:
        self._tab = tab
        self.tables[tab].lift()
        self.decision_reason.configure(text="" if tab != "Decisions" else "Select a decision to read its full reason")
        self._load_tab()
        self.after(80, lambda: self.scroller.canvas.yview_moveto(1))

    def _load_tab(self) -> None:
        if self._mission_id is None:
            self._rows = []
        else:
            try:
                table = TABS[self._tab]
                rows = self.app.db.fetch_table(table, self._mission_id)
                # DatabaseManager orders ascending; slice from the end for the latest telemetry.
                self._rows = rows[-500:] if table == "telemetry" else rows
            except Exception as exc:
                LOG.exception("Archive detail query failed")
                self.app.notify(f"Could not load archive rows: {exc}", "critical")
                self._rows = []
        self._filter_rows()

    def _filter_rows(self) -> None:
        needle = self.row_filter_var.get().casefold().strip()
        rows = list(filter(lambda row: needle in " ".join(map(str, row.values())).casefold(), self._rows))
        if self._tab == "Telemetry":
            rows.reverse()
        if self._tab in ("Telemetry", "Decisions", "Incidents", "State transitions"):
            rows = [{**row, "mission_time": f"{float(row['mission_time']):.1f}"}
                    if row.get("mission_time") is not None else row for row in rows]
        if self._tab == "Decisions":
            rows = [{**row, "total_score": f"{float(row['total_score']):.1f}",
                     "signal": f"{float(row['signal']):.1f}"} for row in rows]
        if self._tab == "Incidents":
            rows = [{**row, "resolved": "✓" if row.get("resolved") else "—"} for row in rows]
        self.tables[self._tab].set_rows(rows, tag_key="severity" if self._tab == "Incidents" else
                                       "status" if self._tab == "Packets" else None)
        self.row_count.configure(text=f"{len(rows)} of {len(self._rows)} rows")

    def _analyze(self) -> None:
        if self._mission_id is not None:
            self.app.show_page("analytics")
            self.app.pages["analytics"].show_summary(self._mission_id)

    def _export(self) -> None:
        if self._mission_id is None:
            return
        table = TABS[self._tab]
        if table not in ("telemetry", "packets", "decisions"):
            self.app.notify("CSV export is available for telemetry, packets, and decisions", "warning")
            return
        try:
            path = self.app.analytics.export_table(self._mission_id, table)
            self.app.notify(f"Saved {path.name}", "success")
        except Exception as exc:
            LOG.exception("Archive export failed")
            self.app.notify(f"Export failed: {exc}", "critical")

    def on_show(self) -> None:
        super().on_show()
        self.refresh()

    def on_hide(self) -> None:
        super().on_hide()
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None

    def handle_event(self, event) -> None:
        """Refresh only on lifecycle events, after UIState is updated."""
        if self.visible and getattr(event.type, "value", event.type) in ("MISSION_STARTED", "MISSION_ENDED"):
            self.refresh()
