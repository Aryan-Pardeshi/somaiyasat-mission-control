"""Build and load a small deterministic SSTV test card for mission replay."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, UnidentifiedImageError

# Direct script execution needs the repository root to import app.config.
if __package__ in (None, ""):
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from app import config

_LOGGER = logging.getLogger(__name__)
_SEED = 36036


def _font(size: int) -> ImageFont.ImageFont:
    """Ask Pillow for a sized default font, while supporting older Pillow too."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _smooth_noise(
    rng: np.random.Generator,
    width: int,
    height: int,
    cell_size: int = 24,
    blur: float = 0.0,
) -> np.ndarray:
    """Return broad, smoothly interpolated noise for geography and weather."""
    coarse = rng.integers(
        0, 256,
        size=(max(3, height // cell_size), max(3, width // cell_size)),
        dtype=np.uint8,
    )
    field = Image.fromarray(coarse, mode="L").resize(
        (width, height), Image.Resampling.BICUBIC
    )
    if blur:
        field = field.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(field, dtype=np.float32) / 255.0


def build_sstv_test_image(width: int = 320, height: int = 256) -> Image.Image:
    """Return a calm, repeatable SSTV view of Earth's curved limb from orbit."""
    if width < 80 or height < 80:
        raise ValueError("SSTV test images need width and height of at least 80 pixels")
    rng = np.random.default_rng(_SEED)
    y, x = np.mgrid[0:height, 0:width]
    vertical = np.clip(y / max(height - 1, 1), 0.0, 1.0)

    # A very dark vertical gradient leaves most of the frame open as space.
    scene = np.empty((height, width, 3), dtype=np.uint8)
    scene[:, :, 0] = 2 + (3 * vertical).astype(np.uint8)
    scene[:, :, 1] = 4 + (8 * vertical).astype(np.uint8)
    scene[:, :, 2] = 14 + (21 * vertical).astype(np.uint8)
    image = Image.fromarray(scene, mode="RGB")

    # The broad ellipse makes the limb enter around 45% down the frame.
    cx, cy = width * 0.50, height * 2.0
    rx, ry = width * 1.62, height * 1.55
    nx = (x - cx) / rx
    ny = (y - cy) / ry
    radius = np.sqrt(nx * nx + ny * ny)
    earth_mask = radius <= 1.0
    center_light = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(radius * radius, 1.0)))
    sun = 0.80 + 0.20 * (1.0 - x / max(width - 1, 1))
    light = np.clip((0.28 + 0.72 * center_light ** 0.75) * sun, 0.0, 1.0)
    ocean_variation = (_smooth_noise(rng, width, height, 46, 6.0) - 0.5) * 5.0

    ocean = np.empty((height, width, 4), dtype=np.uint8)
    ocean[:, :, 0] = np.clip(4 + 23 * light + ocean_variation, 0, 255).astype(np.uint8)
    ocean[:, :, 1] = np.clip(25 + 78 * light + ocean_variation, 0, 255).astype(np.uint8)
    ocean[:, :, 2] = np.clip(61 + 123 * light + ocean_variation, 0, 255).astype(np.uint8)
    ocean_alpha = np.clip((1.0 - radius) * min(rx, ry) + 0.5, 0, 1)
    ocean[:, :, 3] = (ocean_alpha * 255).astype(np.uint8)
    image = Image.alpha_composite(image.convert("RGBA"), Image.fromarray(ocean, mode="RGBA"))

    # Four broad regions get gently ragged coastlines from low-frequency noise.
    land_noise = _smooth_noise(rng, width, height, 34, 7.0)
    continent_score = np.full((height, width), -1.0, dtype=np.float32)
    continents = (
        (0.12, 0.68, 0.080, 0.115),
        (0.34, 0.75, 0.112, 0.155),
        (0.62, 0.65, 0.145, 0.145),
        (0.87, 0.75, 0.086, 0.125),
    )
    for index, (land_x, land_y, land_rx, land_ry) in enumerate(continents):
        u = (x / width - land_x) / land_rx
        v = (y / height - land_y) / land_ry
        angle = np.arctan2(v, u)
        radial_noise = (
            0.12 * np.sin(2.0 * angle + index * 0.7)
            + 0.08 * np.cos(3.0 * angle - index * 0.9)
            + 0.05 * np.sin(5.0 * angle + index * 0.4)
        )
        dist = np.sqrt(u * u + v * v)
        continent_score = np.maximum(continent_score, 1.0 - dist + radial_noise)
    land_mask = earth_mask & ((continent_score + (land_noise - 0.5) * 0.62) > 0.0)

    # Muted greens and warm highlands carry only broad internal variation.
    land_variation = _smooth_noise(rng, width, height, 28, 5.0)
    land_color = np.empty((height, width, 4), dtype=np.uint8)
    tan_mix = np.clip((land_variation - 0.39) * 1.40, 0.0, 0.62)
    land_shade = (0.72 + 0.28 * sun) * (0.84 + 0.16 * center_light)
    land_color[:, :, 0] = np.clip((75 + 60 * tan_mix + 27 * (land_variation - 0.5)) * land_shade, 0, 255).astype(np.uint8)
    land_color[:, :, 1] = np.clip((97 + 29 * tan_mix + 29 * (land_variation - 0.5)) * land_shade, 0, 255).astype(np.uint8)
    land_color[:, :, 2] = np.clip((61 + 17 * tan_mix + 18 * (land_variation - 0.5)) * land_shade, 0, 255).astype(np.uint8)
    soft_land = Image.fromarray((land_mask * 255).astype(np.uint8), mode="L").filter(
        ImageFilter.GaussianBlur(1.25)
    )
    land_color[:, :, 3] = np.asarray(soft_land, dtype=np.uint8)
    image = Image.alpha_composite(image, Image.fromarray(land_color, mode="RGBA"))

    # Broad, warped noise and a few smooth bands form translucent cloud swirls.
    cloud_a = _smooth_noise(rng, width, height, 18, 4.0)
    cloud_b = _smooth_noise(rng, width, height, 36, 7.0)
    warp_x = x + 18.0 * np.sin(y / 38.0) + 8.0 * np.sin(y / 19.0 + x / 80.0)
    warp_y = y + 12.0 * np.sin(x / 48.0) + 6.0 * np.sin(x / 25.0 - y / 60.0)
    wave_a = 0.5 + 0.5 * np.sin(warp_x / 31.0 + warp_y / 44.0)
    wave_b = 0.5 + 0.5 * np.cos(warp_y / 27.0 - warp_x / 63.0)
    swirl = 0.54 * wave_a + 0.46 * wave_b
    cloud_field = 0.46 * cloud_a + 0.32 * cloud_b + 0.22 * swirl
    cloud_alpha = np.clip((cloud_field - 0.51) / 0.28, 0.0, 1.0) * 135.0
    cloud_alpha *= earth_mask
    clouds = np.empty((height, width, 4), dtype=np.uint8)
    clouds[:, :, :3] = (245, 249, 255)
    clouds[:, :, 3] = cloud_alpha.astype(np.uint8)
    cloud_layer = Image.fromarray(clouds, mode="RGBA")
    cloud_layer.putalpha(cloud_layer.getchannel("A").filter(ImageFilter.GaussianBlur(3.2)))
    image = Image.alpha_composite(image, cloud_layer)

    # The atmospheric line glows into space and softly tints the ocean edge.
    outer = np.exp(-np.maximum(radius - 1.0, 0.0) / 0.060)
    inner = np.exp(-np.maximum(1.0 - radius, 0.0) / 0.028)
    halo_alpha = np.where(radius >= 1.0, 58.0 * outer, 20.0 * inner)
    halo = np.zeros((height, width, 4), dtype=np.uint8)
    halo[:, :, :3] = (23, 157, 255)
    halo[:, :, 3] = np.where(radius > 0.96, halo_alpha, 0).astype(np.uint8)
    halo_layer = Image.fromarray(halo, mode="RGBA").filter(ImageFilter.GaussianBlur(4.0))
    image = Image.alpha_composite(image, halo_layer)

    rim = np.zeros((height, width, 4), dtype=np.uint8)
    rim[:, :, :3] = (116, 225, 255)
    rim[:, :, 3] = (180.0 * np.exp(-((radius - 1.0) / 0.009) ** 2)).astype(np.uint8)
    rim_layer = Image.fromarray(rim, mode="RGBA").filter(ImageFilter.GaussianBlur(0.8))
    image = Image.alpha_composite(image, rim_layer)

    # Add exactly 25 tiny stars, keeping every one clear of the Earth disk.
    star_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    star_draw = ImageDraw.Draw(star_layer)
    star_tints = ((194, 220, 255), (255, 239, 213), (140, 207, 255))
    stars: list[tuple[int, int]] = []
    attempts = 0
    while len(stars) < 25 and attempts < 5000:
        attempts += 1
        sx = int(rng.integers(3, width - 3))
        sy = int(rng.integers(15, max(16, int(height * 0.68))))
        clear_of_earth = radius[sy, sx] > 1.0 + 2.0 / min(rx, ry)
        if not clear_of_earth or any(abs(sx - px) < 5 and abs(sy - py) < 5 for px, py in stars):
            continue
        stars.append((sx, sy))
        tint = star_tints[int(rng.integers(0, len(star_tints)))]
        diameter = int(rng.choice((1, 1, 1, 2, 2, 3)))
        if diameter == 1:
            star_draw.point((sx, sy), fill=(*tint, 255))
        else:
            star_draw.ellipse(
                (sx - diameter // 2, sy - diameter // 2,
                 sx + diameter // 2, sy + diameter // 2),
                fill=(*tint, 255),
            )
    image = Image.alpha_composite(image, star_layer)

    # An eight-bar strip reads clearly at native size and identifies this as a
    # decoded test frame rather than a photograph.
    color_bars = (
        (242, 242, 242), (242, 220, 35), (34, 210, 230), (40, 185, 75),
        (222, 55, 210), (230, 52, 46), (50, 83, 218), (12, 15, 25),
    )
    bar_draw = ImageDraw.Draw(image)
    for index, color in enumerate(color_bars):
        left = round(index * width / len(color_bars))
        right = round((index + 1) * width / len(color_bars))
        bar_draw.rectangle((left, 0, right - 1, 11), fill=(*color, 255))

    # A compact caption band remains legible at both native and enlarged size.
    caption_height = max(20, round(height * 0.078))
    band_top = height - caption_height
    caption = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    caption_draw = ImageDraw.Draw(caption)
    caption_draw.rectangle((0, band_top, width, height), fill=(3, 10, 20, 228))
    caption_draw.line((0, band_top, width, band_top), fill=(57, 196, 224, 230), width=1)
    caption_font = _font(11)
    caption_draw.text(
        (8, band_top + 4), "SOMAIYASAT \u00b7 SSTV \u00b7 ROBOT36",
        font=caption_font, fill=(227, 243, 250, 255),
    )
    baseline = band_top + caption_height - 4
    right_edge = width - 8
    caption_draw.text((right_edge, baseline), "KJSCE   GS", font=caption_font,
                      fill=(111, 211, 237, 255), anchor="rs")
    image = Image.alpha_composite(image, caption)

    return image.convert("RGB")


def ensure_sstv_image(path: Path = config.SSTV_IMAGE_PATH) -> Image.Image:
    """Load an SSTV image, or create and best-effort save the bundled fallback."""
    path = Path(path)
    try:
        with Image.open(path) as source:
            return source.convert("RGB")
    except (FileNotFoundError, OSError, UnidentifiedImageError) as error:
        _LOGGER.warning("Could not load SSTV image at %s (%s); using generated test card", path, error)

    image = build_sstv_test_image()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    except OSError as error:
        _LOGGER.warning("Could not save generated SSTV image at %s: %s", path, error)
    return image


if __name__ == "__main__":
    output_path = config.SSTV_IMAGE_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_sstv_test_image().save(output_path)
    print(f"Regenerated {output_path}")
