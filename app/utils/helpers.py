"""Formatting and filesystem helpers."""

from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from app import config


def format_met(seconds: float) -> str:
    """Format elapsed mission time as HH:MM:SS."""
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def format_countdown(seconds: float) -> str:
    """Format a nonnegative countdown as MM:SS."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def now_iso() -> str:
    """Return a local wall-clock timestamp."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mission_code(day: date, number: int) -> str:
    """Build a readable daily mission code."""
    return f"{config.MISSION_CODE_PREFIX}-{day:%Y%m%d}-{number:03d}"


def timestamped_filename(prefix: str, ext: str) -> str:
    """Build a timestamped export filename."""
    return f"{prefix}_{datetime.now():%Y-%m-%d_%H%M}.{ext.lstrip('.')}"


def ensure_directories() -> None:
    """Create runtime folders when missing."""
    for path in (config.ASSETS_DIR, config.DATA_DIR, config.EXPORTS_DIR, config.LOGS_DIR):
        Path(path).mkdir(parents=True, exist_ok=True)
