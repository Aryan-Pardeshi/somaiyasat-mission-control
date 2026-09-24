# SomaiyaSat Mission Control — Design Contract

This document is the binding interface contract between the backend (models/core/database/analytics)
and the Tkinter UI. Every module MUST follow the names, signatures, payloads and behaviours below so
independently written parts fit together. All tunables come from `app/config.py` (already written —
read it; never duplicate its constants).

Python 3.10+ syntax (target runtime is 3.14). Libraries: stdlib, numpy, pandas, matplotlib, seaborn,
Pillow, opencv-python (optional at runtime). No other dependencies.

---------------------------------------------------------------------------------------------------
## 0. Package layout

```
main.py                          entry point: python main.py
requirements.txt
app/__init__.py
app/config.py                    (exists) all constants
app/exceptions.py                custom exceptions
app/application.py               MissionControlApp(tk.Tk) — UI shell (UI agent)
app/models/__init__.py
app/models/enums.py              all Enums
app/models/telemetry.py          TelemetrySnapshot dataclass
app/models/packet.py             DataPacket hierarchy + create_packet factory
app/models/communication_modes.py CommunicationMode ABC + 4 concrete modes
app/models/satellite.py          PowerSystem, ThermalSystem, Satellite
app/models/mission_state.py      StateMachine (+ STATE_DESCRIPTIONS)
app/core/__init__.py
app/core/event_bus.py            EventType, Event, EventBus(queue.Queue)
app/core/ground_pass.py          PassInfo, GroundPass, ReplayGroundPass
app/core/packet_queue.py         PacketQueue
app/core/router.py               RouterContext, ScoreBreakdown, RoutingDecision, SafetyRules, AutonomousRouter
app/core/communication_system.py Transmission, CommunicationSystem
app/core/health_monitor.py       HealthMonitor
app/core/incident_manager.py     Incident dataclass, IncidentManager
app/core/simulator.py            TelemetrySimulator
app/core/replay_engine.py        ValidationReport, ReplayEngine
app/core/mission_controller.py   MissionController (owns worker threads)
app/database/__init__.py
app/database/database_manager.py DatabaseManager
app/analytics/__init__.py
app/analytics/analytics_engine.py MissionData, AnalyticsEngine
app/utils/__init__.py
app/utils/logging_config.py      setup_logging()
app/utils/validation.py          small pure validators (clamp, is_valid_percentage, parse_timestamp)
app/utils/helpers.py             format_met, mission_code, timestamped_filename, ensure_directories, now_iso
app/utils/sample_data.py         generate_sample_missions(data_dir, overwrite=False)
app/utils/asset_factory.py       ensure_sstv_image(path) -> PIL.Image, build_sstv_test_image(w,h)
app/ui/...                       (UI agent — see section 9)
tests/                           pytest unit tests for core logic
```

---------------------------------------------------------------------------------------------------
## 1. Enums — `app/models/enums.py`

All are `class X(str, Enum)` so values serialise directly. Always use `.value` when writing to DB/UI.

```python
PacketType:        TTC="TTC", HOUSEKEEPING="HOUSEKEEPING", SSTV="SSTV", M17="M17", CODEC2="CODEC2"
                   property label -> "TT&C", "Housekeeping", "SSTV", "M17", "Codec2"
PacketPriority:    CRITICAL, HIGH, MEDIUM, LOW          (values = names)
PacketStatus:      QUEUED, SELECTED, TRANSMITTING, SENT, DEFERRED, FAILED, DROPPED
CommunicationType: TTC="TTC", SSTV="SSTV", M17="M17", CODEC2="CODEC2"
                   property label -> "TT&C", "SSTV", "M17", "Codec2"
MissionState:      NOMINAL, LOW_POWER, DEGRADED_LINK, THERMAL_ALERT, SAFE_MODE, COMMUNICATION_LOSS
                   property label -> "Nominal", "Low Power", "Degraded Link", "Thermal Alert", "Safe Mode", "Comm Loss"
                   property severity -> "nominal" | "warning" | "critical"
                       (NOMINAL=nominal; LOW_POWER, DEGRADED_LINK, THERMAL_ALERT=warning; SAFE_MODE, COMMUNICATION_LOSS=critical)
IncidentSeverity:  INFO, WARNING, CRITICAL
IncidentType:      BATTERY_DRAIN, THERMAL_SPIKE, SIGNAL_LOSS, COMM_FAILURE, CORRUPTED_PACKET, PACKET_BURST,
                   FORCE_SAFE_MODE, RESTORE_NOMINAL, LOW_POWER, THERMAL_ALERT, SAFE_MODE, TELEMETRY_CORRUPTION
                   property label -> human title e.g. "Thermal Spike"
PassPhase:         PRE_PASS="PRE-PASS", AOS="AOS", ACTIVE="ACTIVE PASS", LOS="LOS"
MissionMode:       LIVE, REPLAY
```

Packet type → communication mode mapping: TTC→TTC, HOUSEKEEPING→TTC, SSTV→SSTV, M17→M17, CODEC2→CODEC2.

---------------------------------------------------------------------------------------------------
## 2. Exceptions — `app/exceptions.py`

```python
class SomaiyaSatError(Exception)                      base
class TelemetryCorruptionError(SomaiyaSatError)       bad telemetry frame / packet CRC mismatch
class CommunicationFailureError(SomaiyaSatError)      RF link lost during transmission
class InvalidPacketError(SomaiyaSatError)             malformed packet (bad size/type/priority)
class DatabaseOperationError(SomaiyaSatError)         wraps sqlite3.Error
class ReplayDataError(SomaiyaSatError)                CSV unreadable / schema invalid / no valid rows
```

---------------------------------------------------------------------------------------------------
## 3. Models

