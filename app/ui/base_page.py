"""Small page superclass used by the shell built in the next phase."""
from __future__ import annotations

import tkinter as tk

from .theme import COLORS, FONTS, px


class BasePage(tk.Frame):
    """Pages override lifecycle hooks instead of coupling to shell details."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self.title = ""
        self.subtitle = ""
        self.visible = False

    def build_header(self, title: str, subtitle: str, right_widgets_frame: bool = True):
        """Pack a consistent two-line page heading; return optional right slot."""
        self.title, self.subtitle = title, subtitle
        row = tk.Frame(self, bg=COLORS["bg"])
        row.pack(fill="x", padx=px(24), pady=(px(20), px(18)))
        text = tk.Frame(row, bg=COLORS["bg"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, font=FONTS["h1"], fg=COLORS["text"],
                 bg=COLORS["bg"], anchor="w").pack(fill="x")
        tk.Label(text, text=subtitle, font=FONTS["small"], fg=COLORS["text_2"],
                 bg=COLORS["bg"], anchor="w").pack(fill="x", pady=(px(3), 0))
        if right_widgets_frame:
            slot = tk.Frame(row, bg=COLORS["bg"])
            slot.pack(side="right", padx=(px(12), 0))
            return slot
        return None

    def on_show(self) -> None:
        self.visible = True

    def on_hide(self) -> None:
        self.visible = False

    def handle_event(self, event) -> None:
        """Handle a bus event when a subclass needs it."""
