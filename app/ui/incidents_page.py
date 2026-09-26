"""Operator fault controls and live autonomous response."""
from __future__ import annotations

from collections import deque
import tkinter as tk

from app import config
from app.models.enums import IncidentType, MissionMode, MissionState
from app.models.mission_state import STATE_DESCRIPTIONS
from .base_page import BasePage
from .components import Card, DataTable, KeyValueList, ModernButton, ScrollableFrame, StatusBadge, add_tooltip
from .theme import COLORS, FONTS, px

ACTIONS = (
    (IncidentType.BATTERY_DRAIN, "BATTERY DRAIN", "Drains battery toward 19%; triggers LOW POWER.", "warning"),
    (IncidentType.THERMAL_SPIKE, "THERMAL SPIKE", "Heats the bus in steps; triggers THERMAL ALERT.", "warning"),
    (IncidentType.SIGNAL_LOSS, "SIGNAL LOSS", "Attenuates the ground link for 20 seconds.", "warning"),
    (IncidentType.COMM_FAILURE, "COMMUNICATION FAILURE", "Drops the RF link and tests retry safety.", "critical"),
    (IncidentType.CORRUPTED_PACKET, "CORRUPTED PACKET", "Quarantines a damaged packet.", "critical"),
    (IncidentType.PACKET_BURST, "PACKET BURST", "Adds ten packets to stress the router.", "warning"),
    (IncidentType.FORCE_SAFE_MODE, "FORCE SAFE MODE", "Permits critical control traffic only.", "critical"),
    (IncidentType.RESTORE_NOMINAL, "RESTORE NOMINAL CONDITIONS", "Clears injected faults and restores sensors.", "success"),
)
ACTIONS_BY_STATE = {
    "NOMINAL": ("All communication modes available", "Router scores the next safe packet"),
    "DEGRADED_LINK": ("Marginal packets held", "Router waits for stronger signal"),
    "LOW_POWER": ("SSTV and M17 suspended", "Lower-energy modes prioritized"),
    "THERMAL_ALERT": ("SSTV, M17 and Codec2 suspended", "Only essential TT&C / housekeeping transmitted", "Transmitter load reduced"),
    "SAFE_MODE": ("Only critical TT&C traffic permitted", "Payload downlinks suspended", "Power and temperature monitored"),
    "COMMUNICATION_LOSS": ("All transmissions suspended", "Packets queued for link recovery"),
}


