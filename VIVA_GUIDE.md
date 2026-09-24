# Viva Guide: SomaiyaSat Mission Control

Short, correct answers to study, with the file to open when the examiner says "show me".

---

## Learn these 10 first

1. **What is the project?** (Q1)
2. **Why is it "AI" without ML?** (Q2)
3. **How does the routing score work?** (Q29)
4. **Show inheritance and polymorphism.** (Q6, Q7, Q38)
5. **What is an abstract class, and why ABC?** (Q8, Q9)
6. **Why threads, and why can't they touch Tkinter?** (Q17, Q19, Q20)
7. **Explain the database tables.** (Q35)
8. **What happens during a thermal emergency / safe mode?** (Q32, Q33)
9. **How is CSV replay implemented?** (Q43)
10. **How do you prevent starvation?** (Q44)

## 30-second pitch

> "SomaiyaSat Mission Control is a desktop digital twin of a PocketQube satellite mission. It simulates
> telemetry and ground-station passes, and an autonomous router decides which data packet to send, when,
> and through which radio mode (TT&C, SSTV, M17 or Codec2). The router first applies safety rules and then
> a transparent weighted score, and it explains every decision. Operators can inject faults, replay
> missions from CSV and analyse everything stored in SQLite. It uses OOP, Tkinter, SQLite,
> multithreading, Pandas, NumPy, Matplotlib and Seaborn."

---

## A. Project and concept

**1. What is the project?**
A Tkinter desktop simulator (digital twin) of the SomaiyaSat satellite mission. It generates telemetry,
simulates ground passes, queues packets and makes autonomous, explainable transmission decisions. It also
handles injected failures, replays CSV missions and stores and analyses everything in SQLite.

**2. Why is this an AI use case if no ML model is used?**
AI here means *autonomous intelligent decision-making*. The system senses its environment (battery,
temperature, signal, pass), reasons with rules and a utility score, and acts (it transmits, defers or
enters safe mode) without a human. It is a rule-based + utility-based agent, which is classic AI. ML
is deliberately avoided: a satellite needs predictable, explainable and cheap decisions, and we have no
training data.

**3. What is a digital twin?**
A software model that behaves like a real system, so you can monitor it, test "what-if" scenarios and
rehearse failures without touching the hardware. Ours mirrors the satellite's power, thermal, radio and
pass behaviour.

## B. OOP

**4. Where have you used classes?**
Everywhere. `Satellite`, `PowerSystem`, `ThermalSystem`, `DataPacket` and its subclasses,
`CommunicationMode` and its subclasses, `PacketQueue`, `AutonomousRouter`, `StateMachine`, `GroundPass`,
`MissionController`, `DatabaseManager`, `AnalyticsEngine`, and all the GUI pages and widgets.

**5. What is encapsulation?**
Bundling data with the methods that act on it, and hiding the internal state. In `PowerSystem` the
battery is `self.__battery` (a private, name-mangled attribute). Other code must call
`consume_power()`, `recharge()` or `drain()`, which always keep it between 0 and 100 %. That is data
hiding. → `app/models/satellite.py`

**6. Show inheritance.**
`class TTCPacket(DataPacket)`, `SSTVPacket(DataPacket)`, and `M17Packet(VoicePacket)`, which itself
extends `DataPacket` → `app/models/packet.py`. Also `TTCMode(DigitalLinkMode)` →
`DigitalLinkMode(CommunicationMode)`, and every GUI page extends `BasePage`.

**7. Show polymorphism.**
`CommunicationSystem.step()` calls `mode.transmit(packet, signal, dt)` without knowing the mode's class:

* TT&C is robust at low signal;
* M17 has a sharp S-shaped curve;
* Codec2 degrades gently;
* SSTV sends whole scan lines at a fixed speed and turns weak signal into picture noise.

The same call gives different behaviour. → `app/models/communication_modes.py`

**8. What is an abstract class?**
A class that cannot be instantiated and exists to define a common interface. It has abstract methods
that subclasses *must* implement. `CommunicationMode(ABC)` declares `minimum_signal_required`,
`estimate_transmission_time` and `transmit` with `@abstractmethod`. Calling `CommunicationMode()` raises
`TypeError`, and a test checks this.

**9. Why ABC?**
It enforces the contract: any new radio mode *must* implement those methods, or Python refuses to
create it. The router can therefore rely on every mode having the same interface.

