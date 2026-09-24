# SomaiyaSat Mission Control — Requirements

Desktop Python mini-project (2nd-year B.Tech IT). Subtitle: **Autonomous Satellite Operations Digital Twin**.
A Tkinter mission-control simulator for the SomaiyaSat PocketQube (deployer: SomaiyaPod).

Academic requirement: "Design, implementation, documentation, demonstration, and viva of an AI use case
integrating Python OOP, GUI, database connectivity, and multithreading concepts."
Use case: "SomaiyaSat & SomaiyaPod: A PocketQube Mission featuring Autonomous AI-Based Inter-Satellite Data Routing
and Advanced Multi-Mode Amateur Radio Payloads (M17, Codec2, SSTV, & TT&C / Housekeeping)". Vertical: Space
Technology and Remote Sensing.

Course outcomes: CO1 OOP principles (classes, objects, inheritance, encapsulation, data hiding, polymorphism);
CO2 implement OOP to model real entities; CO3 NumPy, Matplotlib, Pandas, Seaborn; CO4 GUI + database + multithreading.
Previous labs to build upon: classes/objects, constructors & lists, strings & inheritance, abstract classes &
polymorphism, exception handling/modules/multithreading, collections & functional programming (dict, list, set,
deque, lambda, filter, map), GUI dashboard (Tkinter Canvas logo), SQLite system, satellite telemetry monitoring
with threads for battery / comm status / temperature, handling comm failures and corrupted telemetry.

Rubric: Problem analysis & design 3/3, Implementation & demonstration 5/5, Documentation & viva 2/2.

## Hard constraints
* Tkinter (tk, ttk, Canvas) GUI only. Pillow for images, OpenCV only for the optional video background.
* SQLite, Pandas + CSV, NumPy, Matplotlib (embedded via FigureCanvasTkAgg), Seaborn, threading, exception handling.
* NO web frameworks, NO auth, NO cloud, NO LLM chatbot, NO ML / deep learning. Offline. `python main.py` just works.
* The "AI" = lightweight autonomous decision engine: Layer 1 safety rules + Layer 2 transparent weighted
  packet scoring. Must be explainable and logged. Never call it machine learning.
* Nothing faked: real scores, real DB writes, real threads, real progressive SSTV reveal, real progress.
* It is a simulation / digital twin — no real RF, no real spacecraft control. Disclaimer in About/docs:
  "This project is an educational software simulation/digital twin inspired by the SomaiyaSat mission use case.
  It does not communicate with real spacecraft hardware, implement actual RF protocols, or provide flight-qualified
  control logic."
* Missing video / image / exports dir / DB must never crash the app (fallbacks).
* Readable when projected: no ultra-small grey text; main metrics large.

## Visual direction
Clean futuristic **Apple-style** mission control. Graphite / near-black background, soft white text, dark glass-like
cards with subtle borders, rounded cards drawn with Canvas, generous spacing, minimal semantic accents
(green nominal, amber warning, red critical, blue/cyan active comm/info, neutral grey inactive), subtle animation,
hover states, system fonts (Segoe UI Variable / Segoe UI on Windows, SF Pro on macOS), cohesive dark charts.
NOT cyberpunk, NOT rainbow, NOT grey default Tk buttons, NOT crowded. Must look good at 1366×768, 1440×900,
1920×1080; sensible minimum window size; layouts use grid weights, not hard-coded coordinates.

## Screens (one window, one shell; persistent sidebar after entering)
1. **Landing** — "SOMAIYASAT" / "MISSION CONTROL" / subtitle; looping video `assets/earth_orbit_loop.mp4` with dark
   overlay if present (OpenCV VideoCapture → resize → BGR→RGB → ImageTk via after(); loop; keep PhotoImage ref;
   fallback on any error). Otherwise a polished Canvas fallback: dark starfield with slowly moving stars, stylised
   Earth, orbit line, small satellite moving along the orbit. Canvas-drawn SomaiyaSat logo. Animated init sequence:
   "INITIALIZING TELEMETRY BUS...", "POWER SYSTEM ONLINE", "RF STACK READY", "ROUTING ENGINE READY",
   "GROUND STATION LINK READY", then "SYSTEM READY" and an "ENTER MISSION CONTROL" button.
2. **Overview** — top bar (title, mission ID, MET clock, overall state, ground-link state). Hero: 2D animated
   orbit (Earth, orbit ring, moving satellite, ground-station marker, beam when in pass, current comm mode).
   Metric cards: Battery %, Signal %, Temperature °C, Power draw W, Queue length. Ground pass card (AOS/LOS, pass
   progress, countdown "LOS IN 06:42" / "NEXT AOS IN 03:20", status PRE-PASS/AOS/ACTIVE PASS/LOS). Autonomous
   decision card ("TRANSMIT TT&C PACKET #104", score, reasons, current mode, "WHY THIS DECISION?" expandable).
   Recent event feed with severity colours ("00:05:12  INFO  Ground pass acquired").
