"""Animated 2D orbit display, independent of the simulation implementation."""
from __future__ import annotations

import math
import random
import tkinter as tk
from typing import Callable

from app import config
from .theme import COLORS, FONTS, blend, px


class OrbitView(tk.Canvas):
    """Poll a degree-valued angle provider; feed labels via ``update_state``."""

    def __init__(self,parent,angle_provider: Callable[[],float],bg=COLORS["card"],**kw):
        super().__init__(parent,bg=bg,highlightthickness=0,bd=0,**kw)
        self.angle_provider=angle_provider
        self.pass_info:dict|None=None
        self.snapshot:dict|None=None
        self.transmitting_mode:str|None=None
        self._job=None
        self._running=False
        self._items={}
        self._trail=[]
        self._pulse_phase=0.
        self.bind("<Configure>",self._build)

    def update_state(self,pass_info:dict|None,snapshot:dict|None,
                     transmitting_mode:str|None):
        self.pass_info=pass_info
        self.snapshot=snapshot
        self.transmitting_mode=transmitting_mode
        self._labels()

    def start(self):
        if not self._running:
            self._running=True
            self._tick()

    def stop(self):
        self._running=False
        if self._job is not None:
            self.after_cancel(self._job)
            self._job=None

    def destroy(self):
        self.stop()
        super().destroy()

    def _point(self,angle,radius):
        a=math.radians(angle)
        return self.cx+radius*math.cos(a),self.cy-radius*math.sin(a)

    def _build(self,_=None):
        w,h=self.winfo_width(),self.winfo_height()
        if w<px(150) or h<px(150):return
        self.delete("all")
        self._items={}
        self.cx,self.cy=w*.52,h*.52
        self.earth_r=min(w,h)*.225
        self.orbit_r=self.earth_r*1.92
        rng=random.Random(1047)
        # Static points use a fixed seed, preventing distracting jumps on resize.
        for _ in range(75):
            x,y=rng.randrange(w),rng.randrange(h)
            if (x-self.cx)**2+(y-self.cy)**2 < (self.orbit_r*.9)**2:continue
            d=px(.8 if rng.random()<.75 else 1.25)
            self.create_oval(x-d,y-d,x+d,y+d,fill=blend(COLORS["text"],self.cget("bg"),
                             rng.uniform(.17,.48)),outline="")
        r=self.earth_r
        for i in range(6,0,-1):
            rr=r*(1+i*.10)
            self.create_oval(self.cx-rr,self.cy-rr,self.cx+rr,self.cy+rr,
                fill=blend(COLORS["blue"],self.cget("bg"),.018+(7-i)*.006),outline="")
        self.create_oval(self.cx-r,self.cy-r,self.cx+r,self.cy+r,
                         fill="#123C63",outline=blend(COLORS["cyan"],"#123C63",.35),width=max(1,px(1)))
        self.create_arc(self.cx-r,self.cy-r,self.cx+r,self.cy+r,start=90,extent=180,
                        style="pieslice",fill="#0C263F",outline="")
        # Simplified continental silhouettes remain inside the Earth disc.
        for pts in (
            [(-.48,-.30),(-.26,-.54),(.05,-.47),(.14,-.24),(-.02,-.08),(-.11,.12),(-.37,.20),(-.50,-.05)],
            [(.18,-.11),(.41,-.19),(.59,.02),(.52,.31),(.29,.47),(.15,.25)],
            [(-.18,.38),(.03,.34),(.15,.58),(-.06,.68),(-.25,.54)],
        ):
            coords=[v for a,b in pts for v in (self.cx+a*r,self.cy+b*r)]
            self.create_polygon(*coords,fill="#22556B",outline="",smooth=True)
        grid=blend(COLORS["cyan"],"#123C63",.12)
        for factor in (.30,.64):
            self.create_oval(self.cx-r*factor,self.cy-r,self.cx+r*factor,self.cy+r,
                             outline=grid,width=max(1,px(1)))
        for factor in (-.48,0,.48):
            y=self.cy+r*factor
            width=r*math.sqrt(1-factor*factor)
            self.create_line(self.cx-width,y,self.cx+width,y,fill=grid,width=max(1,px(1)))
        self.create_oval(self.cx-self.orbit_r,self.cy-self.orbit_r,
                         self.cx+self.orbit_r,self.cy+self.orbit_r,
                         outline=COLORS["border_hi"],dash=(px(3),px(7)),width=max(1,px(1)))
        half=180*config.PASS_DURATION/config.ORBIT_PERIOD
        self.create_arc(self.cx-self.orbit_r,self.cy-self.orbit_r,
                        self.cx+self.orbit_r,self.cy+self.orbit_r,
                        start=config.GROUND_STATION_ANGLE-half,extent=2*half,
                        style="arc",outline=blend(COLORS["cyan"],self.cget("bg"),.42),
                        width=max(1,px(3)))
        self.gx,self.gy=self._point(config.GROUND_STATION_ANGLE,r*.99)
        self.create_oval(self.gx-px(6),self.gy-px(6),self.gx+px(6),self.gy+px(6),
                         fill=blend(COLORS["cyan"],self.cget("bg"),.22),outline="")
        self.create_oval(self.gx-px(2.5),self.gy-px(2.5),self.gx+px(2.5),self.gy+px(2.5),
                         fill=COLORS["cyan"],outline="")
        self.create_text(self.gx+px(10),self.gy-px(7),text="KJSCE GS",fill=COLORS["text_2"],
                         font=FONTS["caption"],anchor="sw")
        # Animated IDs are created once per size change; frames only update coords.
        self._items["beam_glow"]=self.create_line(0,0,0,0,fill=COLORS["cyan"],width=px(7),state="hidden")
        self._items["beam"]=self.create_line(0,0,0,0,fill=COLORS["cyan"],width=px(1.5),
                                              dash=(px(5),px(5)),state="hidden")
        self._items["link_down"]=self.create_text(0,0,text="LINK DOWN",fill=COLORS["red"],
                                                 font=FONTS["caption"],state="hidden")
        self._items["pulse"]=[]
        for _ in range(2):
            self._items["pulse"].append(self.create_oval(0,0,0,0,outline=COLORS["cyan"],
                                                    width=max(1,px(1)),state="hidden"))
        self._items["trail"]=[]
        for i in range(9):
            color=blend(COLORS["cyan"],self.cget("bg"),.08+.50*(i/8))
            self._items["trail"].append(self.create_oval(0,0,0,0,fill=color,outline=""))
        for name in ("left_panel","body","right_panel"):
            self._items[name]=self.create_polygon(0,0,0,0,fill=COLORS["blue"] if name!="body" else COLORS["text"],outline="")
        self._items["sat_label"]=self.create_text(0,0,text="SOMAIYASAT",fill=COLORS["text"],
                                                   font=FONTS["caption"],anchor="sw")
        self._items["title"]=self.create_text(px(22),px(20),anchor="nw",text="ORBIT VIEW",
                                               fill=COLORS["muted"],font=FONTS["caption"])
        for name,y,anchor in (("phase",px(42),"nw"),("downlink",h-px(20),"sw"),("pass",h-px(20),"se")):
            x=w-px(22) if anchor=="se" else px(22)
            self._items[name]=self.create_text(x,y,anchor=anchor,
                fill=COLORS["text_2"],font=FONTS["small"] if name=="phase" else FONTS["caption"])
        self._labels()
        self._draw_frame(self.angle_provider())

    def _labels(self):
        if not self._items:return
        info=self.pass_info or {}
        phase=str(info.get("phase","PRE-PASS"))
        seconds=info.get("seconds_to_los",0) if info.get("in_pass") else info.get("seconds_to_aos",0)
        label="LOS IN" if info.get("in_pass") else "NEXT AOS IN"
        minutes,secs=divmod(max(0,int(seconds)),60)
        self.itemconfigure(self._items["phase"],text=f"{phase} · {label} {minutes:02d}:{secs:02d}")
        self.itemconfigure(self._items["downlink"],text=f"DOWNLINK: {self.transmitting_mode or 'IDLE'}")
        sun="SUNLIT" if info.get("sunlit",True) else "ECLIPSE"
        self.itemconfigure(self._items["pass"],text=f"PASS #{info.get('pass_number',1)} · {sun}")

    def _poly(self,center_x,center_y,normal,tangent,along,across):
        out=[]
        for u,v in ((-along,-across),(along,-across),(along,across),(-along,across)):
            out.extend((center_x+u*tangent[0]+v*normal[0],
                        center_y+u*tangent[1]+v*normal[1]))
        return out

    def _draw_frame(self,angle):
        if not self._items:return
        x,y=self._point(angle,self.orbit_r)
        radians=math.radians(angle)
        tangent=(-math.sin(radians),-math.cos(radians))
        normal=(math.cos(radians),-math.sin(radians))
        gap=px(10)
        for name,offset in (("left_panel",-px(15)),("right_panel",px(15))):
            cx=x+offset*tangent[0];cy=y+offset*tangent[1]
            self.coords(self._items[name],*self._poly(cx,cy,normal,tangent,px(6),px(5)))
        self.coords(self._items["body"],*self._poly(x,y,normal,tangent,px(5),px(6)))
        self.coords(self._items["sat_label"],x+px(13),y-px(12))
        self._trail.append(angle)
        self._trail=self._trail[-9:]
        for index,item in enumerate(self._items["trail"]):
            past=self._trail[max(0,len(self._trail)-9+index)]
            tx,ty=self._point(past,self.orbit_r)
            rr=px(1.1+index*.11)
            self.coords(item,tx-rr,ty-rr,tx+rr,ty+rr)
        info=self.pass_info or {}
        connected=bool(info.get("in_pass"))
        for name in ("beam_glow","beam"):
            self.itemconfigure(self._items[name],state="normal" if connected else "hidden")
        if connected:
            weak=(self.snapshot or {}).get("signal",100)<35
            down=(self.snapshot or {}).get("comm_state")=="LINK DOWN" or (self.snapshot or {}).get("system_state")=="COMMUNICATION_LOSS"
            color=COLORS["red"] if down else COLORS["amber"] if weak else COLORS["cyan"]
            self.coords(self._items["beam_glow"],self.gx,self.gy,x,y)
            self.coords(self._items["beam"],self.gx,self.gy,x,y)
            self.itemconfigure(self._items["beam_glow"],fill=blend(color,self.cget("bg"),.14))
            self.itemconfigure(self._items["beam"],fill=color)
            self.itemconfigure(self._items["link_down"],state="normal" if down else "hidden")
            self.coords(self._items["link_down"],(self.gx+x)/2,(self.gy+y)/2-px(13))
            self._pulse_phase=(self._pulse_phase+.035)%1.
            for index,item in enumerate(self._items["pulse"]):
                phase=(self._pulse_phase+index*.5)%1
                radius=px(4)+px(22)*phase
                self.coords(item,self.gx-radius,self.gy-radius,self.gx+radius,self.gy+radius)
                self.itemconfigure(item,state="normal",outline=blend(color,self.cget("bg"),.35*(1-phase)))
        else:
            self.itemconfigure(self._items["link_down"],state="hidden")
            for item in self._items["pulse"]:self.itemconfigure(item,state="hidden")

    def _tick(self):
        try:self._draw_frame(float(self.angle_provider()))
        except (TypeError,ValueError):pass
        self._job=self.after(config.ORBIT_FRAME_MS,self._tick) if self._running else None
