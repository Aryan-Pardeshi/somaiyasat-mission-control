"""Radio mode readiness, active transmission, and progressive SSTV downlink."""
from __future__ import annotations

import tkinter as tk
from collections import deque

from app import config
from app.models.enums import CommunicationType, PacketPriority, PacketType
from app.models.packet import create_packet
from .base_page import BasePage
from .components import Card, DataTable, ModernButton, ProgressBar, StatusBadge, TermLabel
from .sstv_viewer import SSTVViewer
from .theme import COLORS, FONTS, px


MODE_LABELS = {"TTC": "TT&C", "SSTV": "SSTV", "M17": "M17", "CODEC2": "Codec2", "HOUSEKEEPING": "TT&C"}


class _TransmissionFacts(tk.Frame):
    """Four paired facts use two columns so the operator action stays visible."""

    def __init__(self, parent) -> None:
        super().__init__(parent, bg=COLORS["card"])
        self.cells = []
        for index in range(4):
            column, row = index % 2, index // 2
            self.grid_columnconfigure(column, weight=1)
            cell = tk.Frame(self, bg=COLORS["card"])
            cell.grid(row=row, column=column, sticky="ew", pady=px(5), padx=(0, px(10)) if column == 0 else (px(10), 0))
            caption = tk.Label(cell, bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"])
            caption.pack(side="left")
            value = tk.Label(cell, bg=COLORS["card"], fg=COLORS["text"], font=FONTS["body_bold"])
            value.pack(side="right")
            self.cells.append((caption, value))

    def show(self, rows: list[tuple[str, str]]) -> None:
        """Replace captions and values without rebuilding Tk widgets each tick."""
        for (caption, value), (label, text) in zip(self.cells, rows):
            caption.configure(text=label)
            value.configure(text=text)


class CommunicationsPage(BasePage):
    """Follow real RF events and let operators enqueue a high priority SSTV frame."""

    MODES = (("TTC", "TT&C"), ("SSTV", "SSTV"), ("M17", "M17"), ("CODEC2", "Codec2"))

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        modes = tk.Frame(self, bg=COLORS["bg"])
        modes.grid(row=0, column=0, sticky="ew", padx=px(17), pady=(px(17), px(12)))
        self.mode_ui: dict[str, tuple[StatusBadge, dict[str, tk.Label]]] = {}
        for index, (mode, label) in enumerate(self.MODES):
            modes.grid_columnconfigure(index, weight=1, uniform="mode")
            card = Card(modes, padding=px(12))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else px(5), 0 if index == 3 else px(5)))
            head = tk.Frame(card.body, bg=COLORS["card"])
            head.pack(fill="x", pady=(0, px(9)))
            TermLabel(head, label, font=FONTS["h2"], fg=COLORS["text"]).pack(side="left")
            badge = StatusBadge(head, "NO PASS", bg=COLORS["card"])
            badge.pack(side="right")
            facts: dict[str, tk.Label] = {}
            for key, caption in (("signal", "Min signal"), ("power", "Power"),
                                 ("energy", "Typical energy"), ("waiting", "Waiting"),
                                 ("stats", "Sent / failed")):
                row = tk.Frame(card.body, bg=COLORS["card"])
                row.pack(fill="x", pady=px(2))
                tk.Label(row, text=caption, bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"]).pack(side="left")
                value = tk.Label(row, text="—", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["body_bold"])
                value.pack(side="right")
                facts[key] = value
            self.mode_ui[mode] = (badge, facts)
        content = tk.Frame(self, bg=COLORS["bg"])
        content.grid(row=1, column=0, sticky="nsew", padx=px(17), pady=(0, px(17)))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=2)
        content.grid_columnconfigure(1, weight=3)
        current = Card(content, title="CURRENT TRANSMISSION")
        current.grid(row=0, column=0, sticky="nsew", padx=(0, px(7)))
        self.tx_badge = StatusBadge(current.header_right, "IDLE", bg=COLORS["card"])
        self.tx_badge.pack(side="right")
        self.tx_head = tk.Label(current.body, text="Link idle — waiting for the router", bg=COLORS["card"], fg=COLORS["text"], font=FONTS["h2"], anchor="w", wraplength=px(360), justify="left")
        self.tx_head.pack(fill="x", pady=(px(2), px(4)))
        self.tx_percent = tk.Label(current.body, text="0%", bg=COLORS["card"], fg=COLORS["cyan"], font=FONTS["metric"], anchor="w")
        self.tx_percent.pack(fill="x")
        self.tx_progress = ProgressBar(current.body, bg=COLORS["card"])
        self.tx_progress.pack(fill="x", pady=(px(2), px(10)))
        self.tx_facts = _TransmissionFacts(current.body)
        self.tx_facts.pack(fill="x")
        self.request_button = ModernButton(current.body, "Request SSTV image downlink", command=self._request_sstv, kind="primary", height=px(30), bg=COLORS["card"])
        self.request_button.pack(anchor="w", pady=(px(8), 0))
        tk.Label(current.body, text="RECENT DOWNLINKS", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["caption"], anchor="w").pack(fill="x", pady=(px(14), px(6)))
        self.history_table = DataTable(current.body, [
            ("met", "MET", 70, "w"), ("packet", "PACKET", 70, "w"),
            ("mode", "MODE", 70, "w"), ("size", "KB", 55, "e"), ("result", "RESULT", 90, "w"),
        ])
        self.history_table.pack(fill="both", expand=True)
        self._history: deque[dict] = deque(maxlen=30)
        self.viewer = SSTVViewer(content, app.sstv_image)
        self.viewer.grid(row=0, column=1, sticky="nsew", padx=(px(7), 0))
        self._tx_packet: dict = {}
        self._tx_event: dict = {}
        self._failure: dict | None = None
        current.body.bind("<Configure>", lambda e: self.tx_head.configure(wraplength=max(px(180), e.width-px(8))), add="+")

    def _request_sstv(self) -> None:
        try:
            packet_id = self.app.controller.request_sstv_downlink()
        except RuntimeError as exc:
            self.app.notify(str(exc), "warning")
            return
        self.app.notify(f"SSTV packet #{packet_id} queued for downlink", "success")

    def _mode_status(self, mode: str) -> str:
        state = self.app.ui_state
        tx = state.transmission or {}
        if tx.get("mode") == mode:
            return "TRANSMITTING"
        if mode not in config.STATE_ALLOWED_MODES.get(state.state, set()):
            return "SUSPENDED"
        if not (state.pass_info or {}).get("in_pass"):
            return "NO PASS"
        if (state.snapshot or {}).get("comm_state") == "LINK DOWN":
            return "LINK DOWN"
        if float((state.snapshot or {}).get("signal", 0)) < config.MODE_MIN_SIGNAL[mode]:
            return "SIGNAL LOW"
        return "READY"

    def _render_modes(self) -> None:
        state = self.app.ui_state
        for mode, _label in self.MODES:
            badge, facts = self.mode_ui[mode]
            status = self._mode_status(mode)
            badge.set(status, "warning" if status == "SUSPENDED" else None)
            waiting = sum(p.get("mode") == mode and p.get("status") in ("QUEUED", "DEFERRED", "SELECTED") for p in state.queue)
            stats = state.comm_stats.get(mode, {})
            facts["signal"].configure(text=f"{config.MODE_MIN_SIGNAL[mode]:.0f}%")
            facts["power"].configure(text=f"{config.MODE_POWER_COSTS[mode]:.2f} W")
            packet_type = PacketType.TTC if mode == "TTC" else PacketType(mode)
            size = sum(config.PACKET_SIZE_RANGES_KB[packet_type.value])/2
            packet = create_packet(packet_type, 0, PacketPriority.MEDIUM, size, 0)
            mode_obj = self.app.controller.comms.modes[CommunicationType(mode)]
            energy = mode_obj.calculate_energy_cost(packet, max(75, config.MODE_MIN_SIGNAL[mode]))
            facts["energy"].configure(text=f"{energy:.1f} J")
            facts["waiting"].configure(text=str(waiting))
            facts["stats"].configure(text=f"{stats.get('sent', 0)} / {stats.get('failed', 0)}")

    def _render_transmission(self) -> None:
        state = self.app.ui_state
        data = state.transmission or {}
        packet_id = state.transmitting_id or data.get("packet_id")
        packet = next((p for p in state.queue if p.get("packet_id") == packet_id), self._tx_packet)
        if data and packet_id:
            mode = data.get("mode", packet.get("mode", "—"))
            self.tx_badge.set("TRANSMITTING")
            self.tx_head.configure(text=f"Packet #{packet_id} over {MODE_LABELS.get(str(mode), mode)}", fg=COLORS["text"])
            progress = float(data.get("progress", 0))
            self.tx_percent.configure(text=f"{progress*100:.0f}%")
            self.tx_progress.set(progress, COLORS["cyan"])
            self.tx_facts.show([
                ("Size", f"{float(packet.get('size_kb') or data.get('total_kb') or 0):.1f} KB"),
                ("Signal", f"{float(data.get('signal', (state.snapshot or {}).get('signal', 0))):.0f}%"),
                ("ETA", f"{float(data.get('eta', data.get('estimated_time', 0))):.1f} s"),
                ("Elapsed", f"{max(0, self.app.controller.mission_time()-self._tx_event.get('start_met', self.app.controller.mission_time())):.1f} s"),
            ])
        elif self._failure:
            packet = self._failure.get("packet") or {}
            reason = self._failure.get("reason", "link interrupted")
            self.tx_badge.set("INTERRUPTED", "failed")
            self.tx_head.configure(text=f"Interrupted: {reason}", fg=COLORS["red"])
            self.tx_percent.configure(text=f"{100*float(self._failure.get('progress', 0)):.0f}%")
            self.tx_progress.set(float(self._failure.get("progress", 0)), COLORS["red"])
            retry = int(packet.get("retry_count", 0))
            max_retries = config.MAX_RETRIES_CRITICAL if packet.get("priority") == "CRITICAL" else config.MAX_RETRIES
            self.tx_facts.show([
                ("Packet", f"#{packet.get('packet_id', '—')}"),
                ("Status", f"Requeued (retry {retry}/{max_retries})" if self._failure.get("requeued") else "FAILED permanently"),
                ("Size", f"{float(packet.get('size_kb') or 0):.1f} KB"),
                ("Mode", str(self._failure.get("mode", "—"))),
            ])
        else:
            self.tx_badge.set("IDLE")
            self.tx_head.configure(text="Link idle — waiting for the router", fg=COLORS["text"])
            self.tx_percent.configure(text="0%")
            self.tx_progress.set(0, COLORS["cyan"])
            self.tx_facts.show([
                ("Size", "—"), ("Signal", f"{float((state.snapshot or {}).get('signal', 0)):.0f}%"),
                ("ETA", "—"), ("Elapsed", "—"),
            ])
        self.request_button.set_enabled(self.app.controller.mission_active)

    def _log(self, data: dict, result: str) -> None:
        packet = data.get("packet") or {}
        self._history.appendleft({
            "key": f"{packet.get('packet_id')}:{len(self._history)}:{self.app.ui_state.met}",
            "met": self.app.ui_state.met, "packet": f"#{packet.get('packet_id', '—')}",
            "mode": data.get("mode", packet.get("mode", "—")),
            "size": f"{float(packet.get('size_kb') or 0):.1f}", "result": result,
        })
        if self.visible:
            self.history_table.set_rows(list(self._history), iid_key="key", tag_key="result")

    def on_show(self) -> None:
        super().on_show()
        self.viewer.set_visible(True)
        self._render_modes()
        self._render_transmission()
        self.history_table.set_rows(list(self._history), iid_key="key", tag_key="result")

    def on_hide(self) -> None:
        self.viewer.set_visible(False)
        super().on_hide()

    def handle_event(self, event) -> None:
        kind = getattr(event.type, "value", event.type)
        self.viewer.handle_event(event)
        if kind == "TRANSMISSION_STARTED":
            self._tx_packet = dict(event.data.get("packet") or {})
            self._tx_event = {**event.data, "start_met": self.app.controller.mission_time()}
            self._failure = None
        elif kind == "TRANSMISSION_PROGRESS":
            self._tx_event.update(event.data)
        elif kind == "TRANSMISSION_FAILED":
            self._failure = dict(event.data)
            self._tx_event = {}
            self._log(event.data, "REQUEUED" if event.data.get("requeued") else "FAILED")
        elif kind == "TRANSMISSION_COMPLETE":
            self._failure = None
            self._tx_event = {}
            self._log(event.data, "SENT")
        elif kind == "MISSION_STARTED":
            self._tx_packet = {}
            self._tx_event = {}
            self._failure = None
            self._history.clear()
            self.history_table.set_rows([])
        if self.visible and kind in ("TELEMETRY_UPDATE", "QUEUE_UPDATE", "TRANSMISSION_STARTED", "TRANSMISSION_PROGRESS", "TRANSMISSION_COMPLETE", "TRANSMISSION_FAILED", "STATE_CHANGED", "MISSION_STARTED"):
            self._render_modes()
            self._render_transmission()
