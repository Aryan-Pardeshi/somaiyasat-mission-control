"""Live telemetry: animated ring gauges, a vitals strip and four rolling charts."""
from __future__ import annotations

import time
import tkinter as tk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure

from app import config
from .base_page import BasePage
from .components import Card, KeyValueList, RingGauge, StatusBadge
from .theme import CHART_COLORS, COLORS, FONTS, STATUS_COLORS, px, status_kind

GAUGES = (
    ("battery", "Battery", "%", (COLORS["teal"], COLORS["green"])),
    ("signal", "Signal", "%", (COLORS["blue"], COLORS["cyan"])),
    ("temperature", "Temperature", "°C", (COLORS["cyan"], COLORS["teal"])),
    ("power_draw", "Power draw", "W", (COLORS["indigo"], COLORS["purple"])),
)
VITALS = (("voltage", "Bus voltage"), ("packet_loss", "Packet loss"),
          ("queue_size", "Packets queued"), ("comm_state", "Ground link"))
CHARTS = (("battery", "Battery", "%"), ("temperature", "Temperature", "°C"),
          ("signal", "Signal", "%"), ("power_draw", "Power draw", "W"))
ALERT_COLORS = {"warning": (COLORS["amber"], "#FFD166"), "critical": (COLORS["red"], "#FF8A9A")}


def _gradient(color: str) -> np.ndarray:
    """A vertical RGBA ramp: transparent at the baseline, tinted at the peak."""
    ramp = np.zeros((256, 1, 4))
    ramp[..., :3] = to_rgb(color)
    ramp[..., 3] = np.linspace(0, .38, 256)[:, None] ** 1.4
    return ramp


