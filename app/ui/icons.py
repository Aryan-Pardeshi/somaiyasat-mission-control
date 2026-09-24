"""Resolution-independent canvas icons and the SomaiyaSat orbit mark."""
from __future__ import annotations

import math
import tkinter as tk

from .theme import COLORS, blend, px


def draw_icon(canvas: tk.Canvas, name: str, x: float, y: float,
              size: float, color: str) -> list[int]:
    """Draw a centred navigation icon and return its canvas item IDs."""
    ids: list[int] = []
    s = size / 2
    line = max(1, px(1.8))
    def path(points, **kw):
        ids.append(canvas.create_line(*points, fill=color, width=line,
                                      capstyle="round", joinstyle="round", **kw))
    def oval(a,b,c,d, **kw):
        ids.append(canvas.create_oval(a,b,c,d, outline=color, width=line, **kw))
    name = name.lower()
    if name == "overview":
        for dx in (-.48, .12):
            for dy in (-.48, .12):
                ids.append(canvas.create_rectangle(x+dx*s*2,y+dy*s*2,
                    x+(dx+.36)*s*2,y+(dy+.36)*s*2,outline=color,width=line))
    elif name == "telemetry":
        path([x-s,y,x-.55*s,y,x-.33*s,y+.4*s,x-.05*s,y-.55*s,
              x+.2*s,y+.18*s,x+.42*s,y,x+s,y])
    elif name == "router":
        path([x-.65*s,y,x,y,x+.55*s,y-.55*s]); path([x,y,x+.55*s,y+.55*s])
        for a,b in ((-.65,0),(.55,-.55),(.55,.55)):
            oval(x+a*s-px(2),y+b*s-px(2),x+a*s+px(2),y+b*s+px(2))
    elif name == "communications":
        path([x,y+.75*s,x,y-.2*s]); oval(x-px(2),y-.35*s,x+px(2),y-.2*s)
        for extent in (.55,.9):
            ids.append(canvas.create_arc(x-extent*s,y-extent*s,x+extent*s,y+extent*s,
                start=30,extent=120,style="arc",outline=color,width=line))
    elif name == "incidents":
        ids.append(canvas.create_polygon(x,y-.85*s,x+.86*s,y+.7*s,x-.86*s,y+.7*s,
                                         fill="",outline=color,width=line))
        path([x,y-.3*s,x,y+.18*s]); oval(x-px(1),y+.38*s,x+px(1),y+.4*s,fill=color)
    elif name == "analytics":
        for i,h in enumerate((.38,.8,.58)):
            a=x+(-.7+i*.58)*s
            ids.append(canvas.create_rectangle(a,y+.75*s-h*s,a+.35*s,y+.75*s,
                                                fill=color,outline=""))
    elif name == "archive":
        oval(x-.7*s,y-.75*s,x+.7*s,y-.25*s)
        path([x-.7*s,y-.5*s,x-.7*s,y+.65*s]); path([x+.7*s,y-.5*s,x+.7*s,y+.65*s])
        ids.append(canvas.create_arc(x-.7*s,y+.4*s,x+.7*s,y+.9*s,start=180,extent=180,
                                     style="arc",outline=color,width=line))
        path([x-.7*s,y+.05*s,x+.7*s,y+.05*s])
    elif name == "about":
        oval(x-.8*s,y-.8*s,x+.8*s,y+.8*s)
        path([x,y-.05*s,x,y+.5*s]); oval(x-px(1),y-.48*s,x+px(1),y-.46*s,fill=color)
    elif name == "satellite":
        ids.append(canvas.create_rectangle(x-.2*s,y-.2*s,x+.2*s,y+.2*s,
                                            fill=color,outline=""))
        for sign in (-1,1):
            a=x+sign*.35*s
            ids.append(canvas.create_rectangle(a-.16*s,y-.28*s,a+.16*s,y+.28*s,
                                                outline=color,width=line))
            path([x+sign*.2*s,y,x+sign*.35*s,y])
    return ids


def draw_logo(canvas: tk.Canvas, cx: float, cy: float, size: float,
              accent: str = COLORS["cyan"]) -> list[int]:
    """Draw the orbit and S monogram as movable canvas primitives."""
    ids: list[int] = []
    r = size / 2
    ids.append(canvas.create_oval(cx-r,cy-r,cx+r,cy+r,outline=blend(accent,COLORS["border"],.48),
                                  width=max(1,px(1.2))))
    for i in range(7,0,-1):
        rr = r*(.77 + i*.018)
        ids.append(canvas.create_oval(cx-rr,cy-rr,cx+rr,cy+rr,fill=blend(accent,COLORS["bg"],.035+i*.005),outline=""))
    points=[]
    theta=math.radians(-28)
    for k in range(73):
        t=math.tau*k/72
        a,b=r*.95*math.cos(t),r*.39*math.sin(t)
        points.extend((cx+a*math.cos(theta)-b*math.sin(theta),
                       cy+a*math.sin(theta)+b*math.cos(theta)))
    ids.append(canvas.create_line(*points,fill=blend(accent,COLORS["text"],.72),
                                  width=max(1,px(1.25)),smooth=True))
    t=math.radians(332)
    a,b=r*.95*math.cos(t),r*.39*math.sin(t)
    sx,sy=cx+a*math.cos(theta)-b*math.sin(theta),cy+a*math.sin(theta)+b*math.cos(theta)
    for k in (3,2,1):
        gr=r*(.035+.03*k)
        ids.append(canvas.create_oval(sx-gr,sy-gr,sx+gr,sy+gr,
                       fill=blend(accent,COLORS["bg"],.08*k),outline=""))
    dot=max(px(2),r*.047)
    ids.append(canvas.create_oval(sx-dot,sy-dot,sx+dot,sy+dot,fill=COLORS["text"],outline=""))
    # Two restrained arcs read as an S even at sidebar size.
    ids.append(canvas.create_arc(cx-r*.34,cy-r*.37,cx+r*.29,cy+r*.04,
              start=30,extent=245,style="arc",outline=COLORS["text"],width=max(2,px(size*.055))))
    ids.append(canvas.create_arc(cx-r*.29,cy-r*.03,cx+r*.34,cy+r*.38,
              start=210,extent=245,style="arc",outline=COLORS["text"],width=max(2,px(size*.055))))
    return ids
