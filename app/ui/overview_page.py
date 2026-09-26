"""Live mission overview with orbit, ground pass, router explanation and feed."""
from __future__ import annotations

import tkinter as tk

from app import config
from app.utils.helpers import format_countdown
from .base_page import BasePage
from .components import Card, EventFeed, MetricCard, ModernButton, ProgressBar, ScoreBar, StatusBadge, TermLabel, add_tooltip
from .orbit_view import OrbitView
from .theme import COLORS, FONTS, px


TYPE_LABELS = {"TTC": "TT&C", "HOUSEKEEPING": "Housekeeping", "SSTV": "SSTV", "M17": "M17", "CODEC2": "Codec2"}


class OverviewPage(BasePage):
    """Keep the primary demo view current while its orbit animates only when visible."""

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        metrics = tk.Frame(self, bg=COLORS["bg"])
        metrics.grid(row=0, column=0, sticky="ew", padx=px(17), pady=(px(17), px(12)))
        for index in range(5):
            metrics.grid_columnconfigure(index, weight=1, uniform="metric")
        self.metrics: dict[str, MetricCard] = {}
        for index, (key, title, unit, spark) in enumerate((
            ("battery", "BATTERY", "%", True), ("signal", "SIGNAL", "%", False),
            ("temperature", "TEMP", "°C", False), ("power_draw", "POWER", "W", False),
            ("queue", "QUEUE", "", False),
        )):
            card = MetricCard(metrics, title=title, value="—", unit=unit, status="IDLE", subtitle="Awaiting telemetry", spark=[] if spark else None, padding=px(9), format_string="{:.0f}" if key == "queue" else "{:.1f}")
            card.subtitle_label.pack_configure(pady=(px(2), px(3)))
            card.sparkline.configure(height=px(12))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else px(5), 0 if index == 4 else px(5)))
            self.metrics[key] = card
        main = tk.Frame(self, bg=COLORS["bg"])
        main.grid(row=1, column=0, sticky="nsew", padx=px(17), pady=(0, px(17)))
        main.grid_rowconfigure(0, weight=1)
        for index, weight in enumerate((5, 4, 3)):
            main.grid_columnconfigure(index, weight=weight, uniform="overview")
        orbit_card = Card(main, padding=px(3))
        orbit_card.grid(row=0, column=0, sticky="nsew", padx=(0, px(7)))
        self.orbit = OrbitView(orbit_card.body, app.controller.orbit_angle_now)
        self.orbit.pack(fill="both", expand=True)
        middle = tk.Frame(main, bg=COLORS["bg"])
        middle.grid(row=0, column=1, sticky="nsew", padx=px(3))
        middle.grid_rowconfigure(1, weight=1)
        middle.grid_columnconfigure(0, weight=1)
        self._build_pass(middle)
        self._build_decision(middle)
        feed_card = Card(main, title="EVENT FEED")
        feed_card.grid(row=0, column=2, sticky="nsew", padx=(px(7), 0))
        self.feed = EventFeed(feed_card.body)
        self.feed.pack(fill="both", expand=True)

    def _build_pass(self, parent: tk.Frame) -> None:
        card = Card(parent, title="GROUND PASS", padding=px(10))
        card.grid(row=0, column=0, sticky="nsew", pady=(0, px(7)))
        self.pass_badge = StatusBadge(card.header_right, "PRE-PASS", bg=COLORS["card"])
        self.pass_badge.pack(side="right")
        self.countdown = tk.Label(card.body, text="NEXT AOS IN 00:12", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["metric_sm"], anchor="w")
        self.countdown.pack(fill="x", pady=(px(2), px(4)))
        self.pass_progress = ProgressBar(card.body, bg=COLORS["card"])
        self.pass_progress.pack(fill="x")
        row = tk.Frame(card.body, bg=COLORS["card"])
        row.pack(fill="x", pady=(px(4), 0))
        TermLabel(row, "AOS").pack(side="left")
        self.aos_value = tk.Label(row, text="—", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"])
        self.aos_value.pack(side="left", padx=(px(4), px(11)))
        TermLabel(row, "LOS").pack(side="left")
        self.los_value = tk.Label(row, text="—", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"])
        self.los_value.pack(side="left", padx=px(4))
        self.pass_detail = tk.Label(card.body, text="PASS #0 · SUNLIT", bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"], anchor="w")
        self.pass_detail.pack(fill="x", pady=(px(2), 0))
        self.skip_button = ModernButton(card.header_right, "Skip ⏭", command=self._skip_pass, kind="secondary", height=px(25), bg=COLORS["card"])
        self.skip_button.pack(side="right", padx=(0, px(6)))
        add_tooltip(self.skip_button, "Fast-forward the orbit to the next ground pass (live missions only)")

    def _build_decision(self, parent: tk.Frame) -> None:
        card = Card(parent, title="AUTONOMOUS DECISION", padding=px(13))
        card.grid(row=1, column=0, sticky="nsew", pady=(px(7), 0))
        self.decision_badge = StatusBadge(card.header_right, "HOLD", bg=COLORS["card"])
        self.decision_badge.pack(side="right")
        head = tk.Frame(card.body, bg=COLORS["card"])
        head.pack(fill="x")
        self.decision_score = tk.Label(head, text="—", bg=COLORS["card"], fg=COLORS["cyan"], font=FONTS["metric_sm"], anchor="e")
        self.decision_score.pack(side="right", anchor="n", padx=(px(8), 0))
        self.decision_head = tk.Label(head, text="Holding", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["h2"], wraplength=px(220), justify="left", anchor="w")
        self.decision_head.pack(side="left", fill="x", expand=True)
        self.reason_brief = tk.Label(card.body, text="Router waiting for a safe link window", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"], wraplength=px(300), justify="left", anchor="w")
        self.reason_brief.pack(fill="x", pady=(px(4), px(8)))
        self.expand_button = ModernButton(card.header_right, "Why?", command=self._toggle_detail, kind="secondary", height=px(25), bg=COLORS["card"])
        self.expand_button.pack(side="right", padx=(0, px(6)))
        self.bars = ScoreBar(card.body, compact=True)
        self.bars.pack(fill="x")
        self._bars_signature: tuple | None = None
        self.full_reason = tk.Label(card.body, text="", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"], justify="left", wraplength=px(300), anchor="nw")
        self._expanded = False
        card.body.bind("<Configure>", lambda e: self._wrap(e.width), add="+")

    def _wrap(self, width: int) -> None:
        self.decision_head.configure(wraplength=max(px(120), width-px(90)))
        for label in (self.reason_brief, self.full_reason):
            label.configure(wraplength=max(px(150), width-px(6)))

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self.bars.pack_forget()
            self.full_reason.pack(fill="both", expand=True)
        else:
            self.full_reason.pack_forget()
            self.bars.pack(fill="x")
        self.expand_button.set_text("Scores" if self._expanded else "Why?")

    def _skip_pass(self) -> None:
        advanced = self.app.controller.skip_to_next_pass()
        self.app.notify(f"Orbit advanced {advanced:.0f} s toward AOS" if advanced else "Already near the next pass", "info")

    def _render(self) -> None:
        state = self.app.ui_state
        snap = state.snapshot or {}
        if snap:
            battery, signal, temp = (float(snap.get(k, 0)) for k in ("battery", "signal", "temperature"))
            battery_kind = "CRITICAL" if battery < config.BATTERY_CRITICAL_THRESHOLD else "WARNING" if battery < config.BATTERY_LOW_THRESHOLD else "NOMINAL"
            signal_kind = "CRITICAL" if signal < config.SIGNAL_MIN_THRESHOLD and (state.pass_info or {}).get("in_pass") else "WARNING" if signal < config.DEGRADED_LINK_THRESHOLD and (state.pass_info or {}).get("in_pass") else "NOMINAL"
            temp_kind = "CRITICAL" if temp >= config.TEMP_CRITICAL_THRESHOLD else "WARNING" if temp >= config.TEMP_WARNING_THRESHOLD else "NOMINAL"
            self.metrics["battery"].update(battery, status=battery_kind, subtitle=f"{snap.get('voltage', 0):.2f} V · power reserve", level=battery/100, level_color=COLORS["red"] if battery_kind == "CRITICAL" else COLORS["amber"] if battery_kind == "WARNING" else COLORS["green"], spark=list(state.history["battery"]))
            self.metrics["signal"].update(signal, status=signal_kind, subtitle="Ground link quality", level=signal/100, level_color=COLORS["cyan"])
            self.metrics["temperature"].update(temp, status=temp_kind, subtitle="Onboard thermal", level=min(1, max(0, temp/85)), level_color=COLORS["red"] if temp_kind == "CRITICAL" else COLORS["amber"])
            mode = (state.transmission or {}).get("mode", "IDLE")
            self.metrics["power_draw"].update(float(snap.get("power_draw", 0)), status="ACTIVE" if mode != "IDLE" else "NOMINAL", subtitle=f"Mode: {mode}", level=min(1, float(snap.get("power_draw", 0))/4), level_color=COLORS["purple"])
        queue = state.queue
        critical = sum(p.get("priority") == "CRITICAL" for p in queue)
        deferred = sum(p.get("status") == "DEFERRED" for p in queue)
        self.metrics["queue"].update(len(queue), status="WARNING" if deferred else "NOMINAL", subtitle=f"{critical} critical · {deferred} deferred", level=min(1, len(queue)/config.MAX_QUEUE_SIZE), level_color=COLORS["cyan"])
        info = state.pass_info or {}
        in_pass = bool(info.get("in_pass"))
        phase = info.get("phase", "PRE-PASS")
        self.pass_badge.set(phase)
        self.countdown.configure(text=("LOS IN " if in_pass else "NEXT AOS IN ") + format_countdown(info.get("seconds_to_los" if in_pass else "seconds_to_aos", 0)))
        self.pass_progress.set(float(info.get("progress", 0)), COLORS["cyan"])
        self.aos_value.configure(text="ACQUIRED" if in_pass else format_countdown(info.get("seconds_to_aos", 0)))
        self.los_value.configure(text=format_countdown(info.get("seconds_to_los", 0)) if in_pass else "—")
        self.pass_detail.configure(text=f"PASS #{info.get('pass_number', 0)} · {'SUNLIT' if info.get('sunlit', True) else 'ECLIPSE'}")
        self.skip_button.set_enabled(self.app.controller.mode is not None and self.app.controller.mode.value == "LIVE" and self.app.controller.mission_active)
        decision = state.last_decision or {}
        if decision and state.transmitting_id == decision.get("packet_id"):
            label = TYPE_LABELS.get(str(decision.get("packet_type", "")), str(decision.get("packet_type", "")))
            self.decision_head.configure(text=f"{label} #{decision.get('packet_id')}")
            self.decision_score.configure(text=f"{float(decision.get('total_score', 0)):.1f}")
            self.decision_badge.set(decision.get("selected_mode", "ACTIVE"), "active")
            self.reason_brief.configure(text=f"{str(decision.get('priority', '')).capitalize()} priority, link {float(decision.get('signal', 0)):.0f} %, energy {float(decision.get('energy_cost', 0)):.1f} J")
        else:
            self.decision_head.configure(text="Holding")
            self.decision_score.configure(text="")
            self.decision_badge.set("HOLD")
            self.reason_brief.configure(text=state.hold_reason or "Router waiting for the next packet")
        self.full_reason.configure(text=decision.get("reason", state.hold_reason or "No packet selected yet"))
        bars = [(name.title(), float(decision.get(name+"_score", 0)), weight*100, color) for (name, weight), color in zip(config.ROUTING_WEIGHTS.items(), (COLORS["cyan"], COLORS["blue"], COLORS["purple"], COLORS["green"], COLORS["amber"]))] if decision else []
        signature = (decision.get("decision_id", decision.get("packet_id")), tuple(round(b[1], 1) for b in bars))
        if signature != self._bars_signature:
            self._bars_signature = signature
            self.bars.set(bars)
        self.orbit.update_state(info, snap, (state.transmission or {}).get("mode"))

    def on_show(self) -> None:
        super().on_show()
        self.feed.clear()
        for met, severity, message in reversed(self.app.ui_state.feed):
            self.feed.add(met, severity, message)
        self._render()
        self.orbit.start()

    def on_hide(self) -> None:
        self.orbit.stop()
        super().on_hide()

    def handle_event(self, event) -> None:
        kind = getattr(event.type, "value", event.type)
        if not self.visible:
            return
        if kind == "LOG":
            self.feed.add(event.data.get("met", self.app.ui_state.met), event.data.get("severity", "INFO"), event.data.get("message", ""))
        elif kind in ("TELEMETRY_UPDATE", "QUEUE_UPDATE", "PACKET_SELECTED", "TRANSMISSION_STARTED", "TRANSMISSION_COMPLETE", "TRANSMISSION_FAILED", "STATE_CHANGED"):
            self._render()