**10. Difference between class and object?**
A class is the blueprint (`DataPacket`). An object is one instance created from it, such as packet #104
with its own ID, size and status. One class, many objects.

**37. Inheritance vs composition?**
Inheritance is an "is-a" relation: an `SSTVMode` *is a* `CommunicationMode`. Composition is a "has-a"
relation: a `Satellite` *has a* `PowerSystem` and *has a* `ThermalSystem`, and `MissionController`
*has a* router, a queue and a database. We use each where it fits the real world.

**38. How is polymorphism used? (more examples)**
Each GUI page overrides `on_show()`, `on_hide()` and `handle_event()`, and the app loops over all
pages calling `page.handle_event(event)`. `SSTVMode` overrides `calculate_energy_cost()` and calls
`super()` to reuse the parent formula (method overriding).

**41. Why use an enum?**
It gives a fixed set of named values (`MissionState.SAFE_MODE`, `PacketPriority.CRITICAL`) instead of
raw strings, so typos become errors, the code is readable and comparisons are safe. Ours inherit from
`str`, so they store easily in SQLite.

**42. What is a dataclass?**
The `@dataclass` decorator auto-generates `__init__`, `__repr__` and `__eq__` for classes that mainly
hold data: `TelemetrySnapshot`, `RoutingDecision`, `ScoreBreakdown`, `Incident` and `PassInfo`.

## C. Libraries and database

**11. Why SQLite?**
It is built into Python (`sqlite3`), serverless, stores everything in one file, supports SQL with
transactions, and is perfect for a local desktop app. It stores missions, telemetry, packets, decisions
and incidents permanently for the archive and analytics.

**12. Why Pandas?**
To read and validate CSV files, load SQL tables into DataFrames (`read_sql_query`), group and aggregate
(`groupby`, `crosstab`, `value_counts`), and export CSVs, all in a few lines.

**13. Why NumPy?**
Fast numerical arrays: Gaussian noise for the signal and temperature, random packet generation,
mean / std / min / max statistics, the shaded-Earth rendering and the SSTV noise effect.

**14. Why Matplotlib?**
The live telemetry charts and the mission charts, embedded in Tkinter with `FigureCanvasTkAgg`. We
use `Figure` objects rather than pyplot's global state so plotting is safe inside a GUI.

**15. Why Seaborn?**
Statistical plots in one call on top of Matplotlib: the correlation heatmap of battery, temperature,
signal, power and packet loss; mode performance; and the incident distribution.

**35. Explain the database tables.**

* `missions`: one row per mission (code, LIVE/REPLAY, start, end, status).
* The child tables below each link back to `missions` through `mission_id`:

| Table | What one row is |
|---|---|
| `telemetry` | one row per second: battery, temperature, signal, power, packet loss, state |
| `packets` | each packet's type, priority, size, final status, retries, corrupted flag (updated with an UPSERT) |
| `decisions` | every routing decision with its 5 score components, the context and the reason text |
| `incidents` | injected or automatic incidents, with severity and a resolved flag |
| `state_transitions` | every state change with its reason |

**36. Difference between CSV and SQLite?**
CSV is a plain text table: one flat file with no types, no relations and no queries. It is good for
exchange and replay input. SQLite is a real relational database with typed columns, keys, SQL queries,
transactions and multiple related tables. It is good for the permanent archive.

## D. Multithreading and the GUI

**16. What is multithreading?**
Running several threads (independent flows of execution) inside one process concurrently. They share
memory, so access to shared data must be synchronised.

**17. Why are threads used here?**
The telemetry simulation (1 Hz), the health monitor (2 Hz), the router (2 Hz) and the transmission
progress (10 Hz) must all run continuously. If they ran on the GUI thread, the window would freeze.
Five worker threads do the work while the GUI stays smooth. → `app/core/mission_controller.py`

**18. What is `queue.Queue`?**
A thread-safe FIFO queue with its locking built in. Workers `put` events and the GUI `get`s them.
Our `EventBus` wraps one.

**19. Why can worker threads not safely modify Tkinter?**
Tkinter (Tcl/Tk) is single-threaded. Widgets must only be touched by the thread that created them
(the main thread). Updating them from other threads can cause random crashes or corrupted displays.