### 3.1 TelemetrySnapshot (`app/models/telemetry.py`)
```python
@dataclass
class TelemetrySnapshot:
    mission_time: float          # seconds since mission start (MET)
    battery: float               # %
    voltage: float               # V
    temperature: float           # °C
    signal: float                # %
    power_draw: float            # W
    packet_loss: float           # %
    queue_size: int
    system_state: str            # MissionState.value
    comm_state: str              # "TRANSMITTING" | "LINK READY" | "LINK DOWN" | "NO PASS" | "HOLD"
    pass_phase: str              # PassPhase.value
    in_pass: bool
    sunlit: bool
    timestamp: str               # wall-clock ISO string (helpers.now_iso())
    def validate(self) -> None   # raises TelemetryCorruptionError on NaN/inf or out-of-range
                                 # (battery/signal/packet_loss not in 0..100, temp outside config.REPLAY_TEMP_RANGE, power<0)
    def to_dict(self) -> dict
```

### 3.2 Packets (`app/models/packet.py`)
```python
class DataPacket:
    packet_type: PacketType            # class attribute, set by subclasses
    preferred_mode: CommunicationType  # class attribute
    def __init__(self, packet_id: int, priority: PacketPriority, size_kb: float, created_at: float,
                 metadata: dict | None = None)
        # raises InvalidPacketError if size_kb <= 0 or priority not a PacketPriority
        # instance attrs: packet_id, priority, size_kb, created_at (MET seconds), created_iso (wall ISO),
        # status=PacketStatus.QUEUED, retry_count=0, corrupted=False, metadata, score=0.0,
        # hold_reason="", selected_at: float|None, transmitted_at: float|None, mode_used: str|None
        # private: self._payload (bytes header built from fields), self._checksum = zlib.crc32(payload)
    urgency (property)         -> config.URGENCY_SCORES[type]
    max_retries (property)     -> MAX_RETRIES_CRITICAL if CRITICAL else MAX_RETRIES
    label (property)           -> f"{type.label} #{packet_id}"
    def age(self, now: float) -> float
    def verify_integrity(self) -> None     # recompute CRC32; on mismatch set corrupted=True and raise TelemetryCorruptionError
    def corrupt(self) -> None              # simulate a bit error: flip bytes in _payload (checksum NOT updated)
    def describe(self) -> str              # subclass-specific one-liner (polymorphic)
    def to_record(self, now: float | None = None) -> dict
        # keys: packet_id, packet_type, type_label, priority, size_kb, status, retry_count, corrupted(bool),
        #       score, hold_reason, age (float, 0 if now None), required_signal, mode, created_at(ISO)
class TTCPacket(DataPacket)          type TTC, mode TTC
class HousekeepingPacket(DataPacket) type HOUSEKEEPING, mode TTC
class SSTVPacket(DataPacket)         type SSTV, mode SSTV, extra attr image_lines = config.SSTV_IMAGE_LINES
class VoicePacket(DataPacket)        common base for digital-voice packets (vocoder attribute)
class M17Packet(VoicePacket)         type M17, mode M17
class Codec2Packet(VoicePacket)      type CODEC2, mode CODEC2
PACKET_CLASSES: dict[PacketType, type[DataPacket]]
def create_packet(packet_type: PacketType|str, packet_id: int, priority: PacketPriority|str,
                  size_kb: float, created_at: float, metadata=None) -> DataPacket
    # normalises strings with .strip().upper(); accepts "TT&C" as TTC; raises InvalidPacketError on unknown values
```

### 3.3 Communication modes (`app/models/communication_modes.py`) — OOP showcase
```python
class CommunicationMode(ABC):
    mode_type: CommunicationType; display_name: str; description: str   # class attrs
    def __init__(self): reads config: self._power_w, self._data_rate_kbps, self._min_signal
    power_draw (property) -> float  (config.MODE_POWER_COSTS)
    data_rate (property)
    @abstractmethod def minimum_signal_required(self) -> float
    @abstractmethod def estimate_transmission_time(self, packet, signal: float) -> float   # seconds
    @abstractmethod def transmit(self, packet, signal: float, dt: float) -> float          # KB sent in dt
    def calculate_energy_cost(self, packet, signal) -> float   # template method: power_draw * estimate_transmission_time(packet, signal)
    def can_transmit(self, signal) -> bool                      # signal >= minimum_signal_required()
class TTCMode:    robust FEC link: efficiency = 0.7 + 0.3*s/100; transmit() first calls packet.verify_integrity()
class SSTVMode:   analog, line-sequential: time depends on size only (signal changes quality, not speed):
                  estimate = size/data_rate; transmit() returns KB in whole scan-line increments
                  (size/image_lines per line, carrying fractional remainder internally per packet);
                  property last_noise_level (0..1, rises as signal falls below ~75);
                  calculate_energy_cost adds config.SSTV_ENCODER_OVERHEAD_J
class M17Mode:    4FSK digital: efficiency is a steep curve: 0.25 + 0.75 / (1 + exp(-(s - min - 10)/6))
class Codec2Mode: low-bitrate, robust: efficiency = 0.6 + 0.4*s/100
MODE_CLASSES: dict[CommunicationType, type[CommunicationMode]]
def build_modes() -> dict[CommunicationType, CommunicationMode]
```
All `transmit` implementations: rate_kbps * efficiency(signal) * dt, never more than remaining packet size
is NOT their job (CommunicationSystem clamps). They must raise TelemetryCorruptionError if packet corrupted
(TTC via verify_integrity; others also call packet.verify_integrity()).

### 3.4 Satellite (`app/models/satellite.py`) — encapsulation showcase
```python
class PowerSystem:
    def __init__(self, initial_level=config.BATTERY_INITIAL): self.__battery (name-mangled private)
    def get_battery_level(self) -> float
    battery_level (read-only property), voltage (property: linear EMPTY..FULL), power_draw (property)
    def set_load(self, watts: float)
    def consume_power(self, watts: float, seconds: float) -> None   # battery -= watts*seconds*BATTERY_PCT_PER_JOULE
    def recharge(self, watts: float, seconds: float) -> None
    def drain(self, percent: float) -> None                          # incident
    def reset(self, level: float = config.BATTERY_INITIAL) -> None
    # battery always clamped to 0..100
class ThermalSystem:
    def __init__(self, initial=config.TEMP_INITIAL): self.__temperature; self._external_heat = 0.0
    temperature (property), external_heat (property)
    def update(self, power_draw: float, sunlit: bool, dt: float, noise: float = 0.0) -> float
        # target = BASELINE + POWER_COEFF*power_draw + (SUN or ECLIPSE offset) + external_heat
        # T += (target - T) * min(1, THERMAL_RESPONSE*dt) + noise ; external_heat *= EXTERNAL_HEAT_DECAY**dt
    def inject_heat(self, degrees: float)
    def reset(self)
class Satellite:
    def __init__(self, name=config.SATELLITE_NAME): self.power = PowerSystem(); self.thermal = ThermalSystem()
    def reset(self)
```

