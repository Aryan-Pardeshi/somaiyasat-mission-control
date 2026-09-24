"""Transparent two-layer autonomous routing view for operator explanation."""
from __future__ import annotations

import tkinter as tk

from app import config
from app.utils.helpers import format_met
from .base_page import BasePage
from .components import Card, DataTable, KeyValueList, ScoreBar, StatusBadge
from .theme import COLORS, FONTS, px


class RouterPage(BasePage):
    """Show scored packets, safety restrictions, and persisted decision inputs."""

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        body = tk.Frame(self, bg=COLORS["bg"])
        body.grid(row=0, column=0, sticky="nsew", padx=px(17), pady=(px(17), px(8)))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        left = Card(body, title="PACKET QUEUE", padding=px(10))
        left.grid(row=0, column=0, sticky="nsew", padx=(0, px(7)))
        self.hold = tk.Label(left.body, text="Router awaiting telemetry", bg=COLORS["card_hi"], fg=COLORS["amber"], font=FONTS["small"], anchor="w", padx=px(8), pady=px(7))
        self.hold.pack(fill="x", pady=(0, px(8)))
        self.rules = tk.Label(left.body, text="Active safety rules: standard limits", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"], anchor="w", wraplength=px(500), justify="left")
        self.rules.pack(fill="x", pady=(0, px(8)))
        self.queue_table = DataTable(left.body, [
            ("id", "ID", 52, "w"), ("type", "TYPE", 92, "w"),
            ("priority", "PRIORITY", 78, "w"), ("size", "KB", 56, "e"),
            ("age", "AGE s", 50, "e"), ("required", "MIN SIG %", 72, "e"),
            ("energy", "ENERGY J", 72, "e"), ("score", "SCORE", 56, "e"),
            ("status", "STATUS", 104, "w"),
        ])
        self.queue_table.pack(fill="both", expand=True)
        self.queue_table.on_select(self._select_row)
        right = Card(body, title="SELECTED PACKET", padding=px(10))
        right.grid(row=0, column=1, sticky="nsew", padx=(px(7), 0))
        self.selected_badge = StatusBadge(right.header_right, "IDLE", bg=COLORS["card"])
        self.selected_badge.pack(side="right")
        self.selected_title = tk.Label(right.body, text="No packet selected", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["h1"], anchor="w")
        self.selected_title.pack(fill="x")
        self.selected_facts = KeyValueList(right.body, row_pady=0)
        self.selected_facts.pack(fill="x", pady=(px(2), px(1)))
        self.score_title = tk.Label(right.body, text="AUTONOMOUS SCORE  —", bg=COLORS["card"], fg=COLORS["cyan"], font=FONTS["h2"], anchor="w")
        self.score_title.pack(fill="x", pady=(px(2), 0))
        self.score_bars = ScoreBar(right.body, compact=True)
        self.score_bars.pack(fill="x", pady=(0, 0))
        tk.Label(right.body, text="WHY THIS DECISION?", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["caption"], anchor="w").pack(fill="x")
        self.reason = tk.Label(right.body, text="The router evaluates safety restrictions before selecting a packet.", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["small"], justify="left", anchor="w", wraplength=px(350))
        self.reason.pack(fill="x", pady=(px(4), px(8)))
        tk.Label(right.body, text="LAYER 1 — SAFETY RULES   /   LAYER 2 — WEIGHTED SCORE", bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["caption"], anchor="w").pack(fill="x")
        formula = "score = " + " + ".join(f"{weight:.2f}·{name}" for name, weight in config.ROUTING_WEIGHTS.items())
        self.formula = tk.Label(right.body, text=formula, bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"], justify="left", wraplength=px(350), anchor="w")
        self.formula.pack(fill="x", pady=(px(4), 0))
        right.body.bind("<Configure>", lambda e: self._wrap(e.width), add="+")
        recent = Card(self, title="RECENT DECISIONS", padding=px(11))
        recent.grid(row=1, column=0, sticky="nsew", padx=px(17), pady=(0, px(17)))
        self.recent_table = DataTable(recent.body, [
            ("met", "MET", 95, "w"), ("packet", "PACKET", 90, "w"),
            ("mode", "MODE", 75, "w"), ("score", "SCORE", 70, "e"),
            ("state", "STATE", 135, "w"), ("battery", "BATTERY %", 90, "e"),
            ("signal", "SIGNAL %", 90, "e"),
        ])
        # Treeview requests ten rows by default; four keeps the explanation visible.
        self.recent_table.tree.configure(height=2)
        self.recent_table.pack(fill="x")
        self._selected_id: int | None = None
        self._bars_signature: tuple | None = None

    def _wrap(self, width: int) -> None:
        self.reason.configure(wraplength=max(px(150), width-px(4)))
        self.formula.configure(wraplength=max(px(150), width-px(4)))

    def _select_row(self, row: dict) -> None:
        self._selected_id = row.get("packet_id")
        self._render_selected()

    def _render_selected(self) -> None:
        state = self.app.ui_state
        packet = next((item for item in state.queue if item.get("packet_id") == self._selected_id), None)
        if packet is None and state.queue:
            packet = state.queue[0]
            self._selected_id = packet.get("packet_id")
        decision = state.last_decision or {}
        if packet is None and decision:
            packet = {"packet_id": decision.get("packet_id"), "type_label": decision.get("packet_type"),
                      "priority": decision.get("priority"), "size_kb": decision.get("size_kb"),
                      "status": "SENT", "score": decision.get("total_score")}
        if packet is None:
            self.selected_title.configure(text="No packet selected")
            self.score_title.configure(text="AUTONOMOUS SCORE  —")
            self.reason.configure(text=state.hold_reason or "Packets appear here as the mission starts.")
            self.selected_badge.set("IDLE")
            if self._bars_signature is not None:
                self.score_bars.set([])
                self._bars_signature = None
            return
        packet_id = packet.get("packet_id")
        matched = decision if decision.get("packet_id") == packet_id else {}
        self.selected_title.configure(text=f"PACKET #{packet_id}")
        self.selected_badge.set(str(packet.get("status", "QUEUED")))
        self.selected_facts.set("Type", packet.get("type_label") or packet.get("packet_type", "—"))
        self.selected_facts.set("Priority", packet.get("priority", "—"))
        self.selected_facts.set("Size", f"{float(packet.get('size_kb') or 0):.1f} KB")
        score = float(matched.get("total_score", packet.get("score") or 0))
        self.score_title.configure(text=f"AUTONOMOUS SCORE  {score:.1f}")
        names = (("priority", "Priority", COLORS["cyan"]), ("link", "Link suitability", COLORS["blue"]),
                 ("urgency", "Urgency", COLORS["purple"]), ("energy", "Energy suitability", COLORS["green"]),
                 ("waiting", "Waiting time", COLORS["amber"]))
        breakdown = matched or decision
        bars = [(label, float(breakdown.get(name+"_score", 0)), config.ROUTING_WEIGHTS[name]*100, color)
                for name, label, color in names] if breakdown else []
        signature = (breakdown.get("packet_id"), tuple(round(row[1], 2) for row in bars)) if bars else None
        if signature != self._bars_signature:
            self.score_bars.set(bars)
            self._bars_signature = signature
        explanation = matched.get("reason") or packet.get("hold_reason") or state.hold_reason
        if not explanation and decision:
            explanation = f"Last selected packet #{decision.get('packet_id')}: {decision.get('reason', '')}"
        self.reason.configure(text=explanation or "Current score is estimated; packet awaits selection.")

    def _render(self) -> None:
        state = self.app.ui_state
        reason = state.hold_reason or "Router active — evaluating packet scores"
        self.hold.configure(text=reason, fg=COLORS["amber"] if state.hold_reason else COLORS["cyan"])
        self.rules.configure(text="Active safety rules: " + (" · ".join(state.active_rules) if state.active_rules else "standard battery, thermal and signal limits"))
        rows = []
        for packet in state.queue:
            status = "TRANSMITTING" if packet.get("packet_id") == state.transmitting_id else packet.get("status", "QUEUED")
            rows.append({**packet, "id": f"#{packet.get('packet_id')}", "type": packet.get("type_label", packet.get("packet_type", "")),
                         "size": f"{float(packet.get('size_kb') or 0):.1f}", "age": f"{float(packet.get('age') or 0):.0f}",
                         "required": f"{float(packet.get('required_signal') or 0):.0f}",
                         "energy": f"{float(packet['energy_cost']):.1f}" if packet.get("energy_cost") is not None else "—",
                         "score": f"{float(packet.get('score') or 0):.1f}", "status": status})
        self.queue_table.set_rows(rows, iid_key="packet_id", tag_key="status")
        if self._selected_id is None and state.queue:
            self._selected_id = state.queue[0].get("packet_id")
        self._render_selected()
        recent = [{"met": format_met(float(d.get("mission_time", 0))), "packet": f"#{d.get('packet_id', '')}",
                   "mode": d.get("selected_mode", ""), "score": f"{float(d.get('total_score', 0)):.1f}",
                   "state": d.get("system_state", ""), "battery": f"{float(d.get('battery', 0)):.0f}",
                   "signal": f"{float(d.get('signal', 0)):.0f}"} for d in state.decisions]
        self.recent_table.set_rows(recent)

    def on_show(self) -> None:
        super().on_show()
        self._render()

    def on_hide(self) -> None:
        super().on_hide()

    def handle_event(self, event) -> None:
        if self.visible and getattr(event.type, "value", event.type) in ("QUEUE_UPDATE", "PACKET_SELECTED", "STATE_CHANGED", "MISSION_STARTED"):
            self._render()