**20. What does `root.after()` do?**
It schedules a function to run on the Tk main thread after a delay without blocking the event loop.
We call `_poll_events()` every 50 ms, which drains the queue and updates the widgets. It also drives
the animations, such as the orbit at about 30 FPS.

**49. How do you gracefully shut down threads?**
Each worker loops `while not stop_event.wait(interval)`. When the window closes (or a mission ends),
the app:

1. sets the `threading.Event`;
2. joins every thread with a timeout;
3. saves the queued packets and ends the mission in the DB;
4. closes the DB;
5. destroys the window.

No thread is left running; a test checks this.

## E. Exceptions

**21. What is exception handling?**
Catching runtime errors with `try` / `except` so the program can recover or fail gracefully instead of
crashing. For example, a corrupted telemetry frame is discarded and logged while the mission continues.

**22. What is a custom exception?**
Our own exception class that extends `Exception` to describe a domain problem:
`TelemetryCorruptionError`, `CommunicationFailureError`, `InvalidPacketError`,
`DatabaseOperationError` and `ReplayDataError` → `app/exceptions.py`. They make `except` clauses
precise and readable.

## F. Space and radio domain

**23. What is TT&C?** Telemetry, Tracking & Command: the satellite's essential health and control link,
so it gets the highest priority.

**24. What is SSTV?** Slow-Scan Television: a way of sending still images over radio line by line.
Ours is a *visual simulation*, not a real encoder.

**25. What is M17?** An open-source digital radio mode for voice and data used by amateur radio.

**26. What is Codec2?** An open-source low-bitrate speech codec for narrow radio links.

**27. What is AOS?** Acquisition of Signal: the moment the satellite rises above the station's horizon
and contact starts.

**28. What is LOS?** Loss of Signal: the satellite sets and contact ends. The UI counts down to both.

## G. Autonomous logic

**29. How does the routing score work?**
The router works in two layers:

1. **Layer 1, safety rules.** These remove packets that must not be sent: no pass, link down, a mode
   suspended in the current state, weak signal, too much energy, or not enough time before LOS.
2. **Layer 2, the weighted score.** Every remaining packet gets
   `0.35·priority + 0.25·link + 0.15·urgency + 0.15·energy + 0.10·waiting` (each part 0–100). The
   highest score is sent.

All components and the reason are shown in the UI and saved in `decisions`. → `app/core/router.py`

**30. Why is TT&C prioritised?**
Without its health and command link the satellite cannot be controlled or diagnosed. It is small and
cheap to send, so it has the top urgency score (100), and CRITICAL priority adds 35 points.

**31. What happens during low battery?**
Below 25 % the state becomes LOW_POWER. SSTV and M17 are suspended, packets costing more than 12 J are
deferred, and the energy component penalises expensive packets more. Below 15 % the state becomes
SAFE_MODE. It recovers only above 28 % (hysteresis).

**32. What happens during a thermal emergency?**
Above 60 °C the state becomes THERMAL_ALERT: only TT&C mode is allowed, so any active SSTV, M17 or
Codec2 transmission is suspended and requeued as DEFERRED, and an incident is logged. Above 70 °C the
state becomes SAFE_MODE. It recovers below 55 °C.

**33. What is safe mode?**
A minimal survival state. Power draw drops to 0.25 W and only CRITICAL TT&C / housekeeping packets may
be sent. It is triggered by a critical battery (< 15 %), a critical temperature (> 70 °C) or the
operator.

**34. What happens when a packet is corrupted?**
Every packet stores a CRC32 checksum of its payload. The corruption incident flips bytes, so
`verify_integrity()` raises `TelemetryCorruptionError`. The router catches it and quarantines the
packet (status DROPPED, corrupted = 1), and a CRITICAL incident is logged. The packet is never
transmitted.

**44. How do you prevent starvation?**
The waiting component grows with packet age (up to 10 points at 150 s). An old LOW-priority packet
slowly becomes competitive with fresh ones whenever the safety rules allow it, while CRITICAL packets
still dominate. A test proves an older identical packet wins.

**48. What is the time complexity of choosing the best packet?**
O(n): one pass to check the rules and score each packet, then `max()` by score. With at most 40 packets
this is trivial. Re-scoring every cycle is required anyway, because scores change as signal, battery
and age change, which a static heap would not handle.

## H. Functional programming and collections

