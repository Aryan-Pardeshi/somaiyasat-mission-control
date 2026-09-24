# Mini-Project Report

## SomaiyaSat Mission Control: An Autonomous Satellite Operations Digital Twin

**Course:** Python Programming (Mini-Project)  **Branch:** B.Tech Information Technology, Second Year
**Use case:** SomaiyaSat & SomaiyaPod: A PocketQube Mission featuring Autonomous AI-Based Inter-Satellite
Data Routing and Advanced Multi-Mode Amateur Radio Payloads (M17, Codec2, SSTV, & TT&C / Housekeeping)
**Application vertical:** Space Technology and Remote Sensing

---

## Abstract

PocketQube satellites are extremely constrained in power, computation, bandwidth and contact time with
the ground. This project builds **SomaiyaSat Mission Control**, a desktop digital twin written in Python.
It simulates the SomaiyaSat mission end to end:

* generating telemetry;
* monitoring health through an explicit state machine;
* queueing mission data packets;
* deciding autonomously which packet to downlink, and through which radio mode (TT&C, SSTV, M17 or
  Codec2).

The decision engine combines hard safety rules with a transparent weighted score, and it records a
human-readable explanation for every decision. An operator can inject faults, replay recorded missions
from CSV and analyse every mission stored in SQLite.

The application demonstrates the course outcomes on one realistic problem:

* object-oriented design (inheritance, abstract classes, polymorphism, encapsulation);
* a modern Tkinter GUI;
* SQLite connectivity;
* multithreading with thread-safe queues;
* exception handling;
* data analysis with NumPy, Pandas, Matplotlib and Seaborn.

## 1. Introduction

A digital twin is a software model that behaves like a real system, so the system can be observed,
tested and understood without touching the hardware. Satellite operators use such simulators to rehearse
passes and failure scenarios. This project builds a mission-control digital twin for SomaiyaSat, a
PocketQube satellite deployed by SomaiyaSat's deployer, SomaiyaPod. The twin is a capstone that brings
together all the earlier laboratory experiments in one polished application.

## 2. Problem statement

Design and implement a Python desktop application that simulates a constrained satellite mission and
contains an **autonomous decision component**. That component must decide *what* data to transmit,
*when*, *through which communication mode*, and *what to postpone or suspend* for safety. It must explain
and log every decision, and the application must integrate OOP, a GUI, database connectivity and
multithreading.

## 3. Background / existing problem

* **Short contact windows.** A low-Earth-orbit satellite is visible to a ground station for only a few
  minutes per orbit (from AOS to LOS). Data that is not sent in that window waits a whole orbit.
* **Competing data.** Critical health telemetry (TT&C / housekeeping) must never be blocked by large
  images (SSTV) or voice traffic (M17 / Codec2).
* **Power and thermal limits.** Transmitting drains the battery and heats the spacecraft. Transmitting
  at the wrong time can push the satellite into an unsafe state.
* **Trust.** Autonomous systems in space must be predictable and explainable. An opaque black-box
  model is hard to verify.

## 4. Proposed solution

A two-layer **Autonomous Router** runs every 0.5 s:

1. **Safety rules (Layer 1)** remove every packet that must not be sent right now: no ground pass,
   link down, a mode suspended by the current state, too little signal, too much energy in low-power
   mode, or not enough time before LOS. Corrupted packets are detected by a CRC check and quarantined.
2. **Weighted scoring (Layer 2)** ranks the remaining packets with
   `score = 0.35·priority + 0.25·link + 0.15·urgency + 0.15·energy + 0.10·waiting`.
   The best packet is transmitted through its polymorphic communication-mode object.

A **mission state machine** (NOMINAL, LOW_POWER, DEGRADED_LINK, THERMAL_ALERT, SAFE_MODE,
COMMUNICATION_LOSS) with hysteresis changes what the router is allowed to do. Everything is shown live
in the GUI and stored in SQLite for later analysis.

## 5. Objectives

1. Model real-world entities (satellite, subsystems, packets, radio modes, ground pass) using OOP.
2. Implement an explainable autonomous decision engine without machine learning.
3. Build a responsive, modern Tkinter GUI with live charts and animations.
4. Use multithreading correctly, with thread-safe communication to the GUI.
5. Persist all mission data in a normalised SQLite database.
6. Import, validate and replay CSV mission data with Pandas.
7. Analyse missions with NumPy statistics, Matplotlib charts and Seaborn plots.
8. Handle faults and bad input gracefully with custom exceptions and logging.

## 6. Scope

