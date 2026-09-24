"""
Central configuration for SomaiyaSat Mission Control.

Every tunable number in the simulation lives here so that the rest of the
code never contains unexplained "magic numbers". Changing a threshold here
changes the behaviour of the whole system (router, state machine, UI).

NOTE: All values are *simulation constants* chosen to make a compressed,
demo-friendly digital twin. They are not real PocketQube or RF protocol
specifications.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
LOGS_DIR = BASE_DIR / "logs"

DB_PATH = DATA_DIR / "somaiyasat.db"
LOG_FILE = LOGS_DIR / "somaiyasat.log"
VIDEO_PATH = ASSETS_DIR / "earth_orbit_loop.mp4"
SSTV_IMAGE_PATH = ASSETS_DIR / "sample_sstv.png"
SAMPLE_MISSION_CSV = DATA_DIR / "sample_mission.csv"
STRESSFUL_MISSION_CSV = DATA_DIR / "stressful_mission.csv"

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------
APP_TITLE = "SomaiyaSat Mission Control"
APP_SUBTITLE = "Autonomous Satellite Operations Digital Twin"
APP_VERSION = "1.0.0"
MISSION_CODE_PREFIX = "SMC"
SATELLITE_NAME = "SomaiyaSat"
DEPLOYER_NAME = "SomaiyaPod"
GROUND_STATION_NAME = "KJSCE Ground Station, Mumbai"

# ---------------------------------------------------------------------------
# Worker timing (seconds of wall-clock time)
# ---------------------------------------------------------------------------
TELEMETRY_INTERVAL = 1.0          # telemetry simulator tick (~1 Hz)
HEALTH_CHECK_INTERVAL = 0.5       # health monitor / state machine tick
ROUTER_INTERVAL = 0.5             # autonomous router decision cycle
TRANSMISSION_TICK = 0.1           # communication worker tick
PACKET_GENERATION_INTERVAL = 4.0  # live mode: seconds between generation attempts
PACKET_GENERATION_PROBABILITY = 0.75
THREAD_JOIN_TIMEOUT = 2.0

# UI timing (milliseconds)
UI_POLL_INTERVAL_MS = 50          # how often Tk drains the event queue
UI_MAX_EVENTS_PER_POLL = 250
ORBIT_FRAME_MS = 33               # ~30 FPS orbit animation
CHART_REFRESH_MS = 1000           # live charts redraw at ~1 Hz

TELEMETRY_HISTORY_LENGTH = 180    # rolling buffer (deque maxlen) for live charts
EVENT_FEED_MAX_LINES = 250

# ---------------------------------------------------------------------------
# Orbit and ground-pass simulation (compressed time, not orbital mechanics)
# ---------------------------------------------------------------------------
ORBIT_PERIOD = 180.0              # seconds for one simulated orbit
PASS_DURATION = 60.0              # seconds of ground-station visibility per orbit
INITIAL_TIME_TO_AOS = 12.0        # first pass begins shortly after mission start
AOS_PHASE_DURATION = 5.0          # "AOS" label shown for the first seconds of a pass
LOS_PHASE_DURATION = 6.0          # "LOS" label shown right after a pass ends
GROUND_STATION_ANGLE = 90.0       # degrees (90 = top of the Earth in the orbit view)
SUN_DIRECTION_ANGLE = 0.0         # sunlight arrives from the right of the orbit view
SUNLIT_COSINE_LIMIT = -0.45       # cos(angle to sun) above this => sunlit (~65 % of orbit)
PEAK_PASS_SIGNAL = 94.0           # best signal quality (%) at mid-pass
MIN_PASS_SIGNAL = 18.0            # signal right at AOS / LOS
SIGNAL_NOISE_STD = 2.5            # Gaussian noise added with NumPy
OUT_OF_PASS_SIGNAL_MAX = 3.0      # background noise level when no pass

# ---------------------------------------------------------------------------
# Power system
# ---------------------------------------------------------------------------
BATTERY_INITIAL = 92.0            # %
BATTERY_PCT_PER_JOULE = 0.02      # how many % one joule of net energy represents
BATTERY_VOLTAGE_EMPTY = 3.30      # 1S Li-ion, simulated
BATTERY_VOLTAGE_FULL = 4.20
SOLAR_INPUT_W = 0.90              # charging power while sunlit
BASE_POWER_DRAW = 0.45            # onboard computer + sensors idle load (W)
SAFE_MODE_POWER_DRAW = 0.25       # minimal load in safe mode (W)
MODE_POWER_COSTS = {              # extra transmitter load per communication mode (W)
    "TTC": 0.35,
    "CODEC2": 0.85,
    "M17": 1.15,
    "SSTV": 2.15,
}

# ---------------------------------------------------------------------------
# Thermal system
# ---------------------------------------------------------------------------
TEMP_INITIAL = 27.0
THERMAL_BASELINE = 22.0           # equilibrium temperature with no load (°C)
THERMAL_POWER_COEFF = 6.0         # °C of equilibrium rise per watt drawn
THERMAL_SUN_OFFSET = 4.0          # sunlit side warms the satellite
THERMAL_ECLIPSE_OFFSET = -3.0     # eclipse cools it
THERMAL_RESPONSE = 0.08           # fraction of the gap closed per second
THERMAL_NOISE_STD = 0.15
EXTERNAL_HEAT_DECAY = 0.975       # injected heat decays by this factor per second

# ---------------------------------------------------------------------------
# Safety thresholds (Layer 1 of the autonomous decision engine)
# ---------------------------------------------------------------------------
BATTERY_CRITICAL_THRESHOLD = 15.0   # below => SAFE_MODE
BATTERY_LOW_THRESHOLD = 25.0        # below => LOW_POWER
BATTERY_RECOVERY_MARGIN = 3.0       # hysteresis to avoid state flicker
TEMP_WARNING_THRESHOLD = 60.0       # above => THERMAL_ALERT
TEMP_CRITICAL_THRESHOLD = 70.0      # above => SAFE_MODE
TEMP_RECOVERY_MARGIN = 5.0
SIGNAL_MIN_THRESHOLD = 20.0         # below => hold non-critical transmissions
DEGRADED_LINK_THRESHOLD = 35.0      # below (while in pass) => DEGRADED_LINK
LINK_DROP_MARGIN = 12.0             # active transmission fails if signal < min - margin
LOW_POWER_MAX_ENERGY_J = 12.0       # LOW_POWER: defer packets costing more energy than this

# Communication modes allowed in each mission state. SAFE_MODE additionally
# restricts transmission to CRITICAL packets (see router.SafetyRules).
STATE_ALLOWED_MODES = {
    "NOMINAL": {"TTC", "CODEC2", "M17", "SSTV"},
    "DEGRADED_LINK": {"TTC", "CODEC2", "M17", "SSTV"},
    "LOW_POWER": {"TTC", "CODEC2"},
    "THERMAL_ALERT": {"TTC"},
    "SAFE_MODE": {"TTC"},
    "COMMUNICATION_LOSS": set(),
}

# ---------------------------------------------------------------------------
# Communication modes (simulated values)
# ---------------------------------------------------------------------------
MODE_MIN_SIGNAL = {"TTC": 15.0, "CODEC2": 30.0, "M17": 40.0, "SSTV": 55.0}
MODE_DATA_RATE_KBPS = {"TTC": 2.5, "CODEC2": 9.0, "M17": 14.0, "SSTV": 22.0}
SSTV_IMAGE_LINES = 256            # scan lines per simulated SSTV frame
SSTV_ENCODER_OVERHEAD_J = 3.0     # image encoding cost on top of RF energy

# ---------------------------------------------------------------------------
# Weighted routing score (Layer 2 of the autonomous decision engine)
# ---------------------------------------------------------------------------
ROUTING_WEIGHTS = {
    "priority": 0.35,
    "link": 0.25,
    "urgency": 0.15,
    "energy": 0.15,
    "waiting": 0.10,
}
PRIORITY_SCORES = {"CRITICAL": 100.0, "HIGH": 80.0, "MEDIUM": 55.0, "LOW": 30.0}
URGENCY_SCORES = {
    "TTC": 100.0,
    "HOUSEKEEPING": 75.0,
    "CODEC2": 50.0,
    "M17": 45.0,
    "SSTV": 35.0,
}
WAITING_FULL_BONUS_SECONDS = 150.0   # age at which the fairness bonus is maxed out
ENERGY_REFERENCE_J = 40.0            # energy cost that scores 0 on the energy scale
ENERGY_PRESSURE_MIN = 0.30           # how much energy matters on a full battery
ENERGY_PRESSURE_MAX = 1.00           # ... and on an empty battery

# ---------------------------------------------------------------------------
# Packet queue / retry policy
# ---------------------------------------------------------------------------
MAX_QUEUE_SIZE = 40
MAX_RETRIES = 2
MAX_RETRIES_CRITICAL = 4

# Probability of each packet type being generated in live mode.
PACKET_TYPE_WEIGHTS = {
    "HOUSEKEEPING": 0.34,
    "TTC": 0.22,
    "CODEC2": 0.16,
    "M17": 0.16,
    "SSTV": 0.12,
}
PACKET_SIZE_RANGES_KB = {
    "TTC": (1, 10),
    "HOUSEKEEPING": (1, 20),
    "CODEC2": (10, 80),
    "M17": (20, 100),
    "SSTV": (150, 500),
}
# Priority distribution per packet type (CRITICAL is deliberately rare).
PACKET_PRIORITY_WEIGHTS = {
    "TTC": {"CRITICAL": 0.25, "HIGH": 0.55, "MEDIUM": 0.20, "LOW": 0.0},
    "HOUSEKEEPING": {"CRITICAL": 0.08, "HIGH": 0.42, "MEDIUM": 0.40, "LOW": 0.10},
    "CODEC2": {"CRITICAL": 0.0, "HIGH": 0.15, "MEDIUM": 0.50, "LOW": 0.35},
    "M17": {"CRITICAL": 0.0, "HIGH": 0.15, "MEDIUM": 0.45, "LOW": 0.40},
    "SSTV": {"CRITICAL": 0.0, "HIGH": 0.10, "MEDIUM": 0.50, "LOW": 0.40},
}

# ---------------------------------------------------------------------------
# Incident simulator
# ---------------------------------------------------------------------------
BATTERY_DRAIN_TARGET = 19.0          # battery drain incident ends around this level
BATTERY_DRAIN_STEPS = 4              # applied over this many telemetry ticks
THERMAL_SPIKE_STEPS = (10.0, 11.0, 11.0, 6.0)   # °C of heat injected per tick
SIGNAL_LOSS_DURATION = 20.0          # seconds of heavy attenuation
SIGNAL_LOSS_ATTENUATION = 0.08       # signal multiplied by this during loss
COMM_FAILURE_DURATION = 8.0          # seconds the RF link is down
PACKET_BURST_SIZE = 10
TELEMETRY_CORRUPTION_PROBABILITY = 0.004   # random corrupted telemetry frame (live)

# ---------------------------------------------------------------------------
# CSV mission replay
# ---------------------------------------------------------------------------
REPLAY_SPEEDS = (0.5, 1.0, 2.0, 5.0)
REPLAY_REQUIRED_COLUMNS = (
    "timestamp", "battery", "temp", "signal", "power_draw",
    "packet_loss", "packet_type", "priority", "size_kb",
)
REPLAY_OPTIONAL_COLUMNS = ("event",)
REPLAY_ALLOWED_EVENTS = {"COMM_FAILURE", "CORRUPTED_PACKET", "PACKET_BURST", "SIGNAL_LOSS"}
REPLAY_PASS_SIGNAL_THRESHOLD = 8.0   # rows with signal >= this are "in pass"
REPLAY_TEMP_RANGE = (-40.0, 125.0)   # plausible sensor range for validation

# ---------------------------------------------------------------------------
# Supported communication modes (a set: unique, unordered, O(1) membership)
# ---------------------------------------------------------------------------
SUPPORTED_MODES = {"TTC", "SSTV", "M17", "CODEC2"}
PACKET_TYPES = ("TTC", "HOUSEKEEPING", "SSTV", "M17", "CODEC2")
PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