### 3.5 State machine (`app/models/mission_state.py`)
```python
STATE_DESCRIPTIONS: dict[MissionState, str]   # one-sentence explanation of each state
class StateMachine:
    def __init__(self): self.state = MissionState.NOMINAL; self.history: list[tuple[MissionState, MissionState, str]]
    def evaluate(self, battery, temperature, signal, in_pass, comm_failure=False, forced_safe=False) -> MissionState
        # pure decision (does not mutate). Priority order:
        # SAFE_MODE    if forced_safe or battery < BATTERY_CRITICAL or temperature > TEMP_CRITICAL
        # COMMUNICATION_LOSS if comm_failure
        # THERMAL_ALERT if temperature > TEMP_WARNING
        # LOW_POWER    if battery < BATTERY_LOW
        # DEGRADED_LINK if in_pass and signal < DEGRADED_LINK_THRESHOLD
        # NOMINAL otherwise
        # Hysteresis: while CURRENT state is SAFE_MODE use exit thresholds battery < CRITICAL+RECOVERY_MARGIN
        #   and temp > WARNING (i.e. stay safe until temp <= WARNING and battery >= CRITICAL+margin);
        #   while THERMAL_ALERT use temp > WARNING - TEMP_RECOVERY_MARGIN;
        #   while LOW_POWER use battery < LOW + BATTERY_RECOVERY_MARGIN.
    def reason_for(self, state, battery, temperature, signal, comm_failure, forced_safe) -> str
    def update(self, **same args as evaluate) -> tuple[MissionState, MissionState, str] | None
        # applies evaluate(); if changed, records history and returns (old, new, reason) else None
    def reset(self)
```

---------------------------------------------------------------------------------------------------
## 4. Core

### 4.1 Event bus (`app/core/event_bus.py`)
```python
class EventType(str, Enum):
    TELEMETRY_UPDATE, QUEUE_UPDATE, PACKET_ADDED, PACKET_SELECTED, TRANSMISSION_STARTED,
    TRANSMISSION_PROGRESS, TRANSMISSION_COMPLETE, TRANSMISSION_FAILED, STATE_CHANGED,
    INCIDENT_CREATED, INCIDENT_RESOLVED, GROUND_PASS_CHANGED, MISSION_STARTED, MISSION_ENDED,
    REPLAY_PROGRESS, LOG
@dataclass
class Event: type: EventType; data: dict; created: float = field(default_factory=time.time)
class EventBus:
    def __init__(self, maxsize=10000): self._queue = queue.Queue(maxsize)
    def publish(self, event_type: EventType, **data) -> None     # put_nowait; on queue.Full drop + log warning once
    def drain(self, max_events: int) -> list[Event]               # get_nowait loop, main (Tk) thread only
    def clear(self)
```

EVENT PAYLOADS (exact keys; all values plain Python types — never live objects):

| EventType | data keys |
|---|---|
| TELEMETRY_UPDATE | `snapshot` (TelemetrySnapshot.to_dict()), `pass` (PassInfo.to_dict()), `met` (str "HH:MM:SS"), `counters` (dict, see controller.counters) |
| QUEUE_UPDATE | `packets` (list of packet records sorted by score desc), `hold_reason` (str, "" if router free), `active_rules` (list[str] human-readable active safety rules), `transmitting_id` (int or None) |
| PACKET_ADDED | `packet` (record) |
| PACKET_SELECTED | `decision` (RoutingDecision.to_dict()) |
| TRANSMISSION_STARTED | `packet` (record), `mode` (CommunicationType value), `estimated_time` (float s) |
| TRANSMISSION_PROGRESS | `packet_id`, `mode`, `progress` (0..1), `sent_kb`, `total_kb`, `signal`, `eta` (float s), `noise` (0..1, SSTV noise level else 0) |
| TRANSMISSION_COMPLETE | `packet` (record), `mode`, `duration` |
| TRANSMISSION_FAILED | `packet` (record), `mode`, `progress`, `reason`, `requeued` (bool) |
| STATE_CHANGED | `old`, `new` (MissionState values), `reason` |
| INCIDENT_CREATED | `incident` (Incident.to_dict()) |
| INCIDENT_RESOLVED | `incident_id`, `incident_type` |
| GROUND_PASS_CHANGED | `old`, `new` (PassPhase values), `pass` (PassInfo.to_dict()) |
| MISSION_STARTED | `mission_id`, `mission_code`, `mode` ("LIVE"/"REPLAY"), `name` |
| MISSION_ENDED | `mission_id`, `mission_code`, `mode`, `status` |
| REPLAY_PROGRESS | `index`, `total`, `fraction`, `replay_time`, `speed`, `paused` (bool) |
| LOG | `severity` ("INFO"/"WARNING"/"CRITICAL"/"SYSTEM"/"ROUTER"), `message`, `met` |