**In scope:** a single simulated satellite and ground station, a simplified 2D orbit and pass model,
four simulated radio modes, operator fault injection, CSV replay, SQLite archive, analytics and exports.

**Out of scope:** real RF communication, real protocol encoding, orbital mechanics, flight-qualified
software, authentication and networking.

## 7. Technologies

| Technology | Purpose |
|---|---|
| Python 3.10+ (tested on 3.14) | language |
| Tkinter / ttk / Canvas | GUI, animations, custom widgets |
| threading, queue | worker threads, thread-safe event bus |
| sqlite3 | persistent mission archive |
| Pandas | CSV import and validation, SQL→DataFrame, grouping, exports |
| NumPy | noise, random generation, statistics, image processing |
| Matplotlib | live and historical charts embedded in Tkinter |
| Seaborn | correlation heatmap, mode performance, incident distribution |
| Pillow | SSTV image handling, rendered Earth image |
| OpenCV (optional) | looping video background on the landing screen |
| pytest | 62 automated tests |
| logging | rotating log file `logs/somaiyasat.log` |

## 8. System architecture

```
Tkinter GUI (main thread) ◄── root.after() drains ── EventBus (queue.Queue) ◄── worker threads
        │ operator actions                                                         ▲
        ▼                                                                          │
MissionController ── TelemetrySimulator (Satellite: PowerSystem, ThermalSystem)    │
        │           GroundPass / ReplayGroundPass                                  │
        │           HealthMonitor + StateMachine                                   │
        │           PacketQueue ─► AutonomousRouter (SafetyRules + scoring)        │
        │           CommunicationSystem (TTCMode, SSTVMode, M17Mode, Codec2Mode) ──┘
        │           IncidentManager
        ▼
DatabaseManager ─► SQLite ─► AnalyticsEngine (Pandas / NumPy / Matplotlib / Seaborn)
CSV ─► ReplayEngine (Pandas validation) ─► MissionController (same pipeline as live)
```

Data flow per mission: telemetry → health check → packet generation → queue → router → radio mode →
ground station → SQLite → analytics, replay and reports.

## 9. Module descriptions

| Module | Responsibility |
|---|---|
| `app/config.py` | Every threshold, weight, timing and simulation constant (no magic numbers elsewhere). |
| `app/models/enums.py` | `PacketType`, `PacketPriority`, `PacketStatus`, `CommunicationType`, `MissionState`, `IncidentSeverity`, `IncidentType`, `PassPhase`, `MissionMode`. |
| `app/models/telemetry.py` | `TelemetrySnapshot` dataclass with `validate()`, which raises `TelemetryCorruptionError`. |
| `app/models/packet.py` | `DataPacket` hierarchy, CRC32 integrity check, `create_packet()` factory. |
| `app/models/communication_modes.py` | `CommunicationMode` ABC and the TT&C, SSTV, M17 and Codec2 implementations. |
| `app/models/satellite.py` | `PowerSystem`, `ThermalSystem` (encapsulated state) and `Satellite` (composition). |
| `app/models/mission_state.py` | `StateMachine` with priority ordering and hysteresis. |
| `app/core/event_bus.py` | `EventBus`: thread-safe queue of plain-data events for the GUI. |
| `app/core/ground_pass.py` | Pass lifecycle (PRE-PASS / AOS / ACTIVE / LOS), countdowns, signal profile. |
| `app/core/packet_queue.py` | Thread-safe packet list with an overflow policy and `filter()`-based selection. |
| `app/core/router.py` | `SafetyRules`, `AutonomousRouter`, `RoutingDecision`, the explanation text. |
| `app/core/communication_system.py` | Active transmission, per-mode statistics, link failure. |
| `app/core/health_monitor.py` | Runs the state machine, reports threshold crossings once. |
| `app/core/incident_manager.py` | Records and resolves incidents (memory + SQLite). |
| `app/core/simulator.py` | One live telemetry frame: power, thermal, signal and packet loss. |
| `app/core/replay_engine.py` | Pandas CSV validation and paced replay (speed, pause, resume, reset). |
| `app/core/mission_controller.py` | Mission lifecycle, the 5 worker threads, incident injection. |
| `app/database/database_manager.py` | Schema creation and every SQL statement. |
| `app/analytics/analytics_engine.py` | Summaries, statistics, charts and exports. |
| `app/ui/*` | Theme, reusable widgets, rendered Earth, orbit animation, landing screen, 7 pages. |
| `app/utils/*` | Logging, helpers (MET format, mission codes), validation, sample data, SSTV test image. |

## 10. OOP implementation

