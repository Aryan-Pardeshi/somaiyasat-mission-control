"""Create deterministic CSV missions for replay and demonstrations.

The examples are generated from the central config so packet sizes, weights,
power costs, and replay limits stay aligned with the rest of Mission Control.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Direct script execution starts with app/utils on sys.path, so add the repo
# root before importing config. This keeps the requested `python file.py` form
# working even when the package __init__ files have not been created yet.
if __package__ in (None, ""):
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from app import config

_COLUMNS = [
    "timestamp",
    "battery",
    "temp",
    "signal",
    "power_draw",
    "packet_loss",
    "packet_type",
    "priority",
    "size_kb",
    "event",
]
_PACKET_TYPES = tuple(config.PACKET_TYPE_WEIGHTS)
_PRIORITIES = tuple(config.PRIORITIES)
_TRANSMIT_MODES = ("TTC", "CODEC2", "M17", "SSTV")
_TRANSMIT_WEIGHTS = np.array([config.PACKET_TYPE_WEIGHTS[name] for name in _TRANSMIT_MODES], dtype=float)
_TRANSMIT_WEIGHTS /= _TRANSMIT_WEIGHTS.sum()


def _clock_labels(row_count: int) -> list[str]:
    """Format elapsed seconds as mission-clock labels starting at 00:00:01."""
    return [
        f"{second // 3600:02d}:{(second % 3600) // 60:02d}:{second % 60:02d}"
        for second in range(1, row_count + 1)
    ]


def _make_pass_signal(
    seconds: np.ndarray,
    windows: tuple[tuple[int, int], ...],
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return noisy signal and a pass mask; the raised sine gives soft AOS/LOS."""
    signal = rng.uniform(0.0, config.OUT_OF_PASS_SIGNAL_MAX, len(seconds))
    in_pass = np.zeros(len(seconds), dtype=bool)
    for start, end in windows:
        mask = (seconds >= start) & (seconds <= end)
        progress = (seconds[mask] - start) / max(end - start, 1)
        hump = np.sin(np.pi * progress) ** 0.8
        signal[mask] = (
            config.MIN_PASS_SIGNAL
            + (config.PEAK_PASS_SIGNAL - config.MIN_PASS_SIGNAL) * hump
            + rng.normal(0.0, config.SIGNAL_NOISE_STD, mask.sum())
        )
        in_pass[mask] = True
    return np.clip(signal, 0.0, 100.0), in_pass


def _packets(
    row_count: int,
    rng: np.random.Generator,
    base_probability: float,
    congestion: np.ndarray | None = None,
) -> tuple[list[str], list[str], list[float | None]]:
    """Draw packet fields from config, using empty fields for quiet seconds."""
    has_packet = rng.random(row_count) < base_probability
    if congestion is not None:
        # The deliberate burst is visible as a dense, easy-to-explain block.
        has_packet[congestion] = rng.random(int(congestion.sum())) < 0.97

    packet_types: list[str] = []
    priorities: list[str] = []
    sizes: list[float | None] = []
    type_weights = np.array([config.PACKET_TYPE_WEIGHTS[name] for name in _PACKET_TYPES])
    for has_one in has_packet:
        if not has_one:
            packet_types.append("")
            priorities.append("")
            sizes.append(None)
            continue

        packet_type = str(rng.choice(_PACKET_TYPES, p=type_weights))
        priority_map = config.PACKET_PRIORITY_WEIGHTS[packet_type]
        priority_names = tuple(priority_map)
        priority_weights = np.array([priority_map[name] for name in priority_names], dtype=float)
        priority_weights /= priority_weights.sum()
        low, high = config.PACKET_SIZE_RANGES_KB[packet_type]
        packet_types.append(packet_type)
        priorities.append(str(rng.choice(priority_names, p=priority_weights)))
        # Uniform draws retain integer config bounds while producing realistic
        # fractional sizes for the larger payload modes.
        sizes.append(round(float(rng.uniform(low, high)), 1))
    return packet_types, priorities, sizes