### 4.2 Ground pass (`app/core/ground_pass.py`)
```python
@dataclass
class PassInfo:
    phase: PassPhase; in_pass: bool; orbit_angle: float (degrees, math convention CCW, 0=right, 90=top)
    progress: float (0..1 within pass, 0 outside); seconds_to_aos: float; seconds_to_los: float (0 outside pass)
    sunlit: bool; pass_number: int
    def to_dict(self) -> dict   (phase as value string)
class GroundPass:
    def __init__(self, period=ORBIT_PERIOD, duration=PASS_DURATION, station_angle=GROUND_STATION_ANGLE,
                 initial_time_to_aos=INITIAL_TIME_TO_AOS)
    half_arc (property) = 180*duration/period  (degrees of visible arc each side of the station)
    def info(self, t: float) -> PassInfo
        # phase_t = (t - initial_time_to_aos) % period ; in_pass = phase_t < duration
        # AOS if phase_t < AOS_PHASE_DURATION; ACTIVE if in pass; LOS if 0 <= phase_t-duration < LOS_PHASE_DURATION;
        # else PRE_PASS. angle = station_angle - half_arc + 360*phase_t/period (mod 360)
        # seconds_to_aos = period - phase_t if not in_pass (for t < first AOS also correct) ; progress = phase_t/duration
        # sunlit = cos(radians(angle - SUN_DIRECTION_ANGLE)) > SUNLIT_COSINE_LIMIT
        # pass_number = floor((t - initial_time_to_aos)/period) + 1
    def orbit_angle(self, t: float) -> float
    def signal_profile(self, info: PassInfo, rng: numpy.random.Generator) -> float
        # in pass: MIN_PASS_SIGNAL + (PEAK-MIN)*sin(pi*progress)**0.8 + rng.normal(0, SIGNAL_NOISE_STD), clip 0..100
        # outside: rng.uniform(0, OUT_OF_PASS_SIGNAL_MAX)
    def next_aos_offset(self, t) -> float   # seconds until next AOS (used by "skip to next pass")
class ReplayGroundPass(GroundPass):
    def __init__(self, windows: list[tuple[float, float]], period=ORBIT_PERIOD)
    # info(t) overrides: in_pass iff inside a window; angle interpolated so windows are centred on the station
    # (inside window i: station-half_arc -> station+half_arc linearly; between windows: sweep the rest of the circle;
    #  before first/after last: advance at 360/period deg/s); phases AOS/ACTIVE/LOS/PRE_PASS same durations.
```

### 4.3 PacketQueue (`app/core/packet_queue.py`)
Plain list protected by `threading.RLock` (small queue; router evaluates all packets each cycle = O(n)).
```python
class PacketQueue:
    def __init__(self, max_size=MAX_QUEUE_SIZE)
    def add(self, packet) -> DataPacket | None    # returns an evicted packet (status DROPPED) if full:
        # evict the lowest-priority, oldest non-CRITICAL packet; if the new packet itself is the lowest, drop the new one
    def remove(self, packet_id) -> DataPacket | None
    def get(self, packet_id) -> DataPacket | None
    def snapshot(self) -> list[DataPacket]          # shallow copy of list
    def eligible(self, predicate) -> list[DataPacket]   # uses filter()
    def counts_by_type(self) -> dict[str, int]
    def clear(self); __len__; __iter__ (over snapshot)
```

### 4.4 Router (`app/core/router.py`) — the "AI" (rule + weighted-score autonomous decision engine, NOT ML)
```python
@dataclass
class RouterContext: battery: float; temperature: float; signal: float; state: MissionState; in_pass: bool;
                     seconds_to_los: float; comm_ok: bool; now: float
@dataclass
class ScoreBreakdown: priority, link, urgency, energy, waiting (weighted contributions, points), total (0..100)
    def to_dict(self)
@dataclass
class RoutingDecision:
    packet_id, packet_type, priority, size_kb, selected_mode, total_score, priority_score, link_score,
    urgency_score, energy_score, waiting_score, battery, temperature, signal, system_state, reason,
    mission_time, timestamp (wall ISO), estimated_time, energy_cost
    def to_dict(self)
@dataclass
class RouterResult: decision: RoutingDecision | None; hold_reason: str; quarantined: list[DataPacket];
                    newly_deferred: list[DataPacket]; active_rules: list[str]
class SafetyRules:              # LAYER 1
    def global_hold(self, ctx) -> str            # "" if transmission allowed at all, else reason:
        # not in_pass -> "No active ground pass — packets held until AOS"
        # not comm_ok / COMMUNICATION_LOSS -> "RF link down — holding all transmissions"
    def check(self, packet, mode, ctx) -> str    # "" if allowed else human-readable defer reason. Rules in order:
        # mode not in config.STATE_ALLOWED_MODES[state]  -> f"{mode label} suspended in {state label}"
        # SAFE_MODE and priority != CRITICAL             -> "Safe mode: only CRITICAL packets allowed"
        # signal < SIGNAL_MIN_THRESHOLD and priority != CRITICAL -> "Signal below 20 % — non-critical held"
        # signal < mode.minimum_signal_required()        -> f"Needs {min}% signal, link at {s}%"
        # LOW_POWER and energy cost > LOW_POWER_MAX_ENERGY_J -> "Energy cost too high for low-power state"
        # estimated time > seconds_to_los               -> "Would not finish before LOS"
    def describe_active_rules(self, ctx) -> list[str]   # e.g. ["LOW_POWER: SSTV & M17 suspended", ...]
class AutonomousRouter:
    def __init__(self, modes: dict[CommunicationType, CommunicationMode], weights=ROUTING_WEIGHTS, rules=None)
    def score_packet(self, packet, ctx) -> ScoreBreakdown    # LAYER 2
        # components on 0..100 scale, then multiplied by weights:
        # priority = PRIORITY_SCORES[priority]
        # link     = clip(50 + 50*(signal - req)/max(1, 100 - req), 0, 100)
        # urgency  = URGENCY_SCORES[type]
        # energy   = clip(100 - (cost/ENERGY_REFERENCE_J*100) * pressure, 0, 100),
        #            pressure = clip(1.2 - battery/100, ENERGY_PRESSURE_MIN, ENERGY_PRESSURE_MAX)
        # waiting  = clip(age / WAITING_FULL_BONUS_SECONDS * 100, 0, 100)   (starvation prevention)
        # total = sum(weighted) rounded to 1 decimal
    def evaluate(self, packets: list[DataPacket], ctx: RouterContext) -> RouterResult
        # 1) integrity: packet.verify_integrity() in try/except TelemetryCorruptionError -> quarantined list
        # 2) global hold -> every packet: status DEFERRED? NO: keep QUEUED, set hold_reason = global reason; no decision
        # 3) per packet SafetyRules.check -> blocked packets: status DEFERRED + hold_reason (collect newly_deferred for
        #    packets whose status was not DEFERRED before); allowed: status QUEUED, hold_reason ""
        # 4) eligible = list(filter(lambda p: p.status == QUEUED and not hold_reason, ...)); score all packets
        #    (packet.score set for every packet, even blocked, for display); best = max(eligible, key=lambda p: p.score)
        # 5) build RoutingDecision with explain() reason. O(n) per cycle.
    def explain(self, packet, breakdown, ctx) -> str
        # e.g. "Packet #104 was selected because it contains critical TT&C data, the current ground link (78 %)
        #       comfortably exceeds the 15 % it needs, and its low energy cost (1.9 J) is safe at 84 % battery.
        #       Satellite is thermally nominal (31.7 °C)." — built from the largest contributions + conditions.
```