class IncidentsPage(BasePage):
    """Show operator actions, safety restrictions and incident history."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.build_header("Incident Simulator", "Inject a fault and observe the autonomous safety response")
        self.transitions: deque[str] = deque(maxlen=6)
        self.buttons: dict[IncidentType, ModernButton] = {}
        self.cards: dict[IncidentType, tk.Frame] = {}
        layout = tk.Frame(self, bg=COLORS["bg"])
        layout.pack(fill="both", expand=True, padx=px(17), pady=(0, px(14)))
        layout.grid_columnconfigure(0, weight=3)
        layout.grid_columnconfigure(1, weight=2)
        layout.grid_rowconfigure(0, weight=1)
        layout.grid_rowconfigure(1, minsize=px(128))
        faults = Card(layout, title="Fault injection", padding=px(12))
        faults.grid(row=0, column=0, sticky="nsew", padx=(0, px(12)))
        self.fault_hint = tk.Label(faults.header_right, text="", bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"])
        self.fault_hint.pack(side="right")
        rows = ScrollableFrame(faults.body, bg=COLORS["card"])
        rows.pack(fill="both", expand=True)
        self._descriptions: list[tk.Label] = []
        for index, (kind, title, description, severity) in enumerate(ACTIONS):
            accent = COLORS["green"] if severity == "success" else COLORS["red"] if severity == "critical" else COLORS["amber"]
            if index:
                tk.Frame(rows.body, bg=COLORS["border"], height=px(1)).pack(fill="x")
            row = tk.Frame(rows.body, bg=COLORS["card"])
            row.pack(fill="x", pady=px(2))
            tk.Frame(row, bg=accent, width=px(3)).pack(side="left", fill="y", padx=(0, px(11)))
            button = ModernButton(row, "Restore" if severity == "success" else "Inject",
                                  command=lambda selected=kind: self._inject(selected),
                                  kind="success" if severity == "success" else "danger",
                                  width=px(92), height=px(30), bg=COLORS["card"])
            button.pack(side="right", padx=(px(10), px(4)))
            text = tk.Frame(row, bg=COLORS["card"])
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=title.capitalize(), bg=COLORS["card"], fg=COLORS["text"],
                     font=FONTS["body_bold"], anchor="w").pack(fill="x")
            label = tk.Label(text, text=description, bg=COLORS["card"], fg=COLORS["text_2"],
                             font=FONTS["small"], anchor="w", justify="left", wraplength=px(360))
            label.pack(fill="x")
            self._descriptions.append(label)
            self.cards[kind] = row
            self.buttons[kind] = button
            if kind in (IncidentType.BATTERY_DRAIN, IncidentType.THERMAL_SPIKE):
                add_tooltip(button, "Unavailable in replay: battery and temperature come from the CSV.")
        rows.body.bind("<Configure>", lambda e: [d.configure(wraplength=max(px(160), e.width-px(150))) for d in self._descriptions], add="+")
        right = ScrollableFrame(layout)
        right.grid(row=0, column=1, sticky="nsew")
        response = Card(right.body, title="Autonomous response", padding=px(14))
        response.pack(fill="both", expand=True)
        self.badge = StatusBadge(response.body, "NOMINAL", bg=COLORS["card"])
        self.badge.pack(anchor="w", pady=(0, px(7)))
        self.description = tk.Label(response.body, bg=COLORS["card"], fg=COLORS["text_2"],
                                    font=FONTS["body"], justify="left", anchor="w", wraplength=px(315))
        self.description.pack(fill="x", pady=(0, px(9)))
        self.readings = KeyValueList(response.body, [("Temperature", "—"), ("Battery", "—"), ("Signal", "—")])
        self.readings.pack(fill="x")
        self.allowed = self._section(response.body, "ALLOWED MODES")
        self.suspended = self._section(response.body, "SUSPENDED MODES")
        self.rules = self._section(response.body, "ACTIVE SAFETY RULES")
        self.hold = self._section(response.body, "ROUTER HOLD")
        self.system_actions = self._section(response.body, "WHAT THE SYSTEM IS DOING")
        self.timeline = self._section(response.body, "STATE TRANSITIONS")
        history = Card(layout, title="Incident history", padding=px(11))
        history.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(px(10), 0))
        history.configure(height=px(128))
        history.pack_propagate(False)
        self.table = DataTable(history.body, [
            ("met", "MET", 65, "w"), ("incident_type", "TYPE", 135, "w"),
            ("severity", "SEVERITY", 80, "w"), ("description", "DESCRIPTION", 350, "w"),
            ("resolved", "RESOLVED", 75, "center")])
        self.table.pack(fill="both", expand=True)

    @staticmethod
    def _section(parent: tk.Misc, title: str) -> tk.Frame:
        tk.Label(parent, text=title, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["caption"], anchor="w").pack(fill="x", pady=(px(10), px(3)))
        frame = tk.Frame(parent, bg=COLORS["card"])
        frame.pack(fill="x")
        return frame

    @staticmethod
    def _lines(frame: tk.Frame, values, color: str = COLORS["text_2"]) -> None:
        for widget in frame.winfo_children():
            widget.destroy()
        for value in values or ("None",):
            tk.Label(frame, text=value, bg=COLORS["card"], fg=color, font=FONTS["small"],
                     wraplength=px(320), justify="left", anchor="w").pack(fill="x", pady=px(1))

    def _inject(self, kind: IncidentType) -> None:
        if not self.app.controller.mission_active:
            return
        message = self.app.controller.inject_incident(kind)
        severity = next(item[3] for item in ACTIONS if item[0] is kind)
        self.app.notify(message, "success" if severity == "success" else severity)
        self._flash(self.cards[kind], COLORS["card_hi"])
        self.after(900, lambda: self._flash(self.cards[kind], COLORS["card"]))

    @staticmethod
    def _flash(row: tk.Frame, color: str) -> None:
        if not row.winfo_exists():
            return
        stack = [row]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, (tk.Label, tk.Frame)) and widget.cget("bg") in (COLORS["card"], COLORS["card_hi"]):
                widget.configure(bg=color)
            elif isinstance(widget, ModernButton):
                widget.parent_bg = color
                widget.configure(bg=color)
                widget._draw()

    def _refresh(self) -> None:
        ui = self.app.ui_state
        live = self.app.controller.mission_active
        replay = self.app.controller.mode is MissionMode.REPLAY
        for kind, button in self.buttons.items():
            button.set_enabled(live and not (replay and kind in (IncidentType.BATTERY_DRAIN, IncidentType.THERMAL_SPIKE)))
        self.fault_hint.configure(text="" if live else "Start a mission to inject faults")
        try:
            state = MissionState(str(ui.state or "NOMINAL"))
        except ValueError:
            state = MissionState.NOMINAL
        self.badge.set(state.value, state.severity)
        self.description.configure(text=STATE_DESCRIPTIONS[state])
        snapshot = ui.snapshot or {}
        for key, title, unit in (("temperature", "Temperature", "°C"), ("battery", "Battery", "%"), ("signal", "Signal", "%")):
            value = snapshot.get(key)
            self.readings.set(title, f"{value:.1f} {unit}" if isinstance(value, (int, float)) else "—")
        modes = ("TTC", "CODEC2", "M17", "SSTV")
        permitted = config.STATE_ALLOWED_MODES.get(state.value, set())
        self._lines(self.allowed, ("  ·  ".join(m for m in modes if m in permitted) or "None",), COLORS["green"])
        self._lines(self.suspended, ("  ·  ".join(m for m in modes if m not in permitted) or "None",), COLORS["amber"])
        self._lines(self.rules, ui.active_rules[:4] or ("No active restrictions",))
        self._lines(self.hold, (ui.hold_reason or "No router hold",))
        self._lines(self.system_actions, tuple("• " + item for item in ACTIONS_BY_STATE[state.value]))
        self._lines(self.timeline, tuple(self.transitions) or ("No transitions yet",))
        rows = [{**incident, "resolved": "✓" if incident.get("resolved") else "—"} for incident in ui.incidents]
        self.table.set_rows(rows, iid_key="incident_id", tag_key="severity")

    def on_show(self) -> None:
        super().on_show()
        self._refresh()

    def on_hide(self) -> None:
        super().on_hide()

    def handle_event(self, event) -> None:
        """The shell applies UIState first; widgets are updated only on Tk's thread."""
        kind = getattr(event.type, "value", event.type)
        if kind == "MISSION_STARTED":
            self.transitions.clear()
        elif kind == "STATE_CHANGED":
            self.transitions.appendleft(
                f"{self.app.ui_state.met}  {event.data.get('old', '—')} → {event.data.get('new', '—')}")
        if self.visible and kind in {"MISSION_STARTED", "MISSION_ENDED", "TELEMETRY_UPDATE",
                                     "QUEUE_UPDATE", "STATE_CHANGED", "INCIDENT_CREATED", "INCIDENT_RESOLVED"}:
            self._refresh()