* **Classes and objects:** more than 60 classes. Each mission creates fresh objects
  (`Satellite()`, `PacketQueue()`, `CommunicationSystem()` …).
* **Constructors:** `DataPacket.__init__` validates its input (raising `InvalidPacketError`) and
  computes a checksum. `PowerSystem.__init__` clamps the starting charge.
* **Encapsulation and data hiding:** `PowerSystem.__battery` and `ThermalSystem.__temperature` are
  name-mangled private attributes. They can only be changed through methods that enforce valid ranges.
* **Inheritance:**
  * `DataPacket` → `TTCPacket`, `HousekeepingPacket`, `SSTVPacket`, and `VoicePacket` → `M17Packet`, `Codec2Packet`;
  * `CommunicationMode` → `DigitalLinkMode` → `TTCMode`, `M17Mode`, `Codec2Mode`, and `CommunicationMode` → `SSTVMode`;
  * `GroundPass` → `ReplayGroundPass`;
  * `BasePage` → 7 GUI pages;
  * `tk.Canvas` → `OrbitView`, `StatusBadge`, `ModernButton`.
* **Abstract classes:** `CommunicationMode(ABC)` declares `minimum_signal_required`,
  `estimate_transmission_time` and `transmit` as `@abstractmethod`. It cannot be instantiated, and
  a test proves this.
* **Polymorphism:** the router and the comms system call `mode.transmit(packet, signal, dt)` without
  knowing the class.
  * `TTCMode` is robust at low signal.
  * `M17Mode` has a steep S-curve.
  * `Codec2Mode` degrades gently.
  * `SSTVMode` sends whole scan lines at a fixed speed and turns weak signal into picture noise.

  The GUI pages are also called polymorphically (`page.handle_event(event)`).
* **Overriding with `super()`:** `SSTVMode.calculate_energy_cost()` adds the encoder energy to the
  parent's template method.

## 11. Database design

Six tables. `missions` is the parent table, and `telemetry`, `packets`, `decisions`, `incidents` and
`state_transitions` reference it through `mission_id` foreign keys, with indexes on `mission_id`.

**ER-style description**

* One **Mission** has many **Telemetry** rows (one per second).
* One **Mission** has many **Packets**. A packet has one current status (QUEUED, SENT, FAILED,
  DROPPED …) and is updated in place with an UPSERT (`INSERT … ON CONFLICT DO UPDATE`).
* One **Mission** has many **Decisions**. Each decision refers to the packet it selected and stores
  all five score components, the battery, temperature, signal and state at that moment, and the reason text.
* One **Mission** has many **Incidents** (injected or automatic), each with a severity and a resolved flag.
* One **Mission** has many **State transitions** (from_state → to_state, reason).

All queries are parameterised. Writes run inside `with connection:` transactions protected by a lock,
because several worker threads write. Table names are checked against a whitelist.

## 12. Autonomous routing logic

| Component (0–100) | Meaning | Weight |
|---|---|---|
| Priority | CRITICAL 100, HIGH 80, MEDIUM 55, LOW 30 | 0.35 |
| Link | 50 at the mode's minimum signal, up to 100 on a perfect link | 0.25 |
| Urgency | TT&C 100, Housekeeping 75, Codec2 50, M17 45, SSTV 35 | 0.15 |
| Energy | 100 − (energy / 40 J × 100) × battery pressure | 0.15 |
| Waiting | age / 150 s × 100 (fairness, prevents starvation) | 0.10 |

**Example.** Battery 84.3 %, temperature 31.7 °C, signal 78 %. The queue holds Housekeeping #103 HIGH,
TT&C #104 CRITICAL, SSTV #105 MEDIUM and M17 #106 LOW. The router selects **#104 with 88.0 points**:
priority 35.0, and its low energy cost and highest urgency add the rest. Its stored reason reads:
*"Packet #104 was selected because it contains critical TT&C data … The current ground link (78 %)
comfortably exceeds the 15 % that TT&C needs …"*.

**Complexity:** every cycle scores each queued packet once, which is O(n) with n ≤ 40. That is
negligible, and it lets scores change as packets age and as signal and battery change.

## 13. Multithreading

Five worker threads: telemetry (1 Hz) or replay, health monitor (2 Hz), router (2 Hz) and
transmission (10 Hz).

* Shared objects are guarded by a `threading.RLock`.
* Workers never call Tkinter. They publish dictionaries to a `queue.Queue` (`EventBus`), and the GUI
  drains it every 50 ms with `root.after()`.
* A per-mission `threading.Event` lets `stop_mission()` stop and join every worker. The window's close
  handler ends the mission, closes the database and destroys the window, which leaves no dangling threads.