### 4.5 CommunicationSystem (`app/core/communication_system.py`)
```python
@dataclass
class Transmission: packet; mode: CommunicationMode; started_at: float; sent_kb: float = 0.0;
                    estimated_time: float = 0.0
    progress (property) = sent_kb / packet.size_kb ; total_kb ; done (property)
class CommunicationSystem:
    available_routes: list[CommunicationType]            # list of modes in display order
    supported_modes: set[str] = config.SUPPORTED_MODES   # set
    def __init__(self): self.modes = build_modes(); self.active: Transmission|None; self.stats =
        {mode.value: {"sent": 0, "failed": 0, "kb_sent": 0.0}}; self._link_down_until = -1.0
    def mode_for(self, packet) -> CommunicationMode       # via packet.preferred_mode
    def begin(self, packet, now, signal) -> Transmission   # status TRANSMITTING, packet.mode_used set
    def step(self, dt, signal, now) -> Transmission
        # raises CommunicationFailureError if link is down (now < _link_down_until) or
        #        signal < mode.minimum_signal_required() - LINK_DROP_MARGIN
        # else kb = mode.transmit(packet, signal, dt); sent_kb = min(total, sent_kb + kb)
    def complete(self) -> Transmission     # stats sent++, status SENT, clears active
    def fail(self, reason) -> Transmission # stats failed++, clears active (caller applies retry policy)
    def abort(self) -> Transmission|None   # autonomous suspension (not a failure): clears active, no stats
    def trigger_link_failure(self, now, duration)
    def link_down(self, now) -> bool
    def reset(self)
```

### 4.6 HealthMonitor (`app/core/health_monitor.py`)
Wraps StateMachine + threshold-crossing alerts.
```python
class HealthMonitor:
    def __init__(self, state_machine: StateMachine)
    def check(self, snapshot: TelemetrySnapshot, comm_failure: bool, forced_safe: bool)
        -> tuple[tuple[MissionState, MissionState, str] | None, list[tuple[str, str]]]
        # returns (transition or None, alerts) ; alerts = list of (severity, message) for threshold crossings
        # (battery crossing below 25/15, temperature crossing above 60/70, signal crossing below 20 in pass),
        # each crossing reported once until it recovers.
```

### 4.7 IncidentManager (`app/core/incident_manager.py`)
```python
@dataclass
class Incident: incident_id: int|None; incident_type: IncidentType; severity: IncidentSeverity; description: str;
                mission_time: float; timestamp: str; resolved: bool = False
    def to_dict(self)   # enums as values, plus "met" string
class IncidentManager:
    def __init__(self, db: DatabaseManager | None = None)
    def record(self, mission_id, incident_type, severity, description, mission_time, resolved=False) -> Incident
        # writes to DB (if db) inside try/except DatabaseOperationError (log, keep in memory)
    def resolve_open(self, mission_id, incident_type) -> list[Incident]   # marks unresolved of that type resolved (DB too)
    history (property) -> list[Incident]
    def counts_by_type(self) -> dict[str, int]
    def clear(self)
```

### 4.8 TelemetrySimulator (`app/core/simulator.py`)
```python
class TelemetrySimulator:
    def __init__(self, satellite: Satellite, ground_pass: GroundPass, rng: np.random.Generator)
    def step(self, mission_time, orbit_time, dt, active_mode: CommunicationMode|None, state: MissionState,
             signal_attenuation: float = 1.0, queue_size: int = 0, comm_state: str = "") -> tuple[TelemetrySnapshot, PassInfo]
        # power_draw = SAFE_MODE_POWER_DRAW if SAFE_MODE else BASE_POWER_DRAW + (active_mode.power_draw if active)
        # battery: consume_power(power_draw, dt); recharge(SOLAR_INPUT_W, dt) if sunlit
        # thermal.update(power_draw, sunlit, dt, rng.normal(0, THERMAL_NOISE_STD))
        # signal = ground_pass.signal_profile(info, rng) * signal_attenuation
        # packet_loss = in pass: clip(1.0 + 25*(1 - signal/100)**2 + rng.normal(0, 0.6), 0, 100); outside: 0.0
        # With probability TELEMETRY_CORRUPTION_PROBABILITY return a corrupted frame (e.g. battery = nan)
        # — the controller's validate() call catches it (exception-handling demo).
```

### 4.9 ReplayEngine (`app/core/replay_engine.py`)
```python
@dataclass
class ValidationReport: valid_rows: int; invalid_rows: int; errors: list[str] (max 50, e.g. "Row 17: battery 140 out of range");
                        duration: float; pass_windows: list[tuple[float, float]]
class ReplayEngine:
    def __init__(self)
    def load_csv(self, path) -> ValidationReport
        # pd.read_csv inside try/except (FileNotFoundError, pd.errors.ParserError, EmptyDataError, UnicodeDecodeError)
        #   -> ReplayDataError; column names normalised (strip().lower()); missing required columns -> ReplayDataError
        #   listing them; string cleanup (.str.strip().str.upper()) for packet_type/priority/event; "TT&C" -> "TTC";
        #   blank packet_type means "no packet this row"; numeric coercion with pd.to_numeric(errors="coerce");
        #   row validation: battery 0..100, signal 0..100, packet_loss 0..100, temp within REPLAY_TEMP_RANGE,
        #   power_draw >= 0, packet_type in PACKET_TYPES or blank, priority in PRIORITIES when packet_type given,
        #   size_kb > 0 when packet_type given, event blank or in REPLAY_ALLOWED_EVENTS.
        #   timestamp: "HH:MM:SS" / "MM:SS" / seconds number / ISO datetime -> float seconds from first row
        #   (utils.validation.parse_timestamp); invalid rows dropped & reported; zero valid rows -> ReplayDataError.
        #   Sorted by time. pass_windows computed with pandas from contiguous rows where signal >= REPLAY_PASS_SIGNAL_THRESHOLD.
    dataframe (property) -> pd.DataFrame | None (validated, with float column "t")
    preview(self, n=12) -> pd.DataFrame
    total_rows, index, speed, paused (properties); source_name
    def set_speed(self, speed: float)          # one of REPLAY_SPEEDS
    def pause(self); def resume(self); def reset(self)   # reset -> index 0
    def run(self, stop_event: threading.Event, on_row: Callable[[dict], None], on_progress: Callable[[dict], None]) -> None
        # executed in a worker thread started by MissionController. Waits (row_dt / speed) between rows using
        # stop_event.wait(small slices) so pause/stop/speed changes react quickly; while paused, waits.
        # on_row receives the row as a plain dict (keys: t, battery, temp, signal, power_draw, packet_loss,
        # packet_type, priority, size_kb, event). Returns when rows exhausted or stop_event set.
```