**39. What are `map()`, `filter()` and `lambda`?**

* `lambda` is a small anonymous function.
* `filter(func, items)` keeps the items for which `func` is true.
* `map(func, items)` applies `func` to every item.

Ours:

* `filter(lambda p: p.status is QUEUED and not p.hold_reason, packets)` picks the eligible packets;
* `max(eligible, key=lambda p: p.score)` picks the best one;
* `dict(map(stats, TELEMETRY_METRICS))` computes NumPy statistics per metric;
* `frame[col].map(normalize_label)` cleans CSV labels.

**40. What is a deque?**
A double-ended queue from `collections`. With `maxlen=180` it keeps only the latest 180 telemetry
points: adding a new point drops the oldest automatically. That is perfect for rolling live charts with
no memory growth.

Other collections used: a **set** `SUPPORTED_MODES = {"TTC", "SSTV", "M17", "CODEC2"}`, **dicts** for
configuration and snapshots, and **lists** for the queue and routes.

## I. Replay

**43. How is CSV replay implemented?**
The replay runs in two steps:

1. **Loading.** `ReplayEngine.load_csv()` uses Pandas to read the file, check the required columns,
   normalise the text, convert numbers (`to_numeric(errors="coerce")`) and validate each row. It
   reports and drops bad rows, and detects the pass windows.
2. **Playing.** A `ReplayWorker` thread feeds each row, paced by its timestamp divided by the speed
   (0.5×–5×), into the **same** controller pipeline as live telemetry: state machine, router,
   transmissions and SQLite. Pause, resume and reset use thread-safe flags.

## J. Limits and learning

**45. What are the project limitations?**
A simplified 2D orbit with compressed time; simulated power, thermal and radio values; no real
protocol encoding; one satellite and one ground station; the GUI is tested manually.

**46. Could this run on a real satellite?**
Not as is. It is an educational simulator, but the *decision logic* (rules + score) is the kind of
lightweight, explainable approach real small-satellite software uses.

**47. What changes would be required for actual flight software?**
The main changes:

* real sensor drivers and radio hardware interfaces;
* real protocol stacks (AX.25 / M17 / Codec2 / SSTV encoders);
* TLE-based pass prediction;
* a real-time OS or microcontroller code (C / MicroPython) with watchdogs and memory limits;
* formal verification and testing;
* fault-tolerant storage;
* flight qualification.

**50. What did you personally learn?**
How to design a system from interfaces first; OOP hierarchies that remove if-else chains; safe
multithreading with queues; building a modern GUI in plain Tkinter; relational database design; data
validation and analysis with Pandas; and making autonomous decisions explainable.

---

## Quick demo script (say while clicking)

1. *Landing:* "System initialisation. Each line really builds part of the interface."
2. *Overview:* "Live telemetry at 1 Hz from a worker thread. Skip to the next pass, and the router
   starts transmitting. Here is WHY it chose this packet."
3. *Router:* "Layer 1 rules, Layer 2 weighted score. These bars are the five components."
4. *Communications:* "Request an SSTV image. It downlinks line by line, and a weak signal adds noise."
5. *Incidents:* "Thermal spike. The state goes to THERMAL ALERT, SSTV and M17 are suspended, and the
   incident is logged. Restore."
6. *Comm failure:* "The transmission fails, the retry policy requeues it, and the link recovers."
7. *Replay:* "stressful_mission.csv at 5×: low power, then safe mode, then recovery."
8. *Analytics and Archive:* "Seaborn heatmap, mission summary, and all of it stored in SQLite."

## Key numbers to remember

| Item | Value |
|---|---|
| Score weights | 0.35 / 0.25 / 0.15 / 0.15 / 0.10 |
| Battery thresholds | LOW_POWER < 25 %, SAFE_MODE < 15 % |
| Temperature thresholds | THERMAL_ALERT > 60 °C, SAFE_MODE > 70 °C |
| Signal minimums | TT&C 15 %, Codec2 30 %, M17 40 %, SSTV 55 %; hold non-critical < 20 % |
| Orbit / pass | 180 s orbit, 60 s pass (compressed simulation) |
| Retries | 2 (CRITICAL: 4) |
| Queue capacity | 40 packets |
| Threads | Telemetry/Replay, Health, Router, Transmission |
| Tests | 62 (`python -m pytest -v`) |
