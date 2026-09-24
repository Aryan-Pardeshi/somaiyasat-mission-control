"""Current satellite telemetry and four efficient rolling Matplotlib charts."""
from __future__ import annotations

import time
import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from app import config
from .base_page import BasePage
from .components import Card, KeyValueList, StatusBadge
from .theme import CHART_COLORS, COLORS, FONTS, px, style_figure


class TelemetryPage(BasePage):
    """Display validated frames, bounds, and charts refreshed at most once per second."""

    FIELDS = (
        ("battery", "BATTERY", "%"), ("voltage", "VOLTAGE", "V"),
        ("temperature", "TEMPERATURE", "°C"), ("signal", "SIGNAL", "%"),
        ("power_draw", "POWER", "W"), ("packet_loss", "PACKET LOSS", "%"),
        ("queue_size", "QUEUE", ""), ("comm_state", "COMM STATE", ""),
    )

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        tiles = tk.Frame(self, bg=COLORS["bg"])
        tiles.grid(row=0, column=0, sticky="ew", padx=px(17), pady=(px(17), px(12)))
        self.tiles: dict[str, tuple[tk.Label, tk.Label, StatusBadge]] = {}
        for index in range(4):
            tiles.grid_columnconfigure(index, weight=1, uniform="tile")
        for index, (key, title, unit) in enumerate(self.FIELDS):
            card = Card(tiles, title=title, padding=px(10))
            column = index % 4
            card.grid(row=index//4, column=column, sticky="nsew", padx=(0 if column == 0 else px(4), 0 if column == 3 else px(4)), pady=(0, px(7)) if index < 4 else (px(7), 0))
            value = tk.Label(card.body, text="—", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["metric_sm"], anchor="w")
            value.pack(fill="x")
            bounds = tk.Label(card.body, text="MIN —  MAX —", bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"], anchor="w")
            bounds.pack(fill="x", pady=(px(3), 0))
            badge = StatusBadge(card.body, "IDLE", bg=COLORS["card"])
            badge.place(relx=1, y=0, anchor="ne")
            self.tiles[key] = (value, bounds, badge)
        content = tk.Frame(self, bg=COLORS["bg"])
        content.grid(row=1, column=0, sticky="nsew", padx=px(17), pady=(0, px(17)))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        chart_card = Card(content, title="LIVE SENSOR HISTORY")
        chart_card.grid(row=0, column=0, sticky="nsew")
        self.figure = Figure(figsize=(8, 5), dpi=px(100), constrained_layout=True)
        self.axes = self.figure.subplots(2, 2)
        style_figure(self.figure, *self.axes.flat)
        self.lines = {}
        self.signal_fill = None
        for axis, (key, title, unit) in zip(self.axes.flat, (
            ("battery", "Battery", "%"), ("temperature", "Temperature", "°C"),
            ("signal", "Signal", "%"), ("power_draw", "Power draw", "W"),
        )):
            axis.set_title(title, fontsize=11, loc="left", pad=7, color=COLORS["text"])
            axis.set_xlabel("MET (s)", fontsize=9)
            axis.set_ylabel(unit, fontsize=9)
            axis.tick_params(labelsize=8)
            axis.grid(True, alpha=.35)
            color = CHART_COLORS["power" if key == "power_draw" else key]
            self.lines[key], = axis.plot([], [], color=color, linewidth=1.8)
            guides = {"battery": ((25, COLORS["amber"]), (15, COLORS["red"])),
                      "temperature": ((60, COLORS["amber"]), (70, COLORS["red"])),
                      "signal": ((20, COLORS["red"]),)}.get(key, ())
            for value, color in guides:
                axis.axhline(value, color=color, alpha=.34, linestyle="--", linewidth=.9)
        canvas = FigureCanvasTkAgg(self.figure, master=chart_card.body)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.chart_canvas = canvas
        self._last_chart = 0.0
        self._chart_dirty = True

    def _status(self, key: str, value: float | str, snapshot: dict) -> str:
        if key == "battery":
            return "CRITICAL" if value < config.BATTERY_CRITICAL_THRESHOLD else "WARNING" if value < config.BATTERY_LOW_THRESHOLD else "NOMINAL"
        if key == "temperature":
            return "CRITICAL" if value >= config.TEMP_CRITICAL_THRESHOLD else "WARNING" if value >= config.TEMP_WARNING_THRESHOLD else "NOMINAL"
        if key == "signal":
            return "WARNING" if (self.app.ui_state.pass_info or {}).get("in_pass") and value < config.DEGRADED_LINK_THRESHOLD else "NOMINAL"
        if key == "packet_loss":
            return "WARNING" if value > 5 else "NOMINAL"
        if key == "comm_state":
            return str(value)
        return "NOMINAL"

    def _render_values(self) -> None:
        state = self.app.ui_state
        snapshot = state.snapshot or {}
        if not snapshot:
            return
        for key, _, unit in self.FIELDS:
            value_label, bounds_label, badge = self.tiles[key]
            value = snapshot.get(key, "—")
            if isinstance(value, (int, float)):
                formatted = f"{value:.1f}" if key != "queue_size" else str(int(value))
                if key == "voltage":
                    formatted = f"{value:.2f}"
                value_label.configure(text=f"{formatted}{unit}")
                bounds = state.minmax.get(key)
                bounds_label.configure(text=f"MIN {bounds['min']:.1f}  MAX {bounds['max']:.1f}" if bounds else "LIVE VALUE")
            else:
                value_label.configure(text=str(value))
                bounds_label.configure(text="GROUND LINK")
            badge.set(self._status(key, value, snapshot))

    def _draw_chart(self) -> None:
        state = self.app.ui_state
        x = list(state.history["mission_time"])
        if not x:
            return
        for key, axis in zip(("battery", "temperature", "signal", "power_draw"), self.axes.flat):
            y = list(state.history[key])
            self.lines[key].set_data(x[-len(y):], y)
            axis.relim()
            axis.autoscale_view()
            if key in ("battery", "signal"):
                axis.set_ylim(0, 105)
            if key == "signal":
                if self.signal_fill is not None:
                    self.signal_fill.remove()
                self.signal_fill = axis.fill_between(x[-len(y):], y, color=CHART_COLORS[key], alpha=.10)
        self.chart_canvas.draw_idle()
        self._chart_dirty = False
        self._last_chart = time.monotonic()

    def on_show(self) -> None:
        super().on_show()
        self._render_values()
        self._draw_chart()

    def on_hide(self) -> None:
        super().on_hide()

    def handle_event(self, event) -> None:
        kind = getattr(event.type, "value", event.type)
        if kind != "TELEMETRY_UPDATE":
            return
        self._chart_dirty = True
        if self.visible:
            self._render_values()
            if (time.monotonic()-self._last_chart)*1000 >= config.CHART_REFRESH_MS:
                self._draw_chart()
