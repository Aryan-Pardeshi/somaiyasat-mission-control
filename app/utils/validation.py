"""Pure input validators shared by live and replay paths."""

from __future__ import annotations
from datetime import datetime
import math


def clamp(value: float, low: float, high: float) -> float:
    """Limit a numeric value to an inclusive range."""
    return max(low, min(high, value))


def is_valid_percentage(value: object) -> bool:
    """Return whether value is a finite percentage."""
    try:
        number = float(value)
        return math.isfinite(number) and 0 <= number <= 100
    except (TypeError, ValueError):
        return False


def normalize_label(value: object) -> str:
    """Normalise operator and CSV labels, including the TT&C alias."""
    label = str(value).strip().upper() if value is not None else ""
    return "TTC" if label == "TT&C" else label


def parse_timestamp(value: object) -> float:
    """Parse elapsed seconds, MM:SS, HH:MM:SS, or an ISO datetime."""
    raw = str(value).strip()
    try:
        if "T" in raw or "-" in raw and ":" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        pieces = raw.split(":")
        if len(pieces) == 1:
            result = float(raw)
        elif len(pieces) in (2, 3):
            result = sum(float(part) * 60**index for index, part in enumerate(reversed(pieces)))
        else:
            raise ValueError(raw)
        if not math.isfinite(result) or result < 0:
            raise ValueError(raw)
        return result
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp: {value}") from exc