class TelemetryPage(BasePage):
    """Display validated frames, bounds, and charts refreshed at most once per second."""

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_gauges()
        self._build_vitals()
        self._build_charts()
        self._last_chart = 0.0

    def _build_gauges(self) -> None:
        row = tk.Frame(self, bg=COLORS["bg"])
        row.grid(row=0, column=0, sticky="ew", padx=px(17), pady=(px(17), px(12)))
        self.gauges: dict[str, tuple[RingGauge, StatusBadge, KeyValueList]] = {}
        for index, (key, title, unit, colors) in enumerate(GAUGES):
            row.grid_columnconfigure(index, weight=1, uniform="gauge")
            card = Card(row, title=title, padding=px(12))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else px(6), 0 if index == 3 else px(6)))
            badge = StatusBadge(card.header_right, "IDLE", bg=COLORS["card"])
            badge.pack(side="right")
            body = tk.Frame(card.body, bg=COLORS["card"])
            body.pack(fill="both", expand=True)
            gauge = RingGauge(body, unit=unit, fmt="{:.2f}" if key == "power_draw" else "{:.1f}", colors=colors, size=px(118))
            gauge.pack(side="left")
            facts = KeyValueList(body, row_pady=px(4), value_font=(FONTS["small"][0], FONTS["small"][1], "bold"))
            facts.pack(side="left", fill="x", expand=True, padx=(px(6), 0))
            self.gauges[key] = (gauge, badge, facts)

    def _build_vitals(self) -> None:
        strip = Card(self, padding=px(12))
        strip.grid(row=1, column=0, sticky="ew", padx=px(17), pady=(0, px(12)))
        self.vitals: dict[str, tk.Label] = {}
        for index, (key, caption) in enumerate(VITALS):
            strip.body.grid_columnconfigure(index, weight=1, uniform="vital")
            cell = tk.Frame(strip.body, bg=COLORS["card"])
            cell.grid(row=0, column=index, sticky="ew")
            if index:
                tk.Frame(cell, bg=COLORS["border"], width=px(1)).pack(side="left", fill="y", padx=(0, px(16)))
            text = tk.Frame(cell, bg=COLORS["card"])
            text.pack(side="left")
            tk.Label(text, text=caption, bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"], anchor="w").pack(anchor="w")
            value = tk.Label(text, text="—", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["h1"], anchor="w")
            value.pack(anchor="w")
            self.vitals[key] = value

    def _build_charts(self) -> None:
        card = Card(self, title="Sensor history", padding=px(12))
        card.grid(row=2, column=0, sticky="nsew", padx=px(17), pady=(0, px(17)))
        self.figure = Figure(figsize=(8, 4), dpi=px(100), constrained_layout=True)
        self.figure.patch.set_facecolor(COLORS["card"])
        self.figure.get_layout_engine().set(w_pad=.08, h_pad=.08, hspace=.12, wspace=.06)
        self.charts = {}
        for axis, (key, title, unit) in zip(self.figure.subplots(2, 2).flat, CHARTS):
            color = CHART_COLORS["power" if key == "power_draw" else key]
            axis.set_facecolor(COLORS["card"])
            for side, spine in axis.spines.items():
                spine.set_visible(side == "bottom")
                spine.set_color(COLORS["border"])
            axis.tick_params(colors=COLORS["muted"], labelsize=8, length=0, pad=4)
            axis.grid(axis="y", color=COLORS["border"], linewidth=.8, alpha=.9)
            axis.set_axisbelow(True)
            axis.set_title(title, loc="left", fontsize=10, color=COLORS["text_2"], pad=8)
            readout = axis.text(1, 1.02, "", transform=axis.transAxes, ha="right", va="bottom",
                                fontsize=10, fontweight="bold", color=color)
            image = axis.imshow(_gradient(color), aspect="auto", origin="lower", extent=(0, 1, 0, 1),
                                interpolation="bicubic", zorder=1)
            glow, = axis.plot([], [], color=color, linewidth=5, alpha=.14, zorder=2, solid_capstyle="round")
            line, = axis.plot([], [], color=color, linewidth=1.9, zorder=3, solid_capstyle="round")
            guides = {"battery": ((config.BATTERY_LOW_THRESHOLD, COLORS["amber"]), (config.BATTERY_CRITICAL_THRESHOLD, COLORS["red"])),
                      "temperature": ((config.TEMP_WARNING_THRESHOLD, COLORS["amber"]), (config.TEMP_CRITICAL_THRESHOLD, COLORS["red"])),
                      "signal": ((config.SIGNAL_MIN_THRESHOLD, COLORS["red"]),)}.get(key, ())
            for value, guide_color in guides:
                axis.axhline(value, color=guide_color, alpha=.45, linestyle=(0, (4, 4)), linewidth=.9, zorder=1.5)
            self.charts[key] = {"axis": axis, "image": image, "glow": glow, "line": line,
                                "readout": readout, "unit": unit, "fill": None}
        canvas = FigureCanvasTkAgg(self.figure, master=card.body)
        canvas.get_tk_widget().configure(bg=COLORS["card"], highlightthickness=0)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.chart_canvas = canvas

    def _status(self, key: str, value) -> str:
        if key == "battery":
            return "CRITICAL" if value < config.BATTERY_CRITICAL_THRESHOLD else "WARNING" if value < config.BATTERY_LOW_THRESHOLD else "NOMINAL"
        if key == "temperature":
            return "CRITICAL" if value >= config.TEMP_CRITICAL_THRESHOLD else "WARNING" if value >= config.TEMP_WARNING_THRESHOLD else "NOMINAL"
        if key == "signal":
            in_pass = (self.app.ui_state.pass_info or {}).get("in_pass")
            if not in_pass:
                return "NO PASS"
            return "WARNING" if value < config.DEGRADED_LINK_THRESHOLD else "NOMINAL"
        if key == "power_draw":
            return "ACTIVE" if (self.app.ui_state.transmission or {}).get("mode") else "NOMINAL"
        return "NOMINAL"

    def _render_values(self) -> None:
        state = self.app.ui_state
        snapshot = state.snapshot or {}
        if not snapshot:
            return
        for key, _title, unit, colors in GAUGES:
            gauge, badge, facts = self.gauges[key]
            value = float(snapshot.get(key, 0))
            status = self._status(key, value)
            kind = status_kind(status)
            fraction = {"battery": value/100, "signal": value/100,
                        "temperature": (value+10)/95, "power_draw": value/4}[key]
            gauge.set(value, fraction, ALERT_COLORS.get("critical" if kind in ("critical", "failed") else kind, colors))
            badge.set(status)
            bounds = state.minmax.get(key) or {"min": value, "max": value}
            facts.set("Min", f"{bounds['min']:.1f} {unit}")
            facts.set("Max", f"{bounds['max']:.1f} {unit}")
            if key == "battery":
                facts.set("Low at", f"{config.BATTERY_LOW_THRESHOLD:.0f} %")
            elif key == "signal":
                facts.set("Needed", f"{config.SIGNAL_MIN_THRESHOLD:.0f} %")
            elif key == "temperature":
                facts.set("Alert at", f"{config.TEMP_WARNING_THRESHOLD:.0f} °C")
            else:
                facts.set("Mode", str((state.transmission or {}).get("mode") or "Idle"))
        loss = float(snapshot.get("packet_loss", 0))
        link = str(snapshot.get("comm_state", "—"))
        self.vitals["voltage"].configure(text=f"{float(snapshot.get('voltage', 0)):.2f} V")
        self.vitals["packet_loss"].configure(text=f"{loss:.1f} %", fg=COLORS["amber"] if loss > 5 else COLORS["text"])
        self.vitals["queue_size"].configure(text=str(int(snapshot.get("queue_size", len(state.queue)))))
        self.vitals["comm_state"].configure(text=link.replace("_", " ").capitalize(),
                                           fg=STATUS_COLORS.get(status_kind(link), COLORS["text"]))

    def _draw_chart(self) -> None:
        state = self.app.ui_state
        x = np.asarray(state.history["mission_time"], dtype=float)
        if len(x) < 2:
            return
        for key, _title, _unit in CHARTS:
            chart = self.charts[key]
            y = np.asarray(state.history[key], dtype=float)
            count = min(len(x), len(y))
            if count < 2:
                continue
            xs, y = x[-count:], y[-count:]
            if key in ("battery", "signal"):
                low, high = 0, 105
            elif key == "temperature":
                low, high = min(20, y.min()-4), max(config.TEMP_CRITICAL_THRESHOLD+4, y.max()+6)
            else:
                low, high = 0, max(2, y.max()*1.35)
            axis = chart["axis"]
            axis.set_xlim(xs[0], xs[-1])
            axis.set_ylim(low, high)
            chart["line"].set_data(xs, y)
            chart["glow"].set_data(xs, y)
            if chart["fill"] is not None:
                chart["fill"].remove()
            chart["fill"] = axis.fill_between(xs, y, low, facecolor="none", edgecolor="none")
            chart["image"].set_extent((xs[0], xs[-1], low, max(y.max(), low+1e-6)))
            paths = chart["fill"].get_paths()
            if paths:
                chart["image"].set_clip_path(paths[0], transform=axis.transData)
            chart["readout"].set_text(f"{y[-1]:.1f} {chart['unit']}")
        self.chart_canvas.draw_idle()
        self._last_chart = time.monotonic()

    def on_show(self) -> None:
        super().on_show()
        self._render_values()
        self._draw_chart()

    def handle_event(self, event) -> None:
        if getattr(event.type, "value", event.type) != "TELEMETRY_UPDATE" or not self.visible:
            return
        self._render_values()
        if (time.monotonic()-self._last_chart)*1000 >= config.CHART_REFRESH_MS:
            self._draw_chart()
