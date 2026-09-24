"""Embedded, reusable dark Matplotlib chart."""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable
import warnings

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import theme

LOG = logging.getLogger(__name__)


class ChartPanel(tk.Frame):
    """Host one Figure and redraw it on demand on Tk's thread."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.COLORS["surface"])
        self.figure = Figure(figsize=(8, 4), dpi=100 * theme.SCALE)
        theme.style_figure(self.figure)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def render(self, builder: Callable[[Figure], None]) -> None:
        """Build a figure and show a readable error instead of breaking the page."""
        self.figure.clear()
        try:
            # Some Seaborn artists need more space than Matplotlib's generic
            # tight-layout solver can promise; callers may refine margins.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Tight layout not applied.*")
                builder(self.figure)
                theme.style_figure(self.figure)
                if self.figure.axes:
                    self.figure.tight_layout(pad=1.2)
        except Exception:
            LOG.exception("Chart builder failed")
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            theme.style_figure(self.figure, ax)
            ax.text(.5, .5, "Chart unavailable", ha="center", va="center",
                    color=theme.COLORS["text_2"], transform=ax.transAxes)
            ax.set_axis_off()
        self.canvas.draw_idle()
