"""Progressive SSTV image reveal driven by real transmission progress events."""
from __future__ import annotations

import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from app import config
from .components import Card, StatusBadge
from .theme import COLORS, FONTS, px


class SSTVViewer(Card):
    """Retain downlink pixels while hidden; paste into one Tk image when visible."""

    def __init__(self, parent, source: Image.Image) -> None:
        super().__init__(parent, title="SSTV DOWNLINK VIEWER")
        self.source = source.convert("RGB").resize((320, config.SSTV_IMAGE_LINES), Image.Resampling.BILINEAR)
        self.source_pixels = np.asarray(self.source, dtype=np.uint8)
        self.height, self.width = self.source_pixels.shape[:2]
        self.buffer = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        self._rng = np.random.default_rng()
        self.packet_id: int | None = None
        self.revealed = 0
        self.state = "awaiting"
        self.noise = 0.0
        self.visible = False
        self.badge = StatusBadge(self.header_right, "AWAITING SIGNAL", bg=COLORS["card"])
        self.badge.pack(side="right")
        content = tk.Frame(self.body, bg=COLORS["card"])
        source_box = tk.Frame(content, bg=COLORS["card"])
        source_box.pack(side="left", fill="y", padx=(0, px(12)))
        tk.Label(source_box, text="SOURCE", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["caption"]).pack(anchor="w", pady=(0, px(7)))
        thumb = self.source.copy()
        thumb.thumbnail((px(145), px(145)))
        self._thumb_photo = ImageTk.PhotoImage(thumb)
        tk.Label(source_box, image=self._thumb_photo, bg=COLORS["card"]).pack(anchor="nw")
        downlink = tk.Frame(content, bg=COLORS["card"])
        downlink.pack(side="left", fill="both", expand=True)
        tk.Label(downlink, text="DOWNLINK", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["caption"]).pack(anchor="w", pady=(0, px(7)))
        self.canvas = tk.Canvas(downlink, bg="#02050A", height=px(150), highlightthickness=1, highlightbackground=COLORS["border"])
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._render(), add="+")
        self._photo: ImageTk.PhotoImage | None = None
        self._image_item: int | None = None
        self.caption = tk.Label(self.body, text="SSTV · ROBOT36 (simulated) · awaiting downlink", bg=COLORS["card"], fg=COLORS["text_2"], font=FONTS["small"], anchor="w")
        self.footnote = tk.Label(self.body, text="Visual simulation of progressive SSTV downlink — not an RF SSTV encoder.", bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"], anchor="w", justify="left", wraplength=px(400))
        self.footnote.pack(side="bottom", fill="x", pady=(px(3), 0))
        self.caption.pack(side="bottom", fill="x", pady=(px(5), 0))
        content.pack(fill="both", expand=True)
        self.body.bind("<Configure>", lambda e: self.footnote.configure(wraplength=max(px(180), e.width-px(6))), add="+")

    def set_visible(self, visible: bool) -> None:
        """Defer all Tk image copies while the communications page is hidden."""
        self.visible = visible
        if visible:
            self._render()

    def handle_event(self, event) -> None:
        """Accumulate scan lines even while hidden, keeping the final partial frame."""
        kind = getattr(event.type, "value", event.type)
        data = event.data
        if data.get("mode") != "SSTV":
            return
        if kind == "TRANSMISSION_STARTED":
            self.packet_id = (data.get("packet") or {}).get("packet_id")
            self.buffer.fill(0)
            self.revealed = 0
            self.noise = 0.0
            self.state = "receiving"
        elif kind == "TRANSMISSION_PROGRESS":
            if data.get("packet_id") != self.packet_id:
                return
            last = self.revealed
            self.revealed = max(last, min(self.height, int(float(data.get("progress", 0))*self.height)))
            self.noise = max(0.0, min(1.0, float(data.get("noise", 0))))
            if self.revealed > last:
                lines = self.source_pixels[last:self.revealed].astype(np.int16)
                amplitude = 2.0 + 40.0*self.noise + max(0.0, 60.0-float(data.get("signal", 100)))*.3
                grain = self._rng.normal(0, amplitude, size=lines.shape)
                lines = np.clip(lines+grain, 0, 255).astype(np.uint8)
                if self.noise > .08:
                    for row in range(lines.shape[0]):
                        if self._rng.random() < self.noise*.18:
                            lines[row] = np.roll(lines[row], int(self._rng.integers(-9, 10)), axis=0)
                self.buffer[last:self.revealed] = lines
        elif kind == "TRANSMISSION_COMPLETE":
            if (data.get("packet") or {}).get("packet_id") != self.packet_id:
                return
            if self.revealed < self.height:
                self.buffer[self.revealed:] = self.source_pixels[self.revealed:]
            self.revealed = self.height
            self.state = "complete"
        elif kind == "TRANSMISSION_FAILED":
            if (data.get("packet") or {}).get("packet_id") != self.packet_id:
                return
            self.state = "failed"
        else:
            return
        if self.visible:
            self._render()

    def _render(self) -> None:
        if not self.visible or self.canvas.winfo_width() < 5 or self.canvas.winfo_height() < 5:
            return
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min((canvas_w-px(8))/self.width, (canvas_h-px(8))/self.height)
        width, height = max(1, int(self.width*scale)), max(1, int(self.height*scale))
        image = Image.fromarray(self.buffer, mode="RGB").resize((width, height), Image.Resampling.NEAREST)
        if self._photo is None or self._photo.width() != width or self._photo.height() != height:
            self._photo = ImageTk.PhotoImage(image)
            if self._image_item is None:
                self._image_item = self.canvas.create_image(canvas_w/2, canvas_h/2, image=self._photo)
            else:
                self.canvas.itemconfigure(self._image_item, image=self._photo)
        else:
            self._photo.paste(image)
        self.canvas.coords(self._image_item, canvas_w/2, canvas_h/2)
        self.canvas.delete("overlay")
        top = (canvas_h-height)/2
        left = (canvas_w-width)/2
        if self.state == "receiving" and self.revealed:
            y = top + height*self.revealed/self.height
            self.canvas.create_line(left, y, left+width, y, fill=COLORS["cyan"], width=px(2), tags="overlay")
        if self.state in ("awaiting", "failed"):
            label = "AWAITING SIGNAL" if self.state == "awaiting" else f"INTERRUPTED · {100*self.revealed/self.height:.0f}%"
            self.canvas.create_text(canvas_w/2, canvas_h/2, text=label, fill=COLORS["muted"] if self.state == "awaiting" else COLORS["red"], font=FONTS["h2"], tags="overlay")
        badge = {"awaiting": "AWAITING SIGNAL", "receiving": "RECEIVING", "complete": "IMAGE RECEIVED", "failed": "INTERRUPTED"}[self.state]
        self.badge.set(badge, {"receiving": "active", "complete": "sent", "failed": "failed"}.get(self.state, "idle"))
        noise_label = "low" if self.noise < .2 else "moderate" if self.noise < .5 else "high"
        self.caption.configure(text=f"SSTV · ROBOT36 (simulated) · line {self.revealed}/{self.height} · noise {noise_label}")