The integration test `test_live_mission_runs_threads_logs_to_database_and_shuts_down` verifies this.

## 14. GUI design

Apple-inspired dark "glass" style:

* a graphite background with rounded cards drawn on a Canvas;
* semantic colours: green nominal, amber warning, red critical, cyan active;
* system fonts (Segoe UI / SF Pro) with DPI-aware scaling.

Reusable widgets live in `components.py`: `Card`, `MetricCard`, `StatusBadge`, `ModernButton`,
`SidebarButton`, `DataTable`, `EventFeed`, `ScoreBar`, `ProgressBar`, `SegmentedControl`, `Tooltip` and
`TermLabel` (glossary tooltips for AOS, LOS, TT&C, SSTV, M17 and Codec2).

The showpieces:

* the landing screen, with an optional OpenCV video and an automatic Canvas fallback;
* the Earth, rendered once with NumPy lighting;
* the animated orbit view, with a ground-station beam during passes;
* the progressive SSTV downlink viewer.

Animations only move existing canvas items (`coords()`), and heavy images are rendered only when the
window is resized, which keeps the UI smooth.

## 15. CSV and Pandas integration

`ReplayEngine.load_csv()`:

1. reads the file with Pandas;
2. normalises the column names and labels (`str.strip().upper()`, `TT&C` → `TTC`);
3. converts numbers with `pd.to_numeric(errors="coerce")`;
4. validates every row (ranges, allowed types, priorities and sizes);
5. collects readable errors;
6. drops the invalid rows;
7. detects ground-pass windows from the signal column.

The replay worker then feeds each row through the same controller pipeline as live telemetry, at
0.5×, 1×, 2× or 5× speed, with pause, resume and reset.

## 16. Analytics

* **Summary KPIs:**
  * mission and packets: duration, packets generated / transmitted / failed / deferred / corrupted /
    dropped, success rate;
  * telemetry: average link quality, average and minimum battery, peak temperature, average power;
  * counts by packet type;
  * events: safe-mode activations, comm failures, thermal alerts, low-power events.
* **NumPy statistics:** mean, standard deviation, minimum and maximum for each telemetry channel, using
  `map()` over the metric names.
* **Charts:**
  * telemetry timeline (Matplotlib, with threshold lines);
  * packet outcomes by type (Pandas `crosstab`);
  * communication-mode performance (Seaborn);
  * telemetry correlation heatmap (Seaborn);
  * incident distribution (Seaborn).
* **Exports:** timestamped telemetry, packet and decision CSVs, plus a formatted summary text file, in `exports/`.

## 17. Exception handling

| Situation | Handling |
|---|---|
| Corrupted telemetry frame (NaN / out of range) | `TelemetrySnapshot.validate()` raises `TelemetryCorruptionError`. The frame is discarded, a warning is logged and a resolved incident is recorded. |
| Corrupted packet (CRC mismatch) | `verify_integrity()` raises `TelemetryCorruptionError`. The packet is quarantined (DROPPED) and a critical incident is recorded. |
| RF link lost mid-transmission | `CommunicationSystem.step()` raises `CommunicationFailureError`. The retry policy requeues the packet or marks it FAILED. |
| Bad packet parameters | `InvalidPacketError` from the constructor / factory. |
| SQLite error | wrapped as `DatabaseOperationError`. The workers log it once and keep running. If the DB file cannot be opened, the app falls back to `:memory:`. |
| Bad CSV (missing file, missing columns, no valid rows) | `ReplayDataError`, shown in a red validation card. |
| Missing video / image / folders | automatic fallback or regeneration; the app never crashes. |
| Any worker iteration error | `logger.exception`; the worker continues. |

## 18. Testing

`python -m pytest -v` runs **62 tests**:

* router: critical priority, low-signal filtering, starvation prevention, low-power and safe-mode
  behaviour, no pass, link down, quarantine, the LOS rule, score arithmetic and the explanation text;
* state machine: every transition, hysteresis and forced safe mode;
* database: schema creation, missions, telemetry, packet upsert, decisions, incidents, transitions,
  aggregates and table whitelisting;
* replay: valid and invalid CSVs, missing columns and files, timestamp formats, and validation of the
  bundled samples;
* packets and queue: the factory, validation, eviction, `filter()` selection, status changes and CRC;
* communication modes: the ABC, polymorphic timing and energy;
* ground pass: phases, countdowns and the signal curve;
* analytics: summaries, statistics, charts with and without data, and exports;
* threaded integration tests for a live mission, a thermal incident and a CSV replay.

