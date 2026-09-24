"""Shared pytest fixtures.

Run all tests with:  python -m pytest -v
"""
import os
import sys
from pathlib import Path

# Charts must render without opening windows while testing.
os.environ["MPLBACKEND"] = "Agg"
import matplotlib  # noqa: E402

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.core.router import AutonomousRouter, RouterContext  # noqa: E402
from app.database.database_manager import DatabaseManager  # noqa: E402
from app.models.communication_modes import build_modes  # noqa: E402
from app.models.enums import MissionState  # noqa: E402
from app.models.telemetry import TelemetrySnapshot  # noqa: E402
from app.utils.helpers import now_iso  # noqa: E402


@pytest.fixture
def router() -> AutonomousRouter:
    """A router with the four real communication-mode objects."""
    return AutonomousRouter(build_modes())


@pytest.fixture
def make_context():
    """Factory for router contexts: healthy defaults, override what a test needs."""

    def _make(**overrides) -> RouterContext:
        values = dict(battery=85.0, temperature=30.0, signal=80.0, state=MissionState.NOMINAL,
                      in_pass=True, seconds_to_los=60.0, comm_ok=True, now=10.0)
        values.update(overrides)
        return RouterContext(**values)

    return _make


@pytest.fixture
def db():
    """An in-memory SQLite database (fast, and deleted after the test)."""
    database = DatabaseManager(":memory:")
    yield database
    database.close()


@pytest.fixture
def make_snapshot():
    """Factory for telemetry snapshots with sensible defaults."""

    def _make(mission_time=1.0, battery=90.0, temperature=30.0, signal=80.0, **overrides) -> TelemetrySnapshot:
        values = dict(mission_time=mission_time, battery=battery, voltage=4.1, temperature=temperature,
                      signal=signal, power_draw=0.8, packet_loss=1.0, queue_size=3, system_state="NOMINAL",
                      comm_state="LINK READY", pass_phase="ACTIVE PASS", in_pass=True, sunlit=True,
                      timestamp=now_iso())
        values.update(overrides)
        return TelemetrySnapshot(**values)

    return _make
