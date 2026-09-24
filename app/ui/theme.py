"""Shared colours, type and ttk styling for the dark desktop interface."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk

COLORS = {
    "bg": "#0A0C10", "sidebar": "#0D1015", "surface": "#101318",
    "card": "#14181F", "card_hi": "#1A1F28", "card_hover": "#1E242E",
    "border": "#232A34", "border_hi": "#303947", "text": "#F2F4F7",
    "text_2": "#B4BCC8", "muted": "#7E8898", "green": "#30D158",
    "amber": "#FF9F0A", "red": "#FF453A", "blue": "#0A84FF",
    "cyan": "#64D2FF", "teal": "#40C8E0", "purple": "#BF5AF2",
    "indigo": "#5E5CE6", "grey": "#8E8E93",
}
STATUS_COLORS = {
    **dict.fromkeys(("nominal", "sent", "healthy", "ready"), COLORS["green"]),
    **dict.fromkeys(("warning", "deferred", "low_power", "thermal"), COLORS["amber"]),
    **dict.fromkeys(("critical", "failed", "dropped", "error"), COLORS["red"]),
    **dict.fromkeys(("active", "transmitting", "info", "selected"), COLORS["cyan"]),
    **dict.fromkeys(("queued", "idle", "inactive", "neutral"), COLORS["grey"]),
}
MODE_COLORS = {"TTC": COLORS["cyan"], "HOUSEKEEPING": COLORS["teal"],
               "SSTV": COLORS["purple"], "M17": COLORS["blue"],
               "CODEC2": COLORS["indigo"]}
CHART_COLORS = {"battery": COLORS["green"], "signal": COLORS["cyan"],
                "temperature": COLORS["amber"], "power": COLORS["purple"],
                "packet_loss": COLORS["red"]}

SCALE = 1.0
_FAMILY = "Segoe UI"
_MONO = "Consolas"
FONTS: dict[str, tuple] = {}
_PRESETS = {"display": (30, "bold"), "title": (19, "bold"),
            "h1": (16, "bold"), "h2": (13, "bold"),
            "body": (11, "normal"), "body_bold": (11, "bold"),
            "small": (10, "normal"), "caption": (9, "bold"),
            "metric": (26, "bold"), "metric_sm": (18, "bold"),
            "mono": (10, "normal")}


def blend(c1: str, c2: str, t: float) -> str:
    """Mix hex colours; t=0 gives c2 and t=1 gives c1."""
    t = max(0., min(1., t))
    a, b = (tuple(int(c[i:i+2], 16) for i in (1, 3, 5)) for c in (c1, c2))
    return "#" + "".join(f"{round(x*t+y*(1-t)):02X}" for x, y in zip(a, b))


def px(n: float) -> int:
    """Convert a design pixel to a DPI-aware Tk pixel."""
    return round(n * SCALE)


def font(size: int, weight: str = "normal") -> tuple:
    """Return a Tk font tuple in points, using the selected system family."""
    return (_FAMILY, size, weight)


def init_theme(root: tk.Misc) -> None:
    """Choose installed system fonts and measure Windows-aware display scale."""
    global SCALE, _FAMILY, _MONO
    available = set(tkfont.families(root))
    _FAMILY = next((x for x in ("SF Pro Display", "Segoe UI Variable Display", "Segoe UI",
                                "Helvetica Neue", "Helvetica", "Arial") if x in available), "Arial")
    _MONO = next((x for x in ("SF Mono", "Cascadia Mono", "Consolas", "Menlo",
                              "Courier New") if x in available), "Courier New")
    SCALE = root.winfo_fpixels("1i") / 96.0
    FONTS.clear()
    FONTS.update({name: ((_MONO if name == "mono" else _FAMILY), size, weight)
                  for name, (size, weight) in _PRESETS.items()})
    root.configure(bg=COLORS["bg"])


def status_kind(text: str) -> str:
    """Turn backend status labels into the small set of semantic UI states."""
    value = str(text or "").upper().replace("-", "_").replace(" ", "_")
    exact = {
        "NOMINAL": "nominal", "SENT": "sent", "HEALTHY": "healthy",
        "READY": "ready", "LINK_READY": "ready", "WARNING": "warning",
        "DEFERRED": "deferred", "LOW_POWER": "low_power",
        "THERMAL_ALERT": "thermal", "CRITICAL": "critical",
        "SAFE_MODE": "critical", "COMMUNICATION_LOSS": "critical",
        "LINK_DOWN": "critical", "FAILED": "failed", "DROPPED": "dropped",
        "ERROR": "error", "DEGRADED_LINK": "warning",
        "ACTIVE": "active", "ACTIVE_PASS": "active", "AOS": "active",
        "TRANSMITTING": "transmitting", "INFO": "info", "LIVE": "active",
        "SELECTED": "selected", "QUEUED": "queued", "IDLE": "idle",
        "INACTIVE": "inactive", "PRE_PASS": "idle", "LOS": "idle",
        "NO_PASS": "idle", "HOLD": "warning", "REPLAY": "info",
    }
    return exact.get(value, value.lower() if value.lower() in STATUS_COLORS else "neutral")


def configure_ttk(root: tk.Misc) -> None:
    """Use clam so Windows does not paint native light controls over the theme."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Dark.Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                    foreground=COLORS["text"], borderwidth=0, relief="flat",
                    bordercolor=COLORS["card"],lightcolor=COLORS["card"],
                    darkcolor=COLORS["card"],focuscolor=COLORS["card"],
                    rowheight=px(30), font=FONTS["small"])
    style.map("Dark.Treeview", background=[("selected", blend(COLORS["blue"], COLORS["card"], .35))],
              foreground=[("selected", COLORS["text"])])
    style.configure("Dark.Treeview.Heading", background=COLORS["card_hi"],
                    foreground=COLORS["text_2"], borderwidth=0, relief="flat",
                    padding=(px(8), px(8)), font=FONTS["caption"])
    style.map("Dark.Treeview.Heading", background=[("active", COLORS["card_hover"])])
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"Dark.{orient}.TScrollbar", background=COLORS["border_hi"],
                        troughcolor=COLORS["surface"], borderwidth=0, relief="flat",
                        troughrelief="flat",bordercolor=COLORS["surface"],
                        lightcolor=COLORS["surface"],darkcolor=COLORS["surface"],
                        arrowcolor=COLORS["muted"],gripcount=0,
                        arrowsize=px(8), width=px(9))
        style.map(f"Dark.{orient}.TScrollbar", background=[("active", COLORS["muted"])])
    for name in ("TCombobox", "TEntry"):
        style.configure(name, fieldbackground=COLORS["card_hi"], background=COLORS["card_hi"],
                        foreground=COLORS["text"], bordercolor=COLORS["border_hi"],
                        lightcolor=COLORS["border_hi"], darkcolor=COLORS["border_hi"],
                        arrowcolor=COLORS["text_2"], padding=px(7))
        style.map(name, fieldbackground=[("readonly", COLORS["card_hi"])],
                  foreground=[("readonly", COLORS["text"])])
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=COLORS["surface"], foreground=COLORS["text_2"],
                    borderwidth=0, padding=(px(16), px(9)), font=FONTS["small"])
    style.map("TNotebook.Tab", background=[("selected", COLORS["card_hi"])],
              foreground=[("selected", COLORS["text"])])
    style.configure("Horizontal.TScale", background=COLORS["bg"], troughcolor=COLORS["card_hi"],
                    borderwidth=0, lightcolor=COLORS["blue"], darkcolor=COLORS["blue"])
    root.option_add("*TCombobox*Listbox.background", COLORS["card_hi"])
    root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", COLORS["blue"])
    root.option_add("*Text.selectBackground", blend(COLORS["blue"], COLORS["card"], .55))
    root.option_add("*Entry.selectBackground", blend(COLORS["blue"], COLORS["card"], .55))


def style_figure(fig, *axes) -> None:
    """Apply legible dark colours to an existing Matplotlib figure and axes."""
    fig.patch.set_facecolor(COLORS["surface"])
    for ax in axes or tuple(fig.axes):
        ax.set_facecolor(COLORS["card"])
        for spine in ax.spines.values():
            spine.set_color(COLORS["border"])
        ax.tick_params(colors=COLORS["text_2"])
        ax.xaxis.label.set_color(COLORS["text_2"])
        ax.yaxis.label.set_color(COLORS["text_2"])
        ax.title.set_color(COLORS["text"])
        ax.grid(color=COLORS["border"], alpha=.6)