The GUI was tested manually and with scripted screenshots at 1366×768 and 1440×900.

## 19. Results

* The application starts with `python main.py` and needs no setup.
* A live mission shows continuous telemetry, pass countdowns, autonomous decisions with explanations,
  and SSTV images arriving line by line.
* A thermal spike raises the temperature to about 65 °C. The system enters THERMAL_ALERT within a
  second, suspends SSTV, M17 and Codec2, and logs the incident. RESTORE returns it to NOMINAL.
* The stressful replay drives the satellite through LOW_POWER and SAFE_MODE, a weak link, congestion,
  a communication failure and a corrupted packet. In one test replay, 50 of 52 transmission attempts
  succeeded (96 %). CRITICAL traffic continued in safe mode, and the corrupted packet was quarantined.
* All missions appear in the archive with their full telemetry, decision and incident history.

## 20. Limitations

* 2D orbit and pass model with compressed time; no orbital mechanics or real link budget.
* Simulated power, thermal and radio parameters.
* No real protocol encoding: the SSTV view is a visual simulation, not an RF encoder.
* One satellite and one ground station.

## 21. Future scope

* TLE-based pass prediction and multiple ground stations.
* Explicit inter-satellite relay routes between SomaiyaSat and SomaiyaPod.
* Weight tuning from archived missions, kept explainable.
* Hardware-in-the-loop telemetry over serial.
* PDF reports.

## 22. Conclusion

SomaiyaSat Mission Control shows how a constrained satellite can make safe, explainable, autonomous
routing decisions using clear rules and scoring instead of an opaque model. At the same time, it applies
every major Python concept from the course in one coherent, demonstrable application: OOP, GUI,
database, multithreading, exception handling and data analysis.

---

## Appendix A: Course outcome mapping

| CO | Requirement | Where it is demonstrated |
|---|---|---|
| **CO1** | Describe OOP principles: classes, objects, inheritance, encapsulation, data hiding, polymorphism | `models/satellite.py` (encapsulation, `__battery`); `models/packet.py` (inheritance); `models/communication_modes.py` (ABC + polymorphism, documented class diagram); VIVA_GUIDE Q4–Q10 |
| **CO2** | Implement OOP to model real-world entities and relationships | Satellite *has* PowerSystem + ThermalSystem (composition); packet hierarchy; four radio-mode classes; GroundPass → ReplayGroundPass; the router, queue and controller as collaborating objects |
| **CO3** | NumPy, Matplotlib, Pandas, Seaborn for analysis and visualisation | NumPy: simulator noise, statistics, rendered Earth. Pandas: `replay_engine.py`, `analytics_engine.py`, exports. Matplotlib: live telemetry charts, timeline, outcomes. Seaborn: heatmap, mode performance, incident plot |
| **CO4** | GUI, database connectivity, multithreading | Tkinter shell and 8 screens (`app/ui`); SQLite `DatabaseManager`; 5 worker threads + `queue.Queue` + `root.after()` in `mission_controller.py` / `application.py` |

## Appendix B: Mapping of previous lab experiments

| Lab experiment | How it appears in the final project |
|---|---|
| 1. Classes and objects | `Satellite`, `DataPacket`, `PacketQueue`, `AutonomousRouter` … one object graph per mission |
| 2. Constructors and lists | validating constructors; `available_routes` list of modes; packet queue list; event feed |
| 3. String handling and inheritance | label normalisation (`TT&C` → `TTC`), mission codes `SMC-YYYYMMDD-NNN`, MET formatting, explanation text; packet inheritance |
| 4. Abstract classes and polymorphism | `CommunicationMode(ABC)` and its 4 implementations; polymorphic `transmit()` |
| 5. Exception handling, modules, multithreading | 5 custom exceptions; package split into models/core/database/analytics/ui/utils; 5 worker threads |
| 6. Collections and functional programming | dict (config maps, telemetry snapshots), list, set (`SUPPORTED_MODES`), deque (rolling telemetry), `lambda` (sort / max by score), `filter()` (eligible packets), `map()` (statistics, label normalisation) |
| 7. GUI dashboard | the full Tkinter mission-control dashboard; Canvas-drawn logo, orbit and satellite |
| 8. SQLite database system | six-table mission archive with a search UI |
| Earlier SomaiyaSat experiments | telemetry and health modules → simulator + health monitor; threads for battery / comm / temperature → worker threads; handling comm failures and corrupted telemetry → incident simulator; autonomous routing on signal / priority / destination / mode → the two-layer router |