def _power_and_thermal(
    in_pass: np.ndarray,
    rng: np.random.Generator,
    row_count: int,
    *,
    stressful: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Add short transmission stretches inside passes and generate temperatures."""
    power = np.full(row_count, config.BASE_POWER_DRAW, dtype=float)
    transmitting = np.zeros(row_count, dtype=bool)
    tx_mode = np.full(row_count, "TTC", dtype=object)

    # Short contiguous stretches make the power trace read like a radio being
    # keyed, instead of independent random spikes on every telemetry row.
    seconds = np.arange(1, row_count + 1)
    starts = np.flatnonzero(in_pass & (rng.random(row_count) < (0.075 if stressful else 0.065)))
    for start_index in starts:
        stretch = int(rng.integers(2, 7))
        mode = str(rng.choice(_TRANSMIT_MODES, p=_TRANSMIT_WEIGHTS))
        stop = min(start_index + stretch, row_count)
        mask = in_pass[start_index:stop]
        transmitting[start_index:stop] |= mask
        tx_mode[start_index:stop][mask] = mode

    for mode, extra in config.MODE_POWER_COSTS.items():
        mode_mask = transmitting & (tx_mode == mode)
        power[mode_mask] += extra
    power += rng.normal(0.0, 0.035, row_count)
    power = np.maximum(power, 0.0)

    if stressful:
        # The knots are mission beats: heating during the busy middle, then a
        # long cool-down that ends below the replay's 50 C milestone.
        knots_t = np.array([1, 100, 180, 205, 230, 260, 300, 330, 380, 420, 480])
        knots_temp = np.array([34, 42, 61, 66, 64, 67, 72, 69, 56, 49, 43], dtype=float)
        temp = np.interp(seconds, knots_t, knots_temp) + rng.normal(0.0, 0.32, row_count)
        temp[seconds == 300] = 72.0
    else:
        progress = (seconds - 1) / max(row_count - 1, 1)
        temp = (
            27.0
            + 10.0 * progress
            + 1.1 * np.sin(2.0 * np.pi * seconds / 175.0)
            + (power - config.BASE_POWER_DRAW) * 0.45
            + rng.normal(0.0, 0.25, row_count)
        )
        temp[0] = 27.0
        temp[-1] = 39.0
    return power, np.clip(temp, *config.REPLAY_TEMP_RANGE)


def _mission_frame(
    *,
    row_count: int,
    seed: int,
    pass_windows: tuple[tuple[int, int], ...],
    stressful: bool,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    seconds = np.arange(1, row_count + 1)
    signal, in_pass = _make_pass_signal(seconds, pass_windows, rng)

    if stressful:
        # Piecewise interpolation lets the replay cross the configured LOW_POWER
        # and SAFE_MODE thresholds at visible, predictable moments.
        battery_knots_t = np.array([1, 90, 150, 180, 225, 250, 300, 330, 380, 420, 480])
        battery_knots = np.array([62, 55, 40, 34, 27, 22, 16, 13, 15, 18, 21], dtype=float)
        battery = np.interp(seconds, battery_knots_t, battery_knots)
        battery += rng.normal(0.0, 0.16, row_count)
        battery[0], battery[249], battery[329], battery[-1] = 62.0, 22.0, 13.0, 21.0
    else:
        progress = (seconds - 1) / max(row_count - 1, 1)
        battery = 94.0 - 10.0 * progress + 0.25 * np.sin(seconds / 35.0)
        battery += rng.normal(0.0, 0.12, row_count)
        battery[0], battery[-1] = 94.0, 84.0
    battery = np.clip(battery, 0.0, 100.0)

    congestion = (seconds >= 190) & (seconds <= 215) if stressful else None
    packet_types, priorities, sizes = _packets(row_count, rng, 0.34 if not stressful else 0.33, congestion)
    power_draw, temp = _power_and_thermal(in_pass, rng, row_count, stressful=stressful)

    # During the stressful mission's weak-link interval the signal stays below
    # normal pass strength, but above the replay's in-pass floor of 8 percent.
    if stressful:
        weak = (seconds >= 240) & (seconds <= 265)
        signal[weak] = rng.uniform(10.0, 25.0, int(weak.sum()))

    packet_loss = np.zeros(row_count, dtype=float)
    packet_loss[in_pass] = np.clip(
        1.0 + 25.0 * (1.0 - signal[in_pass] / 100.0) ** 2 + rng.normal(0.0, 1.25, int(in_pass.sum())),
        0.0,
        100.0,
    )
    events = [""] * row_count
    if stressful:
        for second, event in (
            (150, "CORRUPTED_PACKET"),
            (195, "PACKET_BURST"),
            (225, "COMM_FAILURE"),
        ):
            events[second - 1] = event

    return pd.DataFrame(
        {
            "timestamp": _clock_labels(row_count),
            "battery": np.round(battery, 1),
            "temp": np.round(temp, 1),
            "signal": np.round(signal).astype(int),
            "power_draw": np.round(power_draw, 2),
            "packet_loss": np.round(packet_loss, 1),
            "packet_type": packet_types,
            "priority": priorities,
            "size_kb": sizes,
            "event": events,
        },
        columns=_COLUMNS,
    )


def generate_sample_missions(
    data_dir: Path = config.DATA_DIR,
    overwrite: bool = False,
) -> list[Path]:
    """Write the healthy and stressful replay CSVs, returning files written.

    Existing files are left alone by default so a user's hand-edited examples
    are preserved; pass ``overwrite=True`` to restore the deterministic bundle.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    missions = (
        ("sample_mission.csv", 420, 42036, ((20, 110), (250, 340)), False),
        ("stressful_mission.csv", 480, 48036, ((15, 110), (200, 320), (400, 470)), True),
    )
    written: list[Path] = []
    for name, row_count, seed, passes, stressful in missions:
        path = data_dir / name
        if path.exists() and not overwrite:
            continue
        frame = _mission_frame(
            row_count=row_count,
            seed=seed,
            pass_windows=passes,
            stressful=stressful,
        )
        frame.to_csv(path, index=False)
        written.append(path)
    return written


if __name__ == "__main__":
    for _path in generate_sample_missions(overwrite=True):
        print(f"{_path.name}: {len(pd.read_csv(_path))} rows")
