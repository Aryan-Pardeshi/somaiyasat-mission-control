"""CSV validation and paced replay into the mission controller."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging
import math
import threading
import time
import pandas as pd
from app import config
from app.exceptions import ReplayDataError
from app.utils.validation import normalize_label, parse_timestamp

logger = logging.getLogger(__name__)

@dataclass
class ValidationReport:
    """Result of CSV schema and row validation."""
    valid_rows: int
    invalid_rows: int
    errors: list[str]
    duration: float
    pass_windows: list[tuple[float, float]]

class ReplayEngine:
    """Loads valid rows and schedules them against wall time and speed."""
    def __init__(self):
        self._dataframe: pd.DataFrame | None = None
        self._index = 0
        self._speed = 1.0
        self._paused = False
        self._source_name = ""
        self._lock = threading.RLock()
        self.report: ValidationReport | None = None
    def load_csv(self, path: str | Path) -> ValidationReport:
        """Read, normalise, validate, sort, and derive signal pass windows."""
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
            raise ReplayDataError(f"Cannot read replay CSV: {exc}") from exc
        frame.columns = [str(col).strip().lower() for col in frame.columns]
        missing = set(config.REPLAY_REQUIRED_COLUMNS) - set(frame.columns)
        if missing:
            raise ReplayDataError(f"Missing replay columns: {', '.join(sorted(missing))}")
        if "event" not in frame:
            frame["event"] = ""
        for col in ("packet_type", "priority", "event"):
            frame[col] = frame[col].map(normalize_label)
        for col in ("battery", "temp", "signal", "power_draw", "packet_loss", "size_kb"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        errors: list[str] = []
        good_rows = []
        first_time: float | None = None
        for index, row in frame.iterrows():
            try:
                timestamp = parse_timestamp(row["timestamp"])
                if first_time is None:
                    first_time = timestamp
                t = timestamp - first_time
                if t < 0:
                    raise ValueError("timestamp before first row")
                for key in ("battery", "signal", "packet_loss"):
                    if not math.isfinite(row[key]) or not 0 <= row[key] <= 100:
                        raise ValueError(f"{key} {row[key]} out of range")
                if not math.isfinite(row["temp"]) or not config.REPLAY_TEMP_RANGE[0] <= row["temp"] <= config.REPLAY_TEMP_RANGE[1]:
                    raise ValueError(f"temp {row['temp']} out of range")
                if not math.isfinite(row["power_draw"]) or row["power_draw"] < 0:
                    raise ValueError(f"power_draw {row['power_draw']} out of range")
                kind = row["packet_type"]
                if kind and (kind not in config.PACKET_TYPES or row["priority"] not in config.PRIORITIES or not math.isfinite(row["size_kb"]) or row["size_kb"] <= 0):
                    raise ValueError("invalid packet type, priority, or size")
                if row["event"] and row["event"] not in config.REPLAY_ALLOWED_EVENTS:
                    raise ValueError(f"invalid event {row['event']}")
                record = row.to_dict()
                record["t"] = float(t)
                good_rows.append(record)
            except (ValueError, TypeError) as exc:
                if len(errors) < 50:
                    errors.append(f"Row {index + 2}: {exc}")
        if not good_rows:
            raise ReplayDataError("Replay CSV contains no valid rows")
        valid = pd.DataFrame(good_rows).sort_values("t").reset_index(drop=True)
        windows: list[tuple[float, float]] = []
        start: float | None = None
        previous = 0.0
        for row in valid.itertuples():
            if row.signal >= config.REPLAY_PASS_SIGNAL_THRESHOLD:
                if start is None:
                    start = float(row.t)
                previous = float(row.t)
            elif start is not None:
                windows.append((start, previous))
                start = None
        if start is not None:
            windows.append((start, previous))
        report = ValidationReport(len(valid), len(frame) - len(valid), errors,
                                  float(valid["t"].iloc[-1]), windows)
        with self._lock:
            self._dataframe, self.report, self._index = valid, report, 0
            self._source_name = Path(path).name
            self._paused = False
        return report
    @property
    def dataframe(self) -> pd.DataFrame | None:
        """Validated rows with elapsed column t."""
        return self._dataframe
    def preview(self, n: int = 12) -> pd.DataFrame:
        """Return the first validated rows for the UI."""
        return self._dataframe.head(n).copy() if self._dataframe is not None else pd.DataFrame()
    @property
    def total_rows(self) -> int:
        """Number of validated rows."""
        return len(self._dataframe) if self._dataframe is not None else 0
    @property
    def index(self) -> int:
        """Next row index."""
        with self._lock:
            return self._index
    @property
    def speed(self) -> float:
        """Playback speed multiplier."""
        with self._lock:
            return self._speed
    @property
    def paused(self) -> bool:
        """Whether replay time is frozen."""
        with self._lock:
            return self._paused
    @property
    def source_name(self) -> str:
        """CSV basename."""
        return self._source_name
    def set_speed(self, speed: float) -> None:
        """Use one of the supported playback multipliers."""
        if speed not in config.REPLAY_SPEEDS:
            raise ValueError(f"Unsupported replay speed: {speed}")
        with self._lock:
            self._speed = float(speed)
    def pause(self) -> None:
        """Freeze replay progress."""
        with self._lock:
            self._paused = True
    def resume(self) -> None:
        """Resume replay progress."""
        with self._lock:
            self._paused = False
    def reset(self) -> None:
        """Return to the first row."""
        with self._lock:
            self._index = 0
            self._paused = False
    def run(self, stop_event: threading.Event, on_row, on_progress) -> None:
        """Emit rows at replay speed, reacting promptly to pause and stop."""
        if self._dataframe is None:
            raise ReplayDataError("Load a CSV before replay")
        rows = self._dataframe.to_dict("records")
        previous_t = rows[self.index - 1]["t"] if self.index else rows[0]["t"]
        while self.index < len(rows) and not stop_event.is_set():
            with self._lock:
                index = self._index
            row = rows[index]
            remaining = max(0, row["t"] - previous_t)
            while remaining > 0 and not stop_event.is_set():
                if self.paused:
                    stop_event.wait(0.05)
                    continue
                speed = self.speed
                slice_wall = min(0.05, remaining / speed)
                start = time.monotonic()
                stop_event.wait(slice_wall)
                remaining -= (time.monotonic() - start) * speed
            while self.paused and not stop_event.is_set():
                stop_event.wait(0.05)
            if stop_event.is_set():
                break
            on_row(dict(row))
            with self._lock:
                self._index += 1
                index = self._index
            previous_t = row["t"]
            on_progress(dict(index=index, total=len(rows), fraction=index / len(rows),
                             replay_time=float(row["t"]), speed=self.speed, paused=self.paused))
