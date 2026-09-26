"""Reusable dark controls. All public classes are exported from this module."""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import font as tkfont, ttk
from typing import Callable

from app import config
from .icons import draw_icon
from .theme import COLORS, FONTS, STATUS_COLORS, blend, px, status_kind


def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                 r: float, **kw) -> int:
    """Draw a round rectangle using a smooth polygon (Tk has no native shape)."""
    r = min(max(0, r), max(0, (x2-x1)/2), max(0, (y2-y1)/2))
    return canvas.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,
                                 x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,
                                 x1,y2,x1,y2-r,x1,y1+r,x1,y1,
                                 smooth=True, splinesteps=12, **kw)


class Card(tk.Frame):
    """Rounded card with a real content frame in ``body`` and a header slot."""

    def __init__(self, parent, padding=None, radius=None, bg=COLORS["card"],
                 border=COLORS["border"], title: str | None = None,
                 hover: bool = False, **kw):
        parent_bg = kw.pop("parent_bg", parent.cget("bg") if "bg" in parent.keys() else COLORS["bg"])
        super().__init__(parent, bg=parent_bg, **kw)
        self.card_bg, self.border_color = bg, border
        self.padding = px(16) if padding is None else padding
        self.radius = px(14) if radius is None else radius
        self._hot = False
        self.canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self.canvas.place(relwidth=1, relheight=1)
        inset = max(self.padding, round(self.radius*.35))
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=inset, pady=inset)
        self.header_right = tk.Frame(self.body, bg=bg)
        if title is not None:
            header = tk.Frame(self.body, bg=bg)
            header.pack(fill="x", pady=(0,px(8)))
            tk.Label(header, text=title.upper(), bg=bg, fg=COLORS["text_2"],
                     font=FONTS["caption"], anchor="w").pack(side="left")
            self.header_right = tk.Frame(header, bg=bg)
            self.header_right.pack(side="right")
        self.bind("<Configure>", self._draw)
        if hover:
            for widget in (self, self.canvas, self.body):
                widget.bind("<Enter>", lambda _: self._hover(True), add="+")
                widget.bind("<Leave>", lambda _: self._hover(False), add="+")

    def _hover(self, hot: bool) -> None:
        self._hot = hot
        self._draw()

    def _draw(self, _event=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        self.canvas.delete("all")
        if w < 4 or h < 4:
            return
        edge = COLORS["border_hi"] if self._hot else self.border_color
        rounded_rect(self.canvas, px(1), px(1), w-px(1), h-px(1), self.radius,
                     fill=self.card_bg, outline=edge, width=max(1,px(1)))
        self.canvas.create_line(self.radius+px(2),px(2),w-self.radius-px(2),px(2),
            fill=blend(COLORS["border_hi"],self.card_bg,.5),width=max(1,px(1)))
        # Canvas was created before body, so the packed content remains above it.


class StatusBadge(tk.Canvas):
    """Auto-sized status chip. ``set(text, kind=None)`` updates it in place."""

    def __init__(self, parent, text="", kind=None, bg=None, pulse=False, **kw):
        self.parent_bg = bg or (parent.cget("bg") if "bg" in parent.keys() else COLORS["card"])
        super().__init__(parent, bg=self.parent_bg, highlightthickness=0, bd=0, **kw)
        self._pulse = pulse
        self._job = None
        self._phase = 0.
        self.set(text, kind)
        if pulse:
            self._tick()

    def set(self, text: str, kind: str | None = None) -> None:
        self.text = str(text).upper().replace("_", " ")
        self.kind = kind or status_kind(text)
        color = STATUS_COLORS.get(self.kind, COLORS["grey"])
        face = blend(color, self.parent_bg, .16)
        width = tkfont.Font(font=FONTS["caption"]).measure(self.text) + px(34)
        height = px(25)
        self.configure(width=width, height=height)
        self.delete("all")
        rounded_rect(self,px(1),px(1),width-px(1),height-px(1),height/2,
                     fill=face,outline="")
        self._dot = self.create_oval(px(9),height/2-px(3),px(15),height/2+px(3),
                                     fill=color,outline="")
        self.create_text(px(21),height/2,text=self.text,fill=color,font=FONTS["caption"],anchor="w")

    def _tick(self):
        self._phase += .23
        radius = px(2.6 + .75*(1+math.sin(self._phase)))
        h = px(25)/2
        self.coords(self._dot,px(12)-radius,h-radius,px(12)+radius,h+radius)
        self._job = self.after(50,self._tick)

    def destroy(self):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        super().destroy()


class ModernButton(tk.Canvas):
    """Canvas pill with semantic kind and hover/pressed/disabled states."""

    def __init__(self, parent, text: str, command: Callable | None = None,
                 kind="secondary", icon: str | None = None, width=None,
                 height=None, bg=None, **kw):
        self.parent_bg = bg or (parent.cget("bg") if "bg" in parent.keys() else COLORS["bg"])
        self.text, self.icon, self.command, self.kind = text, icon, command, kind
        self.enabled, self.hot, self.pressed = True, False, False
        self._height = px(36) if height is None else height
        self._width = width
        super().__init__(parent, bg=self.parent_bg, highlightthickness=0, bd=0,
                         height=self._height, cursor="hand2", **kw)
        self.bind("<Enter>", lambda _: self._state(hot=True))
        self.bind("<Leave>", lambda _: self._state(hot=False,pressed=False))
        self.bind("<ButtonPress-1>", lambda _: self._state(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._draw)
        self._measure()

    def _measure(self):
        label = (self.icon + "  " if self.icon else "") + self.text
        self.configure(width=self._width or tkfont.Font(font=FONTS["body_bold"]).measure(label)+px(30))
        self._draw()

    def _state(self, hot=None, pressed=None):
        if hot is not None: self.hot = hot
        if pressed is not None: self.pressed = pressed
        self._draw()

    def _release(self, _):
        was_pressed = self.pressed
        self.pressed = False
        self._draw()
        if was_pressed and self.hot and self.enabled and self.command:
            self.command()

    def _draw(self, _event=None):
        w,h = self.winfo_width(),self.winfo_height()
        if w <= 1: w = int(self.cget("width"))
        if h <= 1: h = self._height
        self.delete("all")
        face, fg, edge = {
            "primary": (COLORS["blue"],COLORS["text"],COLORS["blue"]),
            "secondary": (COLORS["card_hi"],COLORS["text"],COLORS["border_hi"]),
            "danger": (blend(COLORS["red"],self.parent_bg,.18),COLORS["red"],COLORS["border"]),
            "success": (blend(COLORS["green"],self.parent_bg,.20),COLORS["green"],COLORS["border"]),
            "ghost": (self.parent_bg,COLORS["text_2"],self.parent_bg),
        }.get(self.kind,(COLORS["card_hi"],COLORS["text"],COLORS["border_hi"]))
        if self.hot and self.enabled: face=blend(COLORS["text"],face,.09)
        if self.pressed: face=blend(COLORS["bg"],face,.20)
        if not self.enabled:
            face=blend(face,self.parent_bg,.45)
            fg=blend(fg,self.parent_bg,.45)
        rounded_rect(self,px(1),px(1),w-px(1),h-px(1),h*.43,
                     fill=face,outline=edge,width=max(1,px(1)))
        label=(self.icon+"  " if self.icon else "")+self.text
        self.create_text(w/2,h/2,text=label,fill=fg,font=FONTS["body_bold"])

    def set_text(self, text: str):
        self.text=text
        self._measure()

    def set_enabled(self, enabled: bool):
        self.enabled=bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()


class SidebarButton(tk.Frame):
    """Sidebar nav item; call ``set_active(bool)`` as pages change."""

    def __init__(self,parent,text,icon,command=None,active=False,bg=COLORS["sidebar"]):
        super().__init__(parent,bg=bg,height=px(43),cursor="hand2")
        self.pack_propagate(False)
        self.text,self.icon,self.command,self.parent_bg=text,icon,command,bg
        self.active,self.hot=active,False
        self.accent=tk.Frame(self,width=px(3),bg=bg)
        self.accent.pack(side="left",fill="y")
        self.symbol=tk.Canvas(self,width=px(24),height=px(24),bg=bg,highlightthickness=0)
        self.symbol.pack(side="left",padx=(px(13),px(10)))
        self.label=tk.Label(self,text=text,bg=bg,fg=COLORS["text_2"],font=FONTS["body"],anchor="w")
        self.label.pack(side="left",fill="x",expand=True)
        for widget in (self,self.symbol,self.label):
            widget.bind("<Enter>",lambda _:self._hover(True))
            widget.bind("<Leave>",lambda _:self._hover(False))
            widget.bind("<Button-1>",lambda _:self.command() if self.command else None)
        self._paint()

    def _hover(self,value):
        self.hot=value
        self._paint()

    def set_active(self,active: bool):
        self.active=active
        self._paint()

    def _paint(self):
        bg=COLORS["card_hi"] if self.active else (COLORS["card"] if self.hot else self.parent_bg)
        fg=COLORS["text"] if self.active else COLORS["text_2"]
        for widget in (self,self.symbol,self.label):widget.configure(bg=bg)
        self.label.configure(fg=fg)
        self.accent.configure(bg=bg)
        self.symbol.delete("all")
        draw_icon(self.symbol,self.icon,px(12),px(12),px(17),COLORS["blue"] if self.active else fg)


class AnimatedValue:
    """A cancellable 250 ms number tween owned by a Tk widget."""

    def __init__(self,widget,callback,format_string="{:.1f}"):
        self.widget,self.callback,self.format_string=widget,callback,format_string
        self.value=None
        self._job=None

    def set(self,value):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job=None
        try: target=float(value)
        except (TypeError,ValueError):
            self.value=None
            self.callback(str(value))
            return
        if self.value is None:
            self.value=target
            self.callback(self.format_string.format(target))
            return
        start=self.value
        begun=time.monotonic()
        def step():
            t=min(1.,(time.monotonic()-begun)/.25)
            eased=1-(1-t)**3
            self.value=start+(target-start)*eased
            self.callback(self.format_string.format(self.value))
            self._job=None if t>=1 else self.widget.after(16,step)
        step()

    def stop(self):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job=None


class LevelBar(tk.Canvas):
    """Thin rounded track; ``set(fraction, color=None)`` clamps to 0..1."""

    def __init__(self,parent,fraction=0.,color=COLORS["green"],bg=None,height=None,**kw):
        self.parent_bg=bg or (parent.cget("bg") if "bg" in parent.keys() else COLORS["card"])
        self.fraction,self.color=fraction,color
        super().__init__(parent,bg=self.parent_bg,highlightthickness=0,bd=0,
                         height=height or px(6),**kw)
        self.bind("<Configure>",self._draw)

    def set(self,fraction,color=None):
        self.fraction=max(0.,min(1.,float(fraction)))
        if color: self.color=color
        self._draw()

    def _draw(self,_=None):
        w,h=self.winfo_width(),self.winfo_height()
        self.delete("all")
        if w<2:return
        rounded_rect(self,0,0,w,h,h/2,fill=COLORS["border_hi"],outline="")
        if self.fraction>0:
            rounded_rect(self,0,0,max(h,w*self.fraction),h,h/2,fill=self.color,outline="")


class ProgressBar(LevelBar):
    """Animated level with optional moving shimmer while indeterminate."""

    def __init__(self,parent,**kw):
        super().__init__(parent,height=kw.pop("height",px(9)),**kw)
        self._job=None
        self._target=self.fraction
        self._indeterminate=False
        self._phase=0.

    def set(self,fraction,color=None):
        self._target=max(0.,min(1.,float(fraction)))
        if color:self.color=color
        if self._job is not None:
            self.after_cancel(self._job)
            self._job=None
        self._animate()

    def set_indeterminate(self,active: bool):
        self._indeterminate=bool(active)
        if active:self._animate()
        elif self._job is not None:
            self.after_cancel(self._job)
            self._job=None
            self._draw()

    def _animate(self):
        self.fraction+=(self._target-self.fraction)*.22
        if abs(self.fraction-self._target)<.003:self.fraction=self._target
        self._phase=(self._phase+.025)%1.
        self._draw()
        if self._indeterminate:
            w,h=self.winfo_width(),self.winfo_height()
            x=w*self._phase
            rounded_rect(self,max(0,x-px(30)),0,min(w,x+px(30)),h,h/2,
                         fill=blend(COLORS["text"],self.color,.28),outline="")
        self._job=None
        if self._indeterminate or self.fraction!=self._target:
            self._job=self.after(16,self._animate)

    def destroy(self):
        if self._job is not None:self.after_cancel(self._job)
        super().destroy()


class Sparkline(tk.Canvas):
    """Small auto-scaled signal line with a muted duplicate for depth."""

    def __init__(self,parent,values=None,color=COLORS["cyan"],bg=None,**kw):
        self.parent_bg=bg or (parent.cget("bg") if "bg" in parent.keys() else COLORS["card"])
        self.values,self.color=list(values or []),color
        super().__init__(parent,bg=self.parent_bg,highlightthickness=0,bd=0,**kw)
        self.bind("<Configure>",self._draw)

    def set(self,values,color=None):
        self.values=list(values or [])
        if color:self.color=color
        self._draw()

    def _draw(self,_=None):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if len(self.values)<2 or w<4:return
        lo,hi=min(self.values),max(self.values)
        span=max(1e-9,hi-lo)
        points=[]
        for i,value in enumerate(self.values):
            points.extend((px(2)+(w-px(4))*i/(len(self.values)-1),
                           px(3)+(h-px(7))*(1-(value-lo)/span)))
        self.create_line(*[v+(px(3) if i%2 else 0) for i,v in enumerate(points)],
                         fill=blend(self.color,self.parent_bg,.22),width=max(1,px(3)),smooth=True)
        self.create_line(*points,fill=self.color,width=max(1,px(1.5)),smooth=True)


class MetricCard(Card):
    """Metric, optional status/sparkline, range and level; update via ``update``."""

    def __init__(self,parent,title,value="—",unit="",status="NOMINAL",
                 subtitle="",level=0.,spark=None,format_string="{:.1f}",**kw):
        kw.setdefault("padding",px(12))
        super().__init__(parent,title=title,**kw)
        self.badge=StatusBadge(self.header_right,status,bg=self.card_bg)
        self.badge.pack(side="right")
        row=tk.Frame(self.body,bg=self.card_bg)
        row.pack(fill="x")
        self.value_label=tk.Label(row,text="",font=FONTS["metric"],fg=COLORS["text"],bg=self.card_bg)
        self.value_label.pack(side="left",anchor="s")
        self.unit_label=tk.Label(row,text=unit,font=FONTS["body"],fg=COLORS["text_2"],bg=self.card_bg)
        self.unit_label.pack(side="left",padx=(px(4),0),anchor="s",pady=(0,px(4)))
        self.subtitle_label=tk.Label(self.body,text=subtitle,font=FONTS["small"],
                                     fg=COLORS["text_2"],bg=self.card_bg,anchor="w")
        self.subtitle_label.pack(fill="x",pady=(px(3),px(8)))
        self.level_bar=LevelBar(self.body,fraction=level,bg=self.card_bg)
        self.level_bar.pack(fill="x")
        self.sparkline=Sparkline(self.body,height=px(18),bg=self.card_bg)
        if spark is not None:self.sparkline.pack(fill="x",pady=(px(8),0))
        self._value=AnimatedValue(self,self.value_label.configure,format_string)
        # configure(text=...) needs a named argument, so replace the callback.
        self._value.callback=lambda text:self.value_label.configure(text=text)
        self.update(value,unit,status,subtitle,level,spark=spark)

    def update(self,value,unit=None,status=None,subtitle=None,level=None,
               level_color=None,spark=None):
        self._value.set(value)
        if unit is not None:self.unit_label.configure(text=unit)
        if status is not None:self.badge.set(status)
        if subtitle is not None:self.subtitle_label.configure(text=subtitle)
        if level is not None:self.level_bar.set(level,level_color)
        if spark is not None:
            if not self.sparkline.winfo_manager():self.sparkline.pack(fill="x",pady=(px(8),0))
            self.sparkline.set(spark,level_color)

    def destroy(self):
        self._value.stop()
        super().destroy()


# Keep the public import surface small for page builders while separating
# controls by responsibility so no source file grows unwieldy.
from ._components_extra import (EventFeed, DataTable, Tooltip, add_tooltip,
                                SegmentedControl, KeyValueList, ScoreBar,
                                ScrollableFrame, TermLabel, GLOSSARY, humanize, RingGauge)
