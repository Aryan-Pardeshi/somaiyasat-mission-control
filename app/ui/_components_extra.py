"""Table, feed and layout controls re-exported by components.py."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable

from app import config
from .theme import COLORS, FONTS, STATUS_COLORS, blend, px, status_kind
from .components import LevelBar, rounded_rect


class EventFeed(tk.Frame):
    """Newest-first, bounded operator event log: a meta line, then the message."""

    SOURCES = {"INFO": COLORS["cyan"], "WARNING": COLORS["amber"], "CRITICAL": COLORS["red"],
               "SYSTEM": COLORS["purple"], "ROUTER": COLORS["blue"]}

    def __init__(self,parent,bg=COLORS["card"],**kw):
        super().__init__(parent,bg=bg,**kw)
        self.text=tk.Text(self,bg=bg,fg=COLORS["text"],font=FONTS["small"],
                          bd=0,highlightthickness=0,wrap="word",state="disabled",
                          padx=px(2),pady=px(2),cursor="arrow")
        self.text.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(self,orient="vertical",style="Dark.Vertical.TScrollbar",
                             command=self.text.yview)
        scroll.pack(side="right",fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure("time",foreground=COLORS["muted"],font=FONTS["mono"])
        self.text.tag_configure("message",foreground=COLORS["text_2"],spacing1=px(2),spacing3=px(10))
        for source,color in self.SOURCES.items():
            self.text.tag_configure(source,foreground=color,font=FONTS["caption"])
        self._entries=0

    def add(self,met: str,severity: str,message: str):
        source=severity.upper() if severity.upper() in self.SOURCES else "INFO"
        self.text.configure(state="normal")
        self.text.insert("1.0",f"{met}   ","time",source.title()+"\n",source,message+"\n","message")
        self._entries+=1
        if self._entries>config.EVENT_FEED_MAX_LINES:
            self.text.delete(f"{2*config.EVENT_FEED_MAX_LINES+1}.0","end")
            self._entries=config.EVENT_FEED_MAX_LINES
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0","end")
        self.text.configure(state="disabled")
        self._entries=0


def humanize(value):
    """Show enum-style codes such as THERMAL_ALERT as THERMAL ALERT."""
    if isinstance(value,str) and "_" in value and value.upper()==value:
        return value.replace("_"," ")
    return value


class DataTable(tk.Frame):
    """Sortable dark Treeview. ``set_rows`` keeps selection and scroll position."""

    def __init__(self,parent,columns: list[tuple[str,str,int,str]],bg=COLORS["card"],**kw):
        super().__init__(parent,bg=bg,**kw)
        self.columns=columns
        self._rows:dict[str,dict]={}
        self._callback=None
        self._sort_key=None
        self._reverse=False
        self.tree=ttk.Treeview(self,columns=[c[0] for c in columns],show="headings",
                               style="Dark.Treeview",selectmode="browse")
        self.tree.grid(row=0,column=0,sticky="nsew")
        self.grid_rowconfigure(0,weight=1)
        self.grid_columnconfigure(0,weight=1)
        vs=ttk.Scrollbar(self,orient="vertical",style="Dark.Vertical.TScrollbar",command=self.tree.yview)
        vs.grid(row=0,column=1,sticky="ns")
        self.tree.configure(yscrollcommand=vs.set)
        for key,heading,width,anchor in columns:
            self.tree.heading(key,text=heading,anchor=anchor,command=lambda col=key:self._sort(col))
            self.tree.column(key,width=px(width),minwidth=px(40),anchor=anchor,stretch=False)
        self.tree.bind("<Configure>",self._fit_columns,add="+")
        self.tree.tag_configure("odd",background=blend(COLORS["text"],bg,.025))
        for kind,color in STATUS_COLORS.items():
            self.tree.tag_configure(kind,foreground=color)
        self.tree.bind("<<TreeviewSelect>>",self._selected)

    def _fit_columns(self,event=None):
        # Columns share the visible width in proportion to their design widths,
        # so tables never need a horizontal scrollbar.
        available=(event.width if event else self.tree.winfo_width())-px(2)
        total=sum(width for _,_,width,_ in self.columns)
        if available<px(100) or total<=0:return
        used=0
        for index,(key,_,width,_) in enumerate(self.columns):
            size=available-used if index==len(self.columns)-1 else int(available*width/total)
            self.tree.column(key,width=max(px(40),size))
            used+=size

    def set_rows(self,rows: list[dict],iid_key=None,tag_key=None):
        old_selection=self.tree.selection()
        top=self.tree.yview()[0]
        desired=[]
        for index,row in enumerate(rows):
            iid=str(row.get(iid_key,index)) if iid_key else str(index)
            if iid in desired:iid=f"{iid}:{index}"
            desired.append(iid)
            values=tuple(humanize(row.get(col[0],"")) for col in self.columns)
            kind=status_kind(row.get(tag_key,"")) if tag_key else ""
            tags=(("odd",) if index%2 else ()) + ((kind,) if kind and kind!="neutral" else ())
            if iid in self.tree.get_children(""):
                if tuple(self.tree.item(iid,"values"))!=tuple(str(v) for v in values):
                    self.tree.item(iid,values=values,tags=tags)
                else:self.tree.item(iid,tags=tags)
            else:self.tree.insert("","end",iid=iid,values=values,tags=tags)
            self._rows[iid]=dict(row)
        for iid in set(self.tree.get_children(""))-set(desired):
            self.tree.delete(iid)
            self._rows.pop(iid,None)
        for index,iid in enumerate(desired):
            self.tree.move(iid,"",index)
        if self._sort_key:
            self._sort(self._sort_key, preserve_direction=True)
        selected=[iid for iid in old_selection if iid in desired]
        if selected:self.tree.selection_set(selected)
        self.tree.yview_moveto(top)

    def _sort(self,key,preserve_direction=False):
        if not preserve_direction:
            self._reverse=not self._reverse if self._sort_key==key else False
        self._sort_key=key
        def sort_value(iid):
            value=self._rows[iid].get(key,"")
            try:return (0,float(value))
            except (ValueError,TypeError):return (1,str(value).lower())
        for index,iid in enumerate(sorted(self.tree.get_children(""),key=sort_value,reverse=self._reverse)):
            self.tree.move(iid,"",index)

    def _selected(self,_=None):
        if self._callback:
            row=self.selected_row()
            if row is not None:self._callback(row)

    def on_select(self,callback: Callable[[dict],None]):
        self._callback=callback

    def selected_row(self):
        selected=self.tree.selection()
        return self._rows.get(selected[0]) if selected else None


class Tooltip:
    """Delayed rounded help popup. Destroy is safe even if never shown."""

    def __init__(self,widget,text: str):
        self.widget,self.text=widget,text
        self._job=None
        self._popup=None
        widget.bind("<Enter>",self._schedule,add="+")
        widget.bind("<Leave>",self._hide,add="+")
        widget.bind("<Button-1>",self._hide,add="+")
        widget.bind("<Destroy>",self._hide,add="+")

    def _schedule(self,_):
        self._hide()
        self._job=self.widget.after(450,self._show)

    def _show(self):
        self._job=None
        if not self.widget.winfo_exists():return
        pop=tk.Toplevel(self.widget)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.configure(bg=COLORS["bg"])
        label=tk.Label(pop,text=self.text,wraplength=px(280),justify="left",
                       bg=COLORS["card_hi"],fg=COLORS["text"],font=FONTS["small"])
        label.update_idletasks()
        pad_x,pad_y=px(12),px(9)
        width,height=label.winfo_reqwidth()+2*pad_x,label.winfo_reqheight()+2*pad_y
        canvas=tk.Canvas(pop,width=width,height=height,bg=COLORS["bg"],
                         highlightthickness=0,bd=0)
        canvas.pack()
        rounded_rect(canvas,px(1),px(1),width-px(1),height-px(1),px(10),
                     fill=COLORS["card_hi"],outline=COLORS["border_hi"],width=max(1,px(1)))
        canvas.create_window(pad_x,pad_y,window=label,anchor="nw")
        pop.update_idletasks()
        pop.geometry(f"+{self.widget.winfo_rootx()+px(12)}+{self.widget.winfo_rooty()+self.widget.winfo_height()+px(7)}")
        pop.deiconify()
        self._popup=pop

    def _hide(self,_=None):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job=None
        if self._popup is not None:
            self._popup.destroy()
            self._popup=None


def add_tooltip(widget,text: str) -> Tooltip:
    """Attach and return a tooltip so callers may retain it if useful."""
    return Tooltip(widget,text)


class SegmentedControl(tk.Frame):
    """Compact option switch; ``set(option)`` also calls the command."""

    def __init__(self,parent,options,command=None,selected=None,bg=COLORS["card_hi"],**kw):
        super().__init__(parent,bg=bg,padx=px(3),pady=px(3),**kw)
        self.options=list(options)
        self.command=command
        self.selected=selected if selected is not None else (self.options[0] if self.options else None)
        self._buttons=[]
        for option in self.options:
            button=tk.Canvas(self,width=max(px(62),px(10)*len(str(option))),height=px(30),
                             bg=bg,highlightthickness=0,cursor="hand2")
            button.pack(side="left",padx=px(1))
            button.bind("<Button-1>",lambda _,item=option:self.set(item))
            button.bind("<Configure>",lambda _:self._paint())
            self._buttons.append(button)
        self._paint()

    def _paint(self):
        for option,button in zip(self.options,self._buttons):
            button.delete("all")
            w,h=button.winfo_width(),button.winfo_height()
            if w<2:w=int(button.cget("width"))
            if h<2:h=int(button.cget("height"))
            active=option==self.selected
            rounded_rect(button,0,0,w,h,px(8),fill=COLORS["border_hi"] if active else button.cget("bg"),outline="")
            button.create_text(w/2,h/2,text=str(option),font=FONTS["small"],
                               fill=COLORS["text"] if active else COLORS["text_2"])

    def set(self,option):
        if option not in self.options:raise ValueError(f"Unknown segment: {option}")
        self.selected=option
        self._paint()
        if self.command:self.command(option)


class KeyValueList(tk.Frame):
    """Two-column facts. Unknown keys are appended by ``set``."""

    def __init__(self,parent,rows=None,bg=COLORS["card"],row_pady=None,value_font=None,**kw):
        super().__init__(parent,bg=bg,**kw)
        self._labels={}
        self.value_font=value_font or FONTS["body_bold"]
        self.row_pady = px(5) if row_pady is None else row_pady
        for key,value in rows or []:self.set(key,value)

    def set(self,key,value,color=None):
        if key not in self._labels:
            row=tk.Frame(self,bg=self.cget("bg"))
            row.pack(fill="x",pady=self.row_pady)
            tk.Label(row,text=str(key),bg=row.cget("bg"),fg=COLORS["text_2"],
                     font=FONTS["small"]).pack(side="left")
            label=tk.Label(row,bg=row.cget("bg"),fg=COLORS["text"],font=self.value_font)
            label.pack(side="right")
            self._labels[key]=label
        self._labels[key].configure(text=str(value),fg=color or COLORS["text"])


class ScoreBar(tk.Frame):
    """Weighted-score breakdown. Rows: (label, points, max_points, colour)."""

    def __init__(self,parent,rows=None,bg=COLORS["card"],compact=False,**kw):
        super().__init__(parent,bg=bg,**kw)
        self._jobs=[]
        self.compact=compact
        self.set(rows or [])

    def set(self,rows):
        for job in self._jobs:self.after_cancel(job)
        self._jobs.clear()
        for child in self.winfo_children():child.destroy()
        for label,points,maximum,color in rows:
            row=tk.Frame(self,bg=self.cget("bg"))
            row.pack(fill="x",pady=0 if self.compact else px(5))
            top=tk.Frame(row,bg=row.cget("bg"))
            top.pack(fill="x")
            tk.Label(top,text=label,bg=top.cget("bg"),fg=COLORS["text_2"],
                     font=FONTS["caption"] if self.compact else FONTS["small"]).pack(side="left")
            tk.Label(top,text=f"+{points:.1f}",bg=top.cget("bg"),fg=COLORS["text"],
                     font=FONTS["caption"] if self.compact else FONTS["body_bold"]).pack(side="right")
            bar=LevelBar(row,bg=row.cget("bg"),color=color,height=px(3) if self.compact else None)
            bar.pack(fill="x",pady=(0 if self.compact else px(5),0))
            target=max(0.,min(1.,points/max(1e-9,maximum)))
            def animate(b=bar,t=target,step=0):
                b.set(t*(1-(1-min(1,step/13))**3))
                if step<13:self._jobs.append(self.after(16,lambda:animate(b,t,step+1)))
            animate()

    def destroy(self):
        for job in self._jobs:self.after_cancel(job)
        super().destroy()


class ScrollableFrame(tk.Frame):
    """Pack content into ``body``; wheel events are local to this container."""

    def __init__(self,parent,bg=COLORS["bg"],**kw):
        super().__init__(parent,bg=bg,**kw)
        self.canvas=tk.Canvas(self,bg=bg,highlightthickness=0)
        self.canvas.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(self,orient="vertical",style="Dark.Vertical.TScrollbar",
                             command=self.canvas.yview)
        scroll.pack(side="right",fill="y")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body=tk.Frame(self.canvas,bg=bg)
        self._window=self.canvas.create_window(0,0,window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self._window,width=e.width))
        for widget in (self,self.canvas,self.body):
            widget.bind("<Enter>",self._bind_wheel,add="+")
            widget.bind("<Leave>",self._unbind_wheel,add="+")

    def _bind_wheel(self,_):
        self.bind_all("<MouseWheel>",self._wheel,add="+")

    def _unbind_wheel(self,_):
        self.unbind_all("<MouseWheel>")

    def _wheel(self,event):
        self.canvas.yview_scroll(-int(event.delta/120),"units")

    def destroy(self):
        self.unbind_all("<MouseWheel>")
        super().destroy()


GLOSSARY={
    "AOS":"Acquisition of Signal — the moment the ground station first hears the satellite",
    "LOS":"Loss of Signal — the satellite drops below the ground station's horizon",
    "TT&C":"Telemetry, Tracking & Command — the satellite's essential health and control link",
    "SSTV":"Slow-Scan Television — transmits still images line by line over radio",
    "M17":"M17 — an open-source digital radio mode for voice and data",
    "Codec2":"Codec2 — an open-source low-bitrate speech codec for narrow radio links",
    "HOUSEKEEPING":"Housekeeping — routine subsystem health data",
    "MET":"Mission Elapsed Time",
    "SAFE_MODE":"Safe mode — minimal-power survival state; only critical TT&C allowed",
}


class TermLabel(tk.Label):
    """A help term; hovering shows its glossary definition."""

    def __init__(self,parent,term: str,text=None,bg=COLORS["card"],**kw):
        kw.setdefault("font",FONTS["small"])
        kw.setdefault("fg",COLORS["text_2"])
        super().__init__(parent,text=text or term,bg=bg,cursor="question_arrow",**kw)
        self.tooltip=Tooltip(self,GLOSSARY.get(term,term))


class RingGauge(tk.Canvas):
    """A 270° gauge whose gradient arc eases toward each new reading."""

    START,SWEEP=225,270

    def __init__(self,parent,unit="",fmt="{:.1f}",colors=(COLORS["blue"],COLORS["cyan"]),
                 bg=COLORS["card"],size=None,**kw):
        size=size or px(138)
        super().__init__(parent,width=size,height=size,bg=bg,highlightthickness=0,bd=0,**kw)
        self.bg,self.unit,self.fmt,self.colors=bg,unit,fmt,colors
        self.fraction=self._target=0.
        self.value=None
        self._shown=None
        self._job=None
        self.bind("<Configure>",lambda _e:self._draw())

    def set(self,value,fraction,colors=None):
        self._target=max(0.,min(1.,float(fraction)))
        if colors:self.colors=colors
        self.value=value
        if not isinstance(value,(int,float)):self._shown=None
        elif self._shown is None:self._shown=float(value)
        if self._job is None:self._animate()

    def _animate(self):
        self.fraction+=(self._target-self.fraction)*.16
        numeric=isinstance(self.value,(int,float)) and self._shown is not None
        if numeric:self._shown+=(self.value-self._shown)*.16
        done=abs(self._target-self.fraction)<.002 and (not numeric or abs(self.value-self._shown)<.01)
        if done:
            self.fraction=self._target
            if numeric:self._shown=float(self.value)
        self._draw()
        self._job=None if done else self.after(16,self._animate)

    def _point(self,cx,cy,r,angle):
        radians=math.radians(angle)
        return cx+r*math.cos(radians),cy-r*math.sin(radians)

    def _draw(self):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if w<4:w=int(self.cget("width"))
        if h<4:h=int(self.cget("height"))
        d=min(w,h)
        cx,cy=w/2,h/2+d*.04
        thick=max(px(7),d*.07)
        r=d/2-thick*1.4
        box=(cx-r,cy-r,cx+r,cy+r)
        self.create_arc(*box,start=self.START,extent=-self.SWEEP,style="arc",width=thick,
                        outline=blend(COLORS["border_hi"],self.bg,.75))
        low,high=self.colors
        if self.fraction>.003:
            sweep=self.SWEEP*self.fraction
            self.create_arc(*box,start=self.START,extent=-sweep,style="arc",width=thick*2.6,
                            outline=blend(high,self.bg,.10))
            self.create_arc(*box,start=self.START,extent=-sweep,style="arc",width=thick*1.7,
                            outline=blend(high,self.bg,.18))
            steps=max(2,int(48*self.fraction))
            for i in range(steps):
                start=self.START-sweep*i/steps
                self.create_arc(*box,start=start,extent=-(sweep/steps+.9),style="arc",width=thick,
                                outline=blend(high,low,i/(steps-1)))
            for angle,color in ((self.START,low),(self.START-sweep,high)):
                x,y=self._point(cx,cy,r,angle)
                self.create_oval(x-thick/2,y-thick/2,x+thick/2,y+thick/2,fill=color,outline="")
            x,y=self._point(cx,cy,r,self.START-sweep)
            self.create_oval(x-thick*.22,y-thick*.22,x+thick*.22,y+thick*.22,
                             fill=blend(COLORS["text"],high,.7),outline="")
        text=self.fmt.format(self._shown) if self._shown is not None else str(self.value if self.value is not None else "—")
        size=max(11,round(d/px(7.2)))
        self.create_text(cx,cy-d*.03,text=text,fill=COLORS["text"],font=(FONTS["metric"][0],size,"bold"))
        if self.unit:
            self.create_text(cx,cy+d*.14,text=self.unit,fill=COLORS["muted"],font=FONTS["small"])

    def destroy(self):
        if self._job is not None:self.after_cancel(self._job)
        super().destroy()
