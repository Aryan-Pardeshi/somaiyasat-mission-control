"""Cinematic entry screen with an optional looping video and painted fallback."""
from __future__ import annotations

import logging
import math
from pathlib import Path
import random
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from app import config
from .graphics import SatelliteSprite, render_earth
from .icons import draw_logo
from .theme import COLORS, FONTS, blend, px
from .components import rounded_rect

LOG = logging.getLogger(__name__)
DEFAULT_STEPS = (
    "INITIALIZING TELEMETRY BUS...", "POWER SYSTEM ONLINE", "RF STACK READY",
    "ROUTING ENGINE READY", "GROUND STATION LINK READY",
)


class LandingPage(tk.Frame):
    """Run a small intro timeline; ``start`` and ``stop`` own all timers/video."""

    def __init__(self,parent,on_enter:Callable[[],None],video_path=config.VIDEO_PATH,
                 init_steps:list[tuple[str,Callable|None]]|None=None):
        super().__init__(parent,bg=COLORS["bg"])
        self.on_enter=on_enter
        self.video_path=Path(video_path)
        self.init_steps=list(init_steps) if init_steps is not None else [(s,None) for s in DEFAULT_STEPS]
        self.canvas=tk.Canvas(self,bg=COLORS["bg"],highlightthickness=0,bd=0)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",self._build)
        self.canvas.bind("<Motion>",self._motion)
        self.canvas.bind("<Button-1>",self._click)
        self.bind_all("<Return>",self._enter_key,add="+")
        self._jobs:set[str]=set()
        self._running=False
        self._video=None
        self._cv2=None
        self._np=None
        self._photo=None
        self._video_item=None
        self._vignette=None
        self._stars=[]
        self._step_index=0
        self._step_results=[]
        self._typed=""
        self._line_ids=[]
        self._step_status=[]
        self._ready=False
        self._button_hot=False
        self._button_box=(0,0,0,0)
        self._sat_sprite=None
        self._earth_photo=None   # reference kept so Tk does not drop the image
        self._earth_size=None
        self._orbit=(0,0,1,1)
        self._frames=0

    def _after(self,ms,callback):
        holder=[None]
        def wrapped():
            self._jobs.discard(holder[0])
            if self._running:callback()
        holder[0]=self.after(ms,wrapped)
        self._jobs.add(holder[0])

    def start(self):
        if self._running:return
        self._running=True
        self._open_video()
        self._build()
        self._after(400,self._next_step)
        self._animate()

    def stop(self):
        self._running=False
        for job in tuple(self._jobs):
            self.after_cancel(job)
        self._jobs.clear()
        if self._video is not None:
            self._video.release()
            self._video=None
        self._photo=None

    def destroy(self):
        self.stop()
        self.unbind_all("<Return>")
        super().destroy()

    def _open_video(self):
        if not self.video_path.exists():return
        try:
            import cv2
            import numpy as np
            capture=cv2.VideoCapture(str(self.video_path))
            if not capture.isOpened():
                capture.release()
                return
            self._cv2,self._np,self._video=cv2,np,capture
        except Exception:
            LOG.exception("Landing video unavailable; switching to painted scene")
            self._video=None

    def _fallback(self):
        self._video=None
        self._photo=None
        self._build()

    def _build(self,_=None):
        w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
        if w<20 or h<20:return
        c=self.canvas
        c.delete("all")
        self._stars=[]
        self._line_ids=[]
        self._step_status=[]
        if self._video is not None:
            self._video_item=c.create_image(0,0,anchor="nw")
            if self._photo is not None:c.itemconfigure(self._video_item,image=self._photo)
            self._vignette=None
        else:
            self._video_item=None
            # Broad horizontal bands create a low-key sky without per-frame images.
            for i in range(45):
                top=round(h*i/45);bottom=round(h*(i+1)/45)+1
                color=blend("#17283E",COLORS["bg"],.16*(i/44))
                c.create_rectangle(0,top,w,bottom,fill=color,outline="")
            rng=random.Random(714)
            for layer,count in enumerate((75,62,43)):
                for _ in range(count):
                    x=rng.randrange(w);y=rng.randrange(h)
                    r=px(.55+layer*.35)
                    item=c.create_oval(x-r,y-r,x+r,y+r,fill=blend(COLORS["text"],COLORS["bg"],.22+layer*.13),outline="")
                    self._stars.append((item,x,y,r,layer,rng.random()*math.tau))
            ex,ey=w*.82,h*1.17
            er=min(w,h)*.47
            # Shaded Earth rendered once per size with NumPy/Pillow (graphics.py).
            # Rendered at reduced resolution and upscaled: it is soft anyway and
            # this keeps the landing animation from stuttering on resize.
            size=int(2*er)
            if self._earth_size!=size:
                small=render_earth(max(64,int(size/1.6)),glow=.07,rotation=2.2)
                full=int(small.width*1.6)
                self._earth_photo=ImageTk.PhotoImage(small.resize((full,full),Image.BICUBIC))
                self._earth_size=size
            c.create_image(ex,ey,image=self._earth_photo)
            # The satellite flies along exactly this ellipse (see _fallback_frame).
            self._orbit=(w*.64,h*.70,w*.54,h*.57)
            ox,oy,rx,ry=self._orbit
            c.create_oval(ox-rx,oy-ry,ox+rx,oy+ry,outline=blend(COLORS["cyan"],COLORS["bg"],.20),width=max(1,px(1)))
            self._sat_sprite=SatelliteSprite(c,scale=max(1.,px(1.25)))
        # Text is drawn after the scene so a darkened video stays behind it.
        logo_y=h*.19
        draw_logo(c,w*.5,logo_y,min(px(110),h*.145))
        c.create_text(w*.5,h*.315,text="S O M A I Y A S A T",fill=COLORS["text"],font=FONTS["display"])
        c.create_text(w*.5,h*.376,text="MISSION CONTROL",fill=COLORS["cyan"],font=FONTS["title"])
        c.create_text(w*.5,h*.427,text=config.APP_SUBTITLE,fill=COLORS["text_2"],font=FONTS["body"])
        # Five short lines fit even at 1366 x 768; centre them as a single quiet block.
        line_gap=min(px(30),h*.038)
        first_y=h*.51
        for i,(_,_) in enumerate(self.init_steps):
            y=first_y+i*line_gap
            self._line_ids.append(c.create_text(w*.5-px(182),y,anchor="w",text="",
                          fill=COLORS["text_2"],font=FONTS["mono"]))
            self._step_status.append(c.create_text(w*.5+px(205),y,anchor="e",text="",
                          fill=COLORS["green"],font=FONTS["caption"]))
        self._ready_id=c.create_text(w*.5,first_y+len(self.init_steps)*line_gap+px(7),
                     text="SYSTEM READY" if self._ready else "",fill=COLORS["green"],font=FONTS["caption"])
        self._button_box=(w*.5-px(143),h*.82-px(22),w*.5+px(143),h*.82+px(22))
        self._button_id=rounded_rect(c,*self._button_box,px(20),
                      fill=COLORS["blue"] if self._ready else blend(COLORS["blue"],COLORS["bg"],.07),outline="")
        self._button_text=c.create_text(w*.5,h*.82,text="ENTER MISSION CONTROL" if self._ready else "",
                                        fill=COLORS["text"],font=FONTS["body_bold"])
        c.create_text(w*.5,h-px(26),text="Educational digital twin · not connected to real spacecraft",
                      fill=COLORS["muted"],font=FONTS["small"])
        for i in range(min(self._step_index,len(self.init_steps))):
            c.itemconfigure(self._line_ids[i],text=self.init_steps[i][0])
            degraded=self._step_results[i]
            c.itemconfigure(self._step_status[i],text="DEGRADED" if degraded else "OK",
                            fill=COLORS["amber"] if degraded else COLORS["green"])
        if self._step_index<len(self.init_steps) and self._typed:
            c.itemconfigure(self._line_ids[self._step_index],text=self._typed)
        self._paint_button()

    def _next_step(self):
        if self._step_index>=len(self.init_steps):
            self._ready=True
            self.canvas.itemconfigure(self._ready_id,text="SYSTEM READY")
            self.canvas.itemconfigure(self._button_text,text="ENTER MISSION CONTROL")
            self._paint_button()
            return
        label,action=self.init_steps[self._step_index]
        self._typed=""
        degraded=False
        if action is not None:
            try:action()
            except Exception:
                LOG.exception("Landing init step failed: %s",label)
                degraded=True
        self._degraded=degraded
        self._type_char()

    def _type_char(self):
        label,_=self.init_steps[self._step_index]
        self._typed=label[:len(self._typed)+2]
        self.canvas.itemconfigure(self._line_ids[self._step_index],text=self._typed)
        if len(self._typed)<len(label):
            self._after(18,self._type_char)
        else:
            self.canvas.itemconfigure(self._step_status[self._step_index],
                                      text="DEGRADED" if self._degraded else "OK",
                                      fill=COLORS["amber"] if self._degraded else COLORS["green"])
            self._step_results.append(self._degraded)
            self._step_index+=1
            self._typed=""
            self._after(390,self._next_step)

    def _paint_button(self):
        if not hasattr(self,"_button_id"):return
        color=blend(COLORS["text"],COLORS["blue"],.14) if self._button_hot else COLORS["blue"]
        if not self._ready:color=blend(COLORS["blue"],COLORS["bg"],.07)
        self.canvas.itemconfigure(self._button_id,fill=color)
        self.canvas.configure(cursor="hand2" if self._ready and self._button_hot else "arrow")

    def _motion(self,event):
        x1,y1,x2,y2=self._button_box
        hot=self._ready and x1<=event.x<=x2 and y1<=event.y<=y2
        if hot!=self._button_hot:
            self._button_hot=hot
            self._paint_button()

    def _click(self,event):
        x1,y1,x2,y2=self._button_box
        if self._ready and x1<=event.x<=x2 and y1<=event.y<=y2:self.on_enter()

    def _enter_key(self,_):
        if self._ready and self._running:self.on_enter()

    def _animate(self):
        if self._video is not None:self._video_frame()
        else:self._fallback_frame()
        self._frames+=1
        self._after(40,self._animate)

    def _fallback_frame(self):
        c=self.canvas
        w,h=c.winfo_width(),c.winfo_height()
        for item,x,y,r,layer,phase in self._stars:
            nx=(x-self._frames*(.12+layer*.09))%w
            c.coords(item,nx-r,y-r,nx+r,y+r)
            if self._frames%5==0:
                alpha=.22+layer*.13+.08*math.sin(self._frames*.07+phase)
                c.itemconfigure(item,fill=blend(COLORS["text"],COLORS["bg"],alpha))
        if self._sat_sprite is not None:
            ox,oy,rx,ry=self._orbit
            t=self._frames*.006
            x=ox+math.cos(t)*rx
            y=oy-math.sin(t)*ry
            # Heading = direction of motion along the ellipse (derivative of x, y).
            heading=math.degrees(math.atan2(-math.cos(t)*ry,-math.sin(t)*rx))
            self._sat_sprite.place(x,y,heading+180,blink=self._frames%24<12)

    def _video_frame(self):
        try:
            ok,frame=self._video.read()
            if not ok:
                self._video.set(self._cv2.CAP_PROP_POS_FRAMES,0)
                ok,frame=self._video.read()
                if not ok:raise RuntimeError("video has no readable frames")
            w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
            if w<2 or h<2:return
            frame=self._cv2.resize(frame,(w,h),interpolation=self._cv2.INTER_LINEAR)
            rgb=self._cv2.cvtColor(frame,self._cv2.COLOR_BGR2RGB)
            if self._vignette is None or self._vignette.shape[:2]!=(h,w):
                yy,xx=self._np.ogrid[-1:1:complex(h),-1:1:complex(w)]
                self._vignette=(.45*(1-.20*self._np.minimum(1,xx*xx+yy*yy))).astype("float32")
            rgb=(rgb*self._vignette[...,None]).astype("uint8")
            picture=Image.fromarray(rgb)
            if self._photo is None or self._photo.width()!=w or self._photo.height()!=h:
                self._photo=ImageTk.PhotoImage(picture)
                self.canvas.itemconfigure(self._video_item,image=self._photo)
            else:self._photo.paste(picture)
        except Exception:
            LOG.exception("Landing video read failed; switching to painted scene")
            if self._video is not None:self._video.release()
            self._fallback()
