"""Procedural graphics shared by the landing screen and the orbit view.

Two things live here:

* ``render_earth`` — draws a shaded 3D-looking Earth with NumPy + Pillow.
  It is rendered ONCE per window size (never per animation frame) and then
  shown on a Tk canvas as a single image, so it costs nothing while the
  satellite animates.
* ``SatelliteSprite`` — a small satellite made of canvas polygons whose
  coordinates are updated every frame (moving items is cheap in Tkinter;
  deleting and re-creating them every frame would not be).
"""
from __future__ import annotations

import math
import tkinter as tk
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter

# Direction the sunlight comes from: right, slightly up, towards the viewer.
LIGHT = np.array([0.78, 0.22, 0.58])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _noise(rng: np.random.Generator, width: int, height: int, cells: tuple[int, int]) -> np.ndarray:
    """Smooth value noise: a coarse random grid upscaled with bicubic filtering."""
    coarse = (rng.random((cells[1], cells[0])) * 255).astype(np.uint8)
    image = Image.fromarray(coarse, "L").resize((width, height), Image.BICUBIC)
    return np.asarray(image, dtype=np.float32) / 255.0


def _bilinear(texture: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Sample a texture at fractional pixel positions (smooth, not blocky)."""
    h, w = texture.shape[:2]
    u0 = np.floor(u).astype(np.int32) % w
    v0 = np.clip(np.floor(v).astype(np.int32), 0, h - 1)
    u1 = (u0 + 1) % w
    v1 = np.clip(v0 + 1, 0, h - 1)
    fu, fv = u - np.floor(u), v - np.floor(v)
    if texture.ndim == 3:
        fu, fv = fu[..., None], fv[..., None]
    top = texture[v0, u0] * (1 - fu) + texture[v0, u1] * fu
    bottom = texture[v1, u0] * (1 - fu) + texture[v1, u1] * fu
    return top * (1 - fv) + bottom * fv


@lru_cache(maxsize=1)
def _earth_textures() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Equirectangular albedo, cloud and city-light maps (fixed seed, built once)."""
    width, height = 1024, 512
    rng = np.random.default_rng(2026)
    # Several octaves of low-frequency noise give believable continent shapes.
    land_noise = (_noise(rng, width, height, (9, 5)) * 0.6
                  + _noise(rng, width, height, (18, 9)) * 0.3
                  + _noise(rng, width, height, (40, 20)) * 0.1)
    land = _smoothstep(0.52, 0.56, land_noise)
    lat = np.linspace(90, -90, height)[:, None] * np.ones((1, width))
    ice = _smoothstep(68, 76, np.abs(lat))

    ocean = np.stack([
        np.full((height, width), 0.04),
        0.20 + 0.10 * (1 - np.abs(lat) / 90),
        0.42 + 0.14 * (1 - np.abs(lat) / 90),
    ], axis=-1)
    tone = _noise(rng, width, height, (30, 15))[..., None]
    green = np.array([0.20, 0.38, 0.20])
    desert = np.array([0.55, 0.47, 0.30])
    land_rgb = green * (1 - tone) + desert * tone
    albedo = ocean * (1 - land[..., None]) + land_rgb * land[..., None]
    albedo = albedo * (1 - ice[..., None]) + np.array([0.88, 0.92, 0.96]) * ice[..., None]

    clouds = (_noise(rng, width, height, (14, 7)) * 0.55
              + _noise(rng, width, height, (48, 24)) * 0.45)
    clouds = _smoothstep(0.55, 0.78, clouds) * 0.85
    # Blur the cloud map so cloud edges look soft instead of blocky.
    cloud_img = Image.fromarray((clouds * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(3))
    clouds = np.asarray(cloud_img, dtype=np.float32) / 255.0

    sparkle = rng.random((height, width)) > 0.985
    cities = (land > 0.5) & sparkle & (ice < 0.1)
    return albedo.astype(np.float32), clouds.astype(np.float32), cities.astype(np.float32)


def render_earth(diameter: int, glow: float = 0.10, rotation: float = 0.6,
                 tilt_deg: float = 18.0) -> Image.Image:
    """Return an RGBA image of a lit Earth (with atmosphere glow) ``diameter`` pixels wide.

    The returned image is ``diameter * (1 + 2*glow)`` pixels square; its centre
    is the centre of the planet. ``rotation`` spins the texture (radians).
    """
    diameter = max(8, int(diameter))
    radius = diameter / 2
    size = int(diameter * (1 + 2 * glow))
    half = size / 2
    # Pixel grid in planet units: (0, 0) is the centre, 1.0 is the surface.
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    x = (xs + 0.5 - half) / radius
    y = (half - ys - 0.5) / radius
    r2 = x * x + y * y
    r = np.sqrt(r2)
    inside = r2 < 1.0
    z = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))

    # Lambert lighting: brightness = cosine between surface normal and sunlight.
    diffuse = x * LIGHT[0] + y * LIGHT[1] + z * LIGHT[2]
    day = _smoothstep(-0.12, 0.22, diffuse)

    # Map every visible surface point to latitude/longitude, with an axial tilt.
    t = math.radians(tilt_deg)
    xt = x * math.cos(t) - y * math.sin(t)
    yt = x * math.sin(t) + y * math.cos(t)
    lat = np.arcsin(np.clip(yt, -1, 1))
    lon = np.arctan2(xt, np.maximum(z, 1e-6)) + rotation
    albedo, clouds, cities = _earth_textures()
    th, tw = clouds.shape
    u = (lon / (2 * math.pi) + 0.5) % 1.0 * (tw - 1)
    v = (0.5 - lat / math.pi) * (th - 1)
    surface = _bilinear(albedo, u, v)
    cloud = _bilinear(clouds, u, v)[..., None]
    city = _bilinear(cities, u, v)[..., None]

    light = np.clip(diffuse, 0, 1)[..., None]
    lit = surface * (0.30 + 0.85 * light)
    lit = lit * (1 - cloud) + (0.92 * (0.25 + 0.8 * light)) * cloud
    night = surface * 0.06 + city * np.array([1.0, 0.72, 0.35]) * 0.9 * (1 - cloud)
    d = day[..., None]
    rgb = night * (1 - d) + lit * d
    # Atmospheric rim: the limb looks blue because we see through more air there.
    rim = ((1 - z) ** 2.6)[..., None] * (0.25 + 0.75 * d)
    rgb = rgb * (1 - 0.55 * rim) + np.array([0.35, 0.65, 1.0]) * 0.75 * rim
    rgb = np.clip(rgb, 0, 1)

    # Anti-aliased planet edge + soft outer glow, stronger on the sunlit side.
    edge_alpha = np.clip((1.0 - r) * radius + 0.5, 0, 1)
    side = np.clip((x * LIGHT[0] + y * LIGHT[1]) / np.maximum(r, 1e-6), -1, 1)
    halo = np.clip(1 - (r - 1) / glow, 0, 1) ** 2.2 * (0.18 + 0.42 * (side * 0.5 + 0.5))
    halo = np.where(r >= 1.0, halo, 0.0)
    glow_rgb = np.array([0.38, 0.70, 1.0])

    # "Over" compositing of the planet on top of its glow.
    planet = edge_alpha[..., None]
    halo_a = (halo * (1 - edge_alpha))[..., None]
    alpha = planet + halo_a
    color = (rgb * planet + glow_rgb * halo_a) / np.maximum(alpha, 1e-6)
    out = np.dstack([np.clip(color, 0, 1) * 255, alpha[..., 0] * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


class SatelliteSprite:
    """A tiny satellite (body, two solar wings, nadir antenna) drawn on a canvas.

    ``place(x, y, heading_deg, radial_deg)`` rotates it so the wings lie along
    the direction of travel and the antenna points towards the Earth.
    """

    BODY = "#D9DEE7"
    BODY_EDGE = "#8C96A6"
    PANEL = "#1D4F9C"
    PANEL_EDGE = "#6FA8FF"

    def __init__(self, canvas: tk.Canvas, scale: float = 1.0) -> None:
        self.canvas = canvas
        self.s = scale
        width = max(1, round(scale))
        self.strut = canvas.create_line(0, 0, 0, 0, fill="#8C96A6", width=width)
        self.panels = [canvas.create_polygon(0, 0, 0, 0, fill=self.PANEL, outline=self.PANEL_EDGE, width=1)
                       for _ in range(2)]
        self.dividers = [canvas.create_line(0, 0, 0, 0, fill=self.PANEL_EDGE, width=1) for _ in range(2)]
        self.antenna = canvas.create_line(0, 0, 0, 0, fill="#C9D1DC", width=width)
        self.body = canvas.create_polygon(0, 0, 0, 0, fill=self.BODY, outline=self.BODY_EDGE, width=1)
        self.light = canvas.create_oval(0, 0, 0, 0, fill="#64D2FF", outline="")

    def items(self) -> list[int]:
        return [self.strut, *self.panels, *self.dividers, self.antenna, self.body, self.light]

    def place(self, x: float, y: float, heading_deg: float, blink: bool = True) -> None:
        """Move the sprite. ``heading_deg`` is the travel direction in canvas degrees."""
        a = math.radians(heading_deg)
        ux, uy = math.cos(a), math.sin(a)          # along track (wings)
        nx, ny = -uy, ux                           # cross track (antenna side)
        s = self.s

        def pt(u: float, v: float) -> tuple[float, float]:
            return x + (u * ux + v * nx) * s, y + (u * uy + v * ny) * s

        def rect(u1: float, u2: float, v1: float, v2: float) -> list[float]:
            return [c for p in (pt(u1, v1), pt(u2, v1), pt(u2, v2), pt(u1, v2)) for c in p]

        c = self.canvas
        c.coords(self.strut, *pt(-20, 0), *pt(20, 0))
        c.coords(self.panels[0], *rect(-23, -9, -5.5, 5.5))
        c.coords(self.panels[1], *rect(9, 23, -5.5, 5.5))
        c.coords(self.dividers[0], *pt(-16, -5.5), *pt(-16, 5.5))
        c.coords(self.dividers[1], *pt(16, -5.5), *pt(16, 5.5))
        c.coords(self.body, *rect(-5.5, 5.5, -5.5, 5.5))
        c.coords(self.antenna, *pt(0, 5.5), *pt(0, 12))
        lx, ly = pt(0, 12.5)
        r = 1.8 * s
        c.coords(self.light, lx - r, ly - r, lx + r, ly + r)
        c.itemconfigure(self.light, state="normal" if blink else "hidden")
