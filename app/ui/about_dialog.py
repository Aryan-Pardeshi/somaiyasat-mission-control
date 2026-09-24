"""Academic project information in a compact dark modal."""
from __future__ import annotations

import tkinter as tk

from app import config
from .components import ModernButton
from .icons import draw_logo
from .theme import COLORS, FONTS, px


def show_about(app: tk.Misc) -> None:
    """Present project scope, technologies, and simulation disclaimer."""
    window = tk.Toplevel(app, bg=COLORS["surface"])
    window.title("About SomaiyaSat")
    window.transient(app)
    window.grab_set()
    window.resizable(False, False)
    width, height = px(570), px(525)
    x = app.winfo_rootx() + (app.winfo_width() - width) // 2
    y = app.winfo_rooty() + (app.winfo_height() - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")
    body = tk.Frame(window, bg=COLORS["surface"])
    body.pack(fill="both", expand=True, padx=px(32), pady=px(24))
    logo = tk.Canvas(body, width=px(72), height=px(72), bg=COLORS["surface"], highlightthickness=0)
    logo.pack()
    draw_logo(logo, px(36), px(36), px(65))
    tk.Label(body, text="SomaiyaSat Mission Control", bg=COLORS["surface"], fg=COLORS["text"], font=FONTS["title"]).pack(pady=(px(8), 0))
    tk.Label(body, text=config.APP_SUBTITLE, bg=COLORS["surface"], fg=COLORS["cyan"], font=FONTS["body"]).pack(pady=(px(3), px(18)))
    tk.Label(body, text="Python · Tkinter · SQLite · NumPy · Pandas · Matplotlib · Pillow", bg=COLORS["surface"], fg=COLORS["text_2"], font=FONTS["small"]).pack()
    purpose = "Academic purpose\n• Object-oriented satellite and radio models\n• Graphical mission monitoring\n• Database connectivity and multithreading\n• Data analysis and autonomous decision logic"
    tk.Label(body, text=purpose, justify="left", anchor="w", bg=COLORS["surface"], fg=COLORS["text_2"], font=FONTS["body"], wraplength=width-px(64)).pack(fill="x", pady=(px(20), px(16)))
    disclaimer = ("This project is an educational software simulation/digital twin inspired by the SomaiyaSat mission use case. "
                  "It does not communicate with real spacecraft hardware, implement actual RF protocols, or provide flight-qualified control logic.")
    tk.Label(body, text=disclaimer, justify="left", anchor="w", bg=COLORS["surface"], fg=COLORS["muted"], font=FONTS["small"], wraplength=width-px(64)).pack(fill="x")
    footer = tk.Frame(body, bg=COLORS["surface"])
    footer.pack(side="bottom", fill="x")
    tk.Label(footer, text=f"VERSION {config.APP_VERSION}", bg=COLORS["surface"], fg=COLORS["muted"], font=FONTS["caption"]).pack(side="left")
    ModernButton(footer, "Close", command=window.destroy, bg=COLORS["surface"]).pack(side="right")
