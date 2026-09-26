"""Small page superclass used by the shell built in the next phase."""
from __future__ import annotations

import tkinter as tk

from .theme import COLORS, px


class BasePage(tk.Frame):
    """Pages override lifecycle hooks instead of coupling to shell details."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self.title = ""
        self.subtitle = ""
        self.visible = False

    def build_header(self, title: str, subtitle: str) -> None:
        """Record the heading (the shell top bar shows it) and add the top gutter."""
        self.title, self.subtitle = title, subtitle
        tk.Frame(self, bg=COLORS["bg"], height=px(17)).pack(fill="x")

    def on_show(self) -> None:
        self.visible = True

    def on_hide(self) -> None:
        self.visible = False

    def handle_event(self, event) -> None:
        """Handle a bus event when a subclass needs it."""
