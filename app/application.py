"""One persistent Tk shell for live and replay mission pages."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox

from app import config
from app.analytics.analytics_engine import AnalyticsEngine
from app.core.event_bus import EventBus, EventType
from app.core.mission_controller import MissionController
from app.database.database_manager import DatabaseManager
from app.exceptions import DatabaseOperationError
from app.utils.asset_factory import ensure_sstv_image
from app.ui.about_dialog import show_about
from app.ui.components import Card, ModernButton, SidebarButton, StatusBadge
from app.ui.icons import draw_logo
from app.ui.landing_page import LandingPage
from app.ui.theme import COLORS, FONTS, configure_ttk, init_theme, px, status_kind
from app.ui.ui_state import UIState
from app.ui.overview_page import OverviewPage
from app.ui.telemetry_page import TelemetryPage
from app.ui.router_page import RouterPage
from app.ui.communications_page import CommunicationsPage
from app.ui.incidents_page import IncidentsPage
from app.ui.analytics_page import AnalyticsPage
from app.ui.archive_page import ArchivePage

LOG = logging.getLogger(__name__)
PAGES = (
    ("overview", "Overview", "overview", "Mission Control Overview", OverviewPage),
    ("telemetry", "Telemetry", "telemetry", "Live Telemetry", TelemetryPage),
    ("router", "Autonomous Router", "router", "Autonomous Router", RouterPage),
    ("communications", "Communications", "communications", "Communications", CommunicationsPage),
    ("incidents", "Incidents", "incidents", "Incident Simulator", IncidentsPage),
    ("analytics", "Analytics & Replay", "analytics", "Mission Analytics & Replay", AnalyticsPage),
    ("archive", "Archive", "archive", "Mission Archive", ArchivePage),
)


class MissionControlApp(tk.Tk):
    """Own the app lifecycle, shared services, persistent shell, and event pump."""

    def __init__(self) -> None:
        super().__init__()
        self.title(config.APP_TITLE)
        init_theme(self)
        configure_ttk(self)
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(px(1440), screen_w-px(80)), min(px(900), screen_h-px(100))
        self.geometry(f"{width}x{height}+{(screen_w-width)//2}+{(screen_h-height)//2}")
        self.minsize(min(px(1200), screen_w), min(px(700), screen_h))
        self.bus = EventBus()
        try:
            self.db = DatabaseManager(config.DB_PATH)
        except DatabaseOperationError:
            LOG.exception("Persistent database unavailable")
            messagebox.showerror("Database unavailable", "Mission data will be kept in memory for this session.")
            self.db = DatabaseManager(":memory:")
        self.controller = MissionController(self.db, self.bus)
        self.analytics = AnalyticsEngine(self.db)
        self.ui_state = UIState()
        self.sstv_image = ensure_sstv_image(config.SSTV_IMAGE_PATH)
        self.pages: dict[str, object] = {}
        self.nav_buttons: dict[str, SidebarButton] = {}
        self.current_page: str | None = None
        self._shell_ready = False
        self._closing = False
        self._poll_job: str | None = None
        self._clock_job: str | None = None
        self._toasts: list[tk.Frame] = []
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.landing = LandingPage(self, on_enter=self.enter_mission_control, init_steps=[
            ("INITIALIZING TELEMETRY BUS...", self._build_shell),
            ("POWER SYSTEM ONLINE", lambda: self._build_pages("overview", "telemetry")),
            ("RF STACK READY", lambda: self._build_pages("router", "communications")),
            ("ROUTING ENGINE READY", lambda: self._build_pages("incidents", "analytics")),
            ("GROUND STATION LINK READY", lambda: self._build_pages("archive",)),
        ])
        self.landing.grid(row=0, column=0, sticky="nsew")
        self.landing.start()
        for index, (key, *_rest) in enumerate(PAGES, 1):
            self.bind_all(f"<Control-Key-{index}>", lambda _e, page=key: self.show_page(page), add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_events()
        self._update_clock()

    def _build_shell(self) -> None:
        if self._shell_ready:
            return
        self.shell = tk.Frame(self, bg=COLORS["bg"])
        self.shell.grid(row=0, column=0, sticky="nsew")
        self.shell.grid_remove()
        self.shell.grid_rowconfigure(0, weight=1)
        self.shell.grid_columnconfigure(1, weight=1)
        sidebar = tk.Frame(self.shell, bg=COLORS["sidebar"], width=px(220))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)
        tk.Frame(sidebar, width=px(1), bg=COLORS["border"]).place(relx=1, rely=0, relheight=1, anchor="ne")
        brand = tk.Frame(sidebar, bg=COLORS["sidebar"])
        brand.grid(row=0, column=0, sticky="ew", padx=px(15), pady=(px(21), px(27)))
        logo = tk.Canvas(brand, width=px(37), height=px(37), bg=COLORS["sidebar"], highlightthickness=0)
        logo.pack(side="left", padx=(0, px(8)))
        draw_logo(logo, px(18), px(18), px(34))
        name = tk.Frame(brand, bg=COLORS["sidebar"])
        name.pack(side="left")
        tk.Label(name, text="SomaiyaSat", bg=COLORS["sidebar"], fg=COLORS["text"], font=FONTS["h2"]).pack(anchor="w")
        tk.Label(name, text="MISSION CONTROL", bg=COLORS["sidebar"], fg=COLORS["cyan"], font=FONTS["caption"]).pack(anchor="w")
        nav = tk.Frame(sidebar, bg=COLORS["sidebar"])
        nav.grid(row=1, column=0, sticky="ew", padx=px(8))
        for key, label, icon, _, _ in PAGES:
            button = SidebarButton(nav, label, icon, command=lambda k=key: self.show_page(k))
            button.pack(fill="x", pady=px(2))
            self.nav_buttons[key] = button
        foot = tk.Frame(sidebar, bg=COLORS["sidebar"])
        foot.grid(row=3, column=0, sticky="ew", padx=px(11), pady=px(15))
        mission_card = Card(foot, padding=px(12), bg=COLORS["surface"])
        mission_card.pack(fill="x")
        self.side_mode = StatusBadge(mission_card.body, "STANDBY", bg=COLORS["surface"])
        self.side_mode.pack(anchor="w")
        self.side_code = tk.Label(mission_card.body, text="No mission active", bg=COLORS["surface"], fg=COLORS["text_2"], font=FONTS["small"], anchor="w")
        self.side_code.pack(fill="x", pady=(px(8), px(9)))
        self.mission_button = ModernButton(mission_card.body, "New Live Mission", command=self._toggle_mission, height=px(31), bg=COLORS["surface"])
        self.mission_button.pack(fill="x")
        ModernButton(foot, "About", command=lambda: show_about(self), kind="ghost", bg=COLORS["sidebar"]).pack(fill="x", pady=(px(9), 0))
        main = tk.Frame(self.shell, bg=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        top = tk.Frame(main, bg=COLORS["surface"], height=px(64))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        self.page_title = tk.Label(top, text="Mission Control Overview", bg=COLORS["surface"], fg=COLORS["text"], font=FONTS["h2"])
        self.page_title.pack(side="left", padx=px(24))
        right = tk.Frame(top, bg=COLORS["surface"])
        right.pack(side="right", padx=px(18))
        self.link_badge = StatusBadge(right, "NO PASS", bg=COLORS["surface"])
        self.link_badge.pack(side="right", padx=(px(6), 0))
        self.state_badge = StatusBadge(right, "NOMINAL", bg=COLORS["surface"])
        self.state_badge.pack(side="right", padx=(px(6), 0))
        self.mode_badge = StatusBadge(right, "STANDBY", bg=COLORS["surface"])
        self.mode_badge.pack(side="right", padx=(px(6), 0))
        self.met_label = tk.Label(right, text="MET 00:00:00", bg=COLORS["surface"], fg=COLORS["text"], font=FONTS["mono"])
        self.met_label.pack(side="right", padx=(px(9), px(12)))
        self.code_label = tk.Label(right, text="—", bg=COLORS["card_hi"], fg=COLORS["text_2"], font=FONTS["mono"], padx=px(9), pady=px(5))
        self.code_label.pack(side="right")
        self.host = tk.Frame(main, bg=COLORS["bg"])
        self.host.grid(row=1, column=0, sticky="nsew")
        self.host.grid_rowconfigure(0, weight=1)
        self.host.grid_columnconfigure(0, weight=1)
        self.toast_host = tk.Frame(main, bg=COLORS["bg"])
        self.toast_host.place(relx=1, y=px(69), anchor="ne")
        self._shell_ready = True

    def _build_pages(self, *keys: str) -> None:
        self._build_shell()
        for key in keys:
            if key in self.pages:
                continue
            page_class = next(item[4] for item in PAGES if item[0] == key)
            page = page_class(self.host, self)
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()
            self.pages[key] = page

    def enter_mission_control(self) -> None:
        """Reveal the completed shell and start a persisted live mission."""
        if self._closing or not self.landing.winfo_exists():
            return
        self._build_pages(*(item[0] for item in PAGES))
        self.landing.stop()
        self.landing.destroy()
        self.shell.grid()
        self.controller.start_live_mission()
        self.show_page("overview")

    def show_page(self, key: str) -> None:
        """Switch a single built page using its shared lifecycle hooks."""
        if key not in self.pages or not self._shell_ready or not self.shell.winfo_ismapped():
            return
        if self.current_page == key:
            return
        if self.current_page:
            old = self.pages[self.current_page]
            old.on_hide()
            old.grid_remove()
        page = self.pages[key]
        page.grid()
        page.tkraise()
        page.on_show()
        self.current_page = key
        for nav_key, button in self.nav_buttons.items():
            button.set_active(nav_key == key)
        self.page_title.configure(text=next(item[3] for item in PAGES if item[0] == key))

    def notify(self, message: str, kind: str = "info") -> None:
        """Show a short stack of transient shell messages."""
        if not self._shell_ready or self._closing:
            return
        toast = Card(self.toast_host, bg=COLORS["card_hi"], padding=px(11))
        accent = {"success": COLORS["green"], "warning": COLORS["amber"], "critical": COLORS["red"]}.get(kind, COLORS["cyan"])
        tk.Label(toast.body, text=message, fg=accent, bg=COLORS["card_hi"], font=FONTS["body_bold"], wraplength=px(230), justify="left").pack()
        toast.pack(fill="x", pady=px(3))
        self._toasts.append(toast)
        if len(self._toasts) > 3:
            self._toasts.pop(0).destroy()
        def dismiss() -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)
                toast.destroy()
        toast.after(3500, dismiss)
        self.toast_host.lift()

    def confirm(self, title: str, message: str) -> bool:
        """Ask before ending an active mission on window close."""
        return bool(messagebox.askyesno(title, message, parent=self))

    def _toggle_mission(self) -> None:
        if self.controller.mission_active:
            self.controller.stop_mission()
        else:
            self.controller.start_live_mission()

    def _update_shell(self) -> None:
        if not self._shell_ready:
            return
        mode = self.controller.mode.value if self.controller.mode else "STANDBY"
        if not self.controller.mission_active:
            mode = "STANDBY"
        code = self.controller.mission_code or "No mission active"
        self.side_mode.set(mode)
        self.mode_badge.set(f"{mode} ×{self.controller.replay.speed:g}" if mode == "REPLAY" else mode)
        self.side_code.configure(text=code)
        self.code_label.configure(text=code if self.controller.mission_code else "—")
        self.mission_button.set_text("End Mission" if self.controller.mission_active else "New Live Mission")
        self.state_badge.set(self.ui_state.state)
        self.link_badge.set((self.ui_state.snapshot or {}).get("comm_state", "NO PASS"))

    def _handle_shell_event(self, event) -> None:
        kind = getattr(event.type, "value", event.type)
        if kind in (EventType.MISSION_STARTED.value, EventType.MISSION_ENDED.value):
            self._update_shell()
            if kind == EventType.MISSION_STARTED.value:
                self.notify(f"Mission {event.data.get('mission_code', '')} started", "success")
            elif event.data.get("mode") == "REPLAY":
                self.notify("Replay complete — summary ready", "success")
                summary = getattr(self.pages.get("analytics"), "show_summary", None)
                if callable(summary):
                    summary(event.data.get("mission_id"))
            else:
                self.notify("Mission saved to archive", "success")
        elif kind == EventType.STATE_CHANGED.value:
            state = str(event.data.get("new", "NOMINAL"))
            self.state_badge.set(state)
            self.notify(f"State → {state.replace('_', ' ')}", "critical" if status_kind(state) == "critical" else "success" if state == "NOMINAL" else "warning")
        elif kind == EventType.TELEMETRY_UPDATE.value:
            self.link_badge.set((self.ui_state.snapshot or {}).get("comm_state", "NO PASS"))

    def _poll_events(self) -> None:
        # Workers publish plain data only. Draining their queue inside Tk's after loop
        # keeps every widget mutation on the main thread, including hidden pages.
        if self._closing:
            return
        for event in self.bus.drain(config.UI_MAX_EVENTS_PER_POLL):
            self.ui_state.apply(event)
            try:
                self._handle_shell_event(event)
            except Exception:
                LOG.exception("Shell event handler failed")
            for key, page in tuple(self.pages.items()):
                try:
                    page.handle_event(event)
                except Exception:
                    LOG.exception("Page %s event handler failed", key)
        self._poll_job = self.after(config.UI_POLL_INTERVAL_MS, self._poll_events)

    def _update_clock(self) -> None:
        if self._closing:
            return
        if self._shell_ready:
            self.met_label.configure(text=f"MET {self.controller.met_string()}")
        self._clock_job = self.after(250, self._update_clock)

    def _on_close(self) -> None:
        """Stop Tk timers, join mission workers, then release SQLite."""
        if self._closing:
            return
        if self.controller.mission_active and not self.confirm("Exit Mission Control?", "The active mission will be ended and saved to the archive."):
            return
        self._closing = True
        LOG.info("Closing Mission Control")
        for job in (self._poll_job, self._clock_job):
            if job:
                self.after_cancel(job)
        if self.current_page:
            self.pages[self.current_page].on_hide()
        LOG.info("Stopping mission workers")
        self.controller.shutdown()
        LOG.info("Closing database")
        self.db.close()
        self.destroy()
        LOG.info("Mission Control closed")