### 4.10 MissionController (`app/core/mission_controller.py`) — orchestrator & threads
```python
class MissionController:
    def __init__(self, db: DatabaseManager, bus: EventBus, rng_seed: int | None = None)
    # --- read-only state for the UI (thread-safe getters; each takes self._lock briefly) ---
    mission_active: bool; mode: MissionMode|None; mission_id: int|None; mission_code: str; paused (replay)
    def mission_time(self) -> float                     # live: monotonic elapsed; replay: extrapolated replay time
    def met_string(self) -> str
    def orbit_angle_now(self) -> float                  # smooth angle for 30 FPS animation (computed from clock)
    def latest_snapshot(self) -> dict | None
    def pass_info(self) -> dict | None
    counters (property) -> dict: generated, sent, failed, deferred, dropped, corrupted, decisions, incidents
    replay (property) -> ReplayEngine    # the controller owns one ReplayEngine instance
    state (property) -> MissionState

    # --- lifecycle (called from Tk thread) ---
    def start_live_mission(self) -> None
        # ends any active mission first; resets all model objects; db.start_mission(...);
        # seeds 5 packets (HK HIGH, TTC CRITICAL, SSTV MEDIUM, M17 LOW, CODEC2 MEDIUM);
        # starts threads: TelemetryWorker, HealthMonitorWorker, RouterWorker, TransmissionWorker (daemon=True, named)
        # publishes MISSION_STARTED + LOG
    def start_replay_mission(self) -> None      # requires replay.load_csv() done; threads: ReplayWorker (instead of
        # TelemetryWorker), HealthMonitorWorker, RouterWorker, TransmissionWorker. Packets come from CSV rows.
    def stop_mission(self, status: str = "COMPLETED") -> None
        # set mission stop event, join threads (THREAD_JOIN_TIMEOUT), persist queued packets, db.end_mission,
        # publish MISSION_ENDED. Safe to call when no mission.
    def shutdown(self) -> None                  # stop_mission("ABORTED" if active) ; idempotent
    def pause_replay(self); def resume_replay(self); def set_replay_speed(self, speed)
    def reset_replay(self)      # stop_mission("RESET") and replay.reset()

    # --- operator actions (called from Tk thread; thread-safe) ---
    def inject_incident(self, incident_type: IncidentType) -> str     # returns short confirmation message
        # BATTERY_DRAIN: drain over BATTERY_DRAIN_STEPS telemetry ticks to BATTERY_DRAIN_TARGET (live only)
        # THERMAL_SPIKE: inject THERMAL_SPIKE_STEPS heat one per tick (live only) -> ~32→42→53→64 °C
        # SIGNAL_LOSS: attenuation SIGNAL_LOSS_ATTENUATION for SIGNAL_LOSS_DURATION (both modes)
        # COMM_FAILURE: comms.trigger_link_failure(COMM_FAILURE_DURATION); active transmission fails next tick
        # CORRUPTED_PACKET: corrupt() a random queued packet (or create a new HOUSEKEEPING one and corrupt it)
        # PACKET_BURST: add PACKET_BURST_SIZE random packets
        # FORCE_SAFE_MODE: forced_safe = True (until RESTORE_NOMINAL)
        # RESTORE_NOMINAL: clear all incident flags, battery reset to BATTERY_INITIAL, heat cleared,
        #                  temperature reset, link restored (live); in replay only flags are cleared
        # Every injection -> IncidentManager.record + INCIDENT_CREATED + LOG. In replay mode BATTERY_DRAIN and
        # THERMAL_SPIKE return a message explaining telemetry is CSV-driven and do nothing else.
    def request_sstv_downlink(self) -> int   # operator requests an SSTV image: adds SSTV HIGH packet, returns id
    def skip_to_next_pass(self) -> float     # live only: advances orbit clock offset to 3 s before next AOS

    # --- internals ---
    # Workers loop with `while not self._mission_stop.wait(interval):` and wrap each iteration in
    # try/except Exception -> logger.exception (a worker must never die silently).
    # Shared mutable state guarded by self._lock (RLock). Worker threads NEVER touch Tk; they only call
    # bus.publish(...). The UI drains the bus via root.after().
    # Telemetry (live 1 Hz / replay per row) -> _ingest_snapshot(): validate() (TelemetryCorruptionError ->
    #   LOG warning + TELEMETRY_CORRUPTION incident (resolved) and frame discarded), db.insert_telemetry,
    #   pass phase change -> GROUND_PASS_CHANGED + LOG ("Ground pass acquired — AOS" / "Loss of signal — LOS"),
    #   TELEMETRY_UPDATE.
    # Health (0.5 s): HealthMonitor.check -> STATE_CHANGED + db.insert_state_transition + LOG SYSTEM
    #   "State → LOW_POWER"; entering LOW_POWER/THERMAL_ALERT/SAFE_MODE records an automatic incident
    #   (WARNING/WARNING/CRITICAL), leaving resolves it. If the active transmission's mode becomes disallowed,
    #   comms.abort() and the packet returns to queue as DEFERRED with LOG ROUTER "SSTV #211 suspended — THERMAL_ALERT".
    #   Also emits alerts as LOG events and handles link recovery LOG "RF link recovered".
    # Router (0.5 s): live packet generation (every PACKET_GENERATION_INTERVAL s, probability
    #   PACKET_GENERATION_PROBABILITY, type/priority/size from config weights via numpy rng); router.evaluate on
    #   queue.snapshot(); quarantine corrupted (remove, status DROPPED, corrupted=1, db.upsert_packet, CORRUPTED_PACKET
    #   incident, LOG CRITICAL); newly_deferred -> LOG ROUTER "SSTV #211 deferred — <reason>" + db.upsert_packet;
    #   if no active transmission and decision -> status SELECTED, db.insert_decision, PACKET_SELECTED,
    #   comms.begin, TRANSMISSION_STARTED, LOG ROUTER; always publish QUEUE_UPDATE.
    # Transmission (0.1 s): dt = 0.1 * time_scale (replay speed; 0 while paused); comms.step; publish
    #   TRANSMISSION_PROGRESS each tick; on completion -> SENT, transmitted_at, remove from queue, db.upsert_packet,
    #   TRANSMISSION_COMPLETE, LOG INFO "TT&C #204 transmitted (4 KB, 2.1 s)". On CommunicationFailureError ->
    #   retry policy: retry_count += 1; if retry_count <= packet.max_retries: status QUEUED (requeued) else FAILED
    #   (removed from queue); db.upsert_packet; TRANSMISSION_FAILED; LOG CRITICAL. On TelemetryCorruptionError during
    #   transmit -> quarantine like the router does.
    # Replay row -> snapshot (voltage computed from battery; system_state = current state) -> _ingest_snapshot;
    #   packet from row if packet_type not blank; row event -> inject_incident; REPLAY_PROGRESS; when rows exhausted
    #   the ReplayWorker calls stop_mission("COMPLETED") from a helper thread-safe path (do not join the current
    #   thread: skip joining threading.current_thread()).
    # Packet IDs are globally unique: start from db.next_packet_id().
```