3. **Live Telemetry** — current values + min/max + status labels for battery, voltage, temperature, signal, power,
   packet loss, queue size, comm state; embedded Matplotlib live charts (battery, temperature, signal, power) from
   a deque rolling buffer (~180 points), redrawn ~1 Hz efficiently (set_data, draw_idle, only when visible).
4. **Autonomous Router** — modern queue table (ID, Type, Priority, Size, Age, Required Signal, Est. Energy, Score,
   Status); selected packet card (type, priority, size, score) with breakdown (Priority +35.0, Link +22.1, …, TOTAL)
   as bars; "WHY THIS DECISION?" natural-language explanation; active safety rules panel; recent decisions list.
5. **Communications** — cards for TT&C, SSTV, M17, Codec2 (status, est. energy cost, min signal, waiting, sent,
   failed); current transmission panel (packet, mode, size, progress %, signal, ETA) with animated progress;
   **SSTV downlink viewer**: source image + downlink canvas revealing the image line-by-line top→bottom as
   TRANSMISSION_PROGRESS arrives, with subtle scanline and noise when signal is poor; on failure keep the partial
   image and show INTERRUPTED; on completion the full image. Button to request an SSTV downlink.
   (Docs: "This is a visual simulation of progressive SSTV downlink behavior, not an RF SSTV encoder.")
6. **Incident Simulator** — professional operator panel with buttons: BATTERY DRAIN, THERMAL SPIKE, SIGNAL LOSS,
   COMMUNICATION FAILURE, CORRUPTED PACKET, PACKET BURST, FORCE SAFE MODE, RESTORE NOMINAL CONDITIONS; each shows
   what it does; live "autonomous response" panel (state, restricted modes, what the system is doing); incident
   history table (time, type, severity, description, resolved).
7. **Mission Analytics & Replay** — CSV import (filedialog), schema validation report, preview table, start /
   pause / resume / reset, speed 0.5x/1x/2x/5x, replay progress. Analytics for current or any past mission:
   KPI cards (total packets, success rate, avg signal, avg battery, peak temperature, incidents); charts: battery &
   signal vs time, packet outcomes, communication-mode statistics, Seaborn correlation heatmap (+ incident
   distribution). Mission summary (duration, generated/transmitted/failed/deferred/corrupted, success %, avg link,
   avg/min battery, peak temp, avg power, counts by type, safe-mode activations, comm failures, thermal alerts,
   low-power events) with EXPORT TELEMETRY CSV / EXPORT PACKET LOG CSV / EXPORT DECISION LOG CSV / SAVE SUMMARY
   (timestamped files in exports/).
8. **Mission Archive** — SQLite mission list (code, mode LIVE/REPLAY, start time, duration, success %, incidents)
   with search/filter; selecting one shows tabs for telemetry, packets, decisions, incidents (and state transitions).

Tooltips for technical terms: AOS (Acquisition of Signal), LOS (Loss of Signal), TT&C (Telemetry, Tracking &
Command), SSTV (Slow-Scan Television), M17 (open-source digital radio voice/data mode), Codec2 (low-bitrate speech
codec). Reusable status chips (NOMINAL, WARNING, CRITICAL, ACTIVE, QUEUED, TRANSMITTING, DEFERRED, SENT, FAILED).
About dialog (project name, type, technology, academic purpose, disclaimer).

## Demo flow to optimise for (5–8 min)
Launch → cinematic landing → Enter Mission Control (moving satellite, live telemetry, pass countdown, packets,
decision) → Router (score + WHY) → Communications (SSTV image downlinks line by line) → Incidents: THERMAL SPIKE
(state change, modes restricted, queue reprioritised, incident logged) → RESTORE → SIGNAL LOSS / COMM FAILURE
(fail-safe, retry) → Analytics/Replay: import stressful_mission.csv, replay 2x/5x → charts → Archive (SQLite
telemetry, decisions, incidents).

## Code quality
Type hints, docstrings, enums, dataclasses, context managers, logging (logs/somaiyasat.log; no per-frame spam),
no bare except, no giant files, no globals, no duplicated constants, no repeated SQL outside DatabaseManager.
Comment WHY (threading, event queue, scoring, polymorphism, safe mode, replay). Do NOT over-engineer — a
second-year student must be able to explain every file.