---------------------------------------------------------------------------------------------------
## 5. Database — `app/database/database_manager.py`

One `sqlite3.Connection(check_same_thread=False)` guarded by a `threading.Lock`; every write uses
`with self._lock, self._conn:` (transaction context manager); all SQL parameterised; `PRAGMA foreign_keys=ON`;
`sqlite3.Error` is wrapped into `DatabaseOperationError`. Schema created automatically (`CREATE TABLE IF NOT EXISTS`).
Constructor accepts a path (use ":memory:" in tests); creates parent directory.

```sql
missions(mission_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_code TEXT, mission_name TEXT, mode TEXT,
         started_at TEXT, ended_at TEXT, status TEXT, notes TEXT)
telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, timestamp TEXT, mission_time REAL,
          battery REAL, temperature REAL, signal REAL, power_draw REAL, packet_loss REAL, system_state TEXT,
          FOREIGN KEY(mission_id) REFERENCES missions(mission_id))
packets(packet_id INTEGER PRIMARY KEY, mission_id INTEGER, packet_type TEXT, priority TEXT, size_kb REAL,
        status TEXT, created_at TEXT, selected_at TEXT, transmitted_at TEXT, retry_count INTEGER,
        corrupted INTEGER, mode TEXT, score REAL, FOREIGN KEY ...)
decisions(decision_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, packet_id INTEGER, timestamp TEXT,
          mission_time REAL, selected_mode TEXT, total_score REAL, priority_score REAL, link_score REAL,
          urgency_score REAL, energy_score REAL, waiting_score REAL, battery REAL, temperature REAL, signal REAL,
          system_state TEXT, reason TEXT, FOREIGN KEY ...)
incidents(incident_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, timestamp TEXT, mission_time REAL,
          incident_type TEXT, severity TEXT, description TEXT, resolved INTEGER, FOREIGN KEY ...)
state_transitions(id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, timestamp TEXT, mission_time REAL,
          from_state TEXT, to_state TEXT, reason TEXT, FOREIGN KEY ...)
```
Indexes on mission_id for child tables.

```python
class DatabaseManager:
    def __init__(self, db_path: str | Path)
    def start_mission(self, mode: str, name: str = "", notes: str = "") -> tuple[int, str]   # (mission_id, mission_code)
        # mission_code = helpers.mission_code(date, n) e.g. "SMC-20260925-003" (n = missions started that day + 1)
    def end_mission(self, mission_id, status)
    def insert_telemetry(self, mission_id, snapshot: TelemetrySnapshot)
    def upsert_packet(self, mission_id, packet: DataPacket)      # INSERT ... ON CONFLICT(packet_id) DO UPDATE
    def insert_decision(self, mission_id, decision: RoutingDecision) -> int
    def insert_incident(self, mission_id, incident: Incident) -> int
    def resolve_incident(self, incident_id)
    def insert_state_transition(self, mission_id, old, new, reason, mission_time)
    def next_packet_id(self) -> int                               # max(packet_id)+1 or 100
    def get_missions(self, search: str = "", mode: str | None = None) -> list[dict]
        # each: mission_id, mission_code, mission_name, mode, started_at, ended_at, status, duration_s,
        #       packets, sent, attempts (decisions count), success_rate (sent/attempts*100 or None), incidents
    def get_mission(self, mission_id) -> dict | None
    def fetch_table(self, table: str, mission_id: int, limit: int | None = None) -> list[dict]
        # table whitelisted: telemetry, packets, decisions, incidents, state_transitions
    def read_dataframe(self, table: str, mission_id: int) -> pandas.DataFrame   # pd.read_sql_query, whitelisted
    def close(self)   # idempotent
```

---------------------------------------------------------------------------------------------------
## 6. Analytics — `app/analytics/analytics_engine.py`

Uses pandas/numpy for data, matplotlib `Figure` objects (NOT pyplot state) and seaborn with `ax=`.
```python
@dataclass
class MissionData: mission: dict; telemetry: pd.DataFrame; packets: pd.DataFrame; decisions: pd.DataFrame;
                   incidents: pd.DataFrame
    empty (property)
class AnalyticsEngine:
    def __init__(self, db: DatabaseManager, exports_dir=config.EXPORTS_DIR)
    def load(self, mission_id) -> MissionData
    def summary(self, data) -> dict
        # keys: mission_code, mode, duration_s, duration (str), packets_generated, packets_transmitted, packets_failed,
        # packets_deferred (count of packets ever DEFERRED — use decisions/packets status), packets_corrupted,
        # packets_dropped, attempts, success_rate, avg_signal (in-pass rows only, signal >= 8), avg_battery,
        # min_battery, peak_temperature, avg_power_draw, battery_std (numpy), signal_std, count_by_type (dict type->n),
        # sent_by_type (dict), safe_mode_activations, communication_failures, thermal_alerts, low_power_events,
        # incident_count
    def telemetry_stats(self, data) -> dict      # numpy mean/std/min/max per metric (uses map() over column list)
    def success_by_type(self, data) -> pd.DataFrame     # groupby packet_type: generated, sent, failed, success_rate
    def mode_performance(self, data) -> pd.DataFrame    # groupby selected_mode on decisions: attempts, avg_score, avg_signal
    # Figure builders: each takes a matplotlib Figure (cleared inside) + data, styles for dark UI via
    # apply_dark_style(fig, axes) (module-level helper; colours from a DARK_CHART dict defined in this module)
    def plot_timeline(self, fig, data)            # battery & signal vs mission_time (twin axis or 2 rows) + temperature
    def plot_packet_outcomes(self, fig, data)     # stacked bar status counts by packet type
    def plot_mode_performance(self, fig, data)    # seaborn barplot of success % / avg score by mode
    def plot_correlation_heatmap(self, fig, data) # seaborn heatmap of battery/temperature/signal/power_draw/packet_loss
    def plot_incident_distribution(self, fig, data)  # seaborn countplot by incident_type (hue severity)
    # Each plot must render a centred "No data yet" message instead of raising when data is empty.
    def export_table(self, mission_id, table) -> Path    # exports/<table>_YYYY-MM-DD_HHMM.csv (telemetry/packets/decisions)
    def save_summary(self, mission_id) -> Path           # exports/summary_<code>_YYYY-MM-DD_HHMM.txt (formatted text)
```

---------------------------------------------------------------------------------------------------
## 7. Utils

* `helpers.py`: `format_met(seconds) -> "HH:MM:SS"`, `format_countdown(seconds) -> "MM:SS"`, `now_iso()`,
  `mission_code(date, n) -> "SMC-YYYYMMDD-NNN"`, `timestamped_filename(prefix, ext) -> f"{prefix}_{YYYY-MM-DD_HHMM}.{ext}"`,
  `ensure_directories()` (assets, data, exports, logs).
* `validation.py`: `clamp(v, lo, hi)`, `is_valid_percentage(v)`, `parse_timestamp(value) -> float seconds`
  (raises ValueError), `normalize_label(s) -> str` (strip/upper, "TT&C"->"TTC").
* `logging_config.py`: `setup_logging()` → RotatingFileHandler to `logs/somaiyasat.log` (INFO), console WARNING only.
* `sample_data.py`: `generate_sample_missions(data_dir, overwrite=False) -> list[Path]` writes
  `sample_mission.csv` (~420 rows / 7 min, healthy, 2 passes, mixed packets in ~35 % of rows) and
  `stressful_mission.csv` (~480 rows: battery decline to ~13 %, thermal rise to ~72 °C and recovery, weak-link
  interval, a packet burst/congestion period, one COMM_FAILURE event and one CORRUPTED_PACKET event in the `event`
  column, then recovery). NumPy-generated, deterministic seed, timestamps "HH:MM:SS".
* `asset_factory.py`: `build_sstv_test_image(width=320, height=256) -> PIL.Image` (attractive procedural
  "Earth from orbit" test card: space gradient, Earth limb with clouds, SomaiyaSat caption, SSTV-style colour bars
  strip, timestamp band); `ensure_sstv_image(path) -> PIL.Image` loads path (try/except OSError/UnidentifiedImageError)
  or builds + saves the test image.

---------------------------------------------------------------------------------------------------
## 8. Threading rules (non-negotiable)

1. Worker threads never call any Tk method. They only mutate backend objects under `self._lock` and call
   `bus.publish()`.
2. The Tk main thread drains the bus every `UI_POLL_INTERVAL_MS` using `root.after()`.
3. Graceful shutdown: `threading.Event` per mission; `stop_mission` sets it and joins threads; `shutdown()` is
   called from the window close handler, followed by `db.close()`.
4. No unbounded growth: deques with maxlen for history; queue capped at MAX_QUEUE_SIZE.

---------------------------------------------------------------------------------------------------
## 9. UI (Tkinter) contract

* `main.py`: Windows DPI awareness (`ctypes.windll.shcore.SetProcessDpiAwareness(1)` in try/except), ensure dirs,
  setup logging, generate sample CSVs / SSTV image if missing, `MissionControlApp().mainloop()`.
* `app/application.py` `MissionControlApp(tk.Tk)`: builds EventBus, DatabaseManager(DB_PATH), MissionController,
  AnalyticsEngine, UIState; landing page first; "ENTER MISSION CONTROL" builds the shell (sidebar + top bar + 7
  pages) and starts a live mission; polls bus via `after`; updates UIState then forwards each event to every page's
  `handle_event(event)`; close handler confirms if a mission is active, then controller.shutdown(), db.close(), destroy.
* `app/ui/ui_state.py` `UIState`: latest snapshot/pass/counters, `history` dict of deques (maxlen
  TELEMETRY_HISTORY_LENGTH) for mission_time, battery, temperature, signal, power_draw, packet_loss; queue records;
  last decision; active transmission; comm stats; incidents list; feed entries; min/max trackers. `apply(event)`.
* Pages subclass `BasePage(tk.Frame)` with `on_show()`, `on_hide()`, `handle_event(event)` (polymorphic).
* Pages: landing, overview, telemetry, router, communications, incidents, analytics (replay + analytics +
  summary), archive — see project brief. Theme tokens & reusable widgets in `app/ui/theme.py` and
  `app/ui/components.py`.
```
