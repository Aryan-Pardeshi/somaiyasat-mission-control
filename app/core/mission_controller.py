"""MissionController — the heart of the simulation and its worker threads.

THREADING MODEL (why and how)
-----------------------------
The simulation must keep running while the Tkinter window stays responsive, so
the work is split across a few background threads (all ``daemon=True``):

    TelemetryWorker     1 Hz   simulate battery / thermal / signal (LIVE mode)
    ReplayWorker        rows   feed telemetry rows from a CSV instead (REPLAY mode)
    HealthMonitorWorker 2 Hz   run the state machine (NOMINAL, LOW_POWER, SAFE_MODE ...)
    RouterWorker        2 Hz   generate packets + run the autonomous router
    TransmissionWorker  10 Hz  advance the active transmission (progress, failures)

Rules that keep this correct:
1. Shared objects (satellite, queue, comms, state machine) are only touched
   while holding ``self._lock`` (a re-entrant lock), so two threads never
   modify them at the same time.
2. Worker threads NEVER touch Tkinter widgets (Tkinter is not thread-safe).
   They only ``bus.publish(...)`` plain dictionaries into a ``queue.Queue``;
   the GUI drains that queue on its own thread with ``root.after()``.
3. Every worker loops with ``while not stop_event.wait(interval)`` so that
   ``stop_mission()`` can set one ``threading.Event`` and every thread exits
   within one tick; the threads are then joined (graceful shutdown).
4. Each loop body is wrapped in try/except so one bad iteration is logged and
   the worker keeps running instead of silently dying.
"""

from __future__ import annotations
from collections import deque
import logging
import threading
import time
import numpy as np
from app import config
from app.core.communication_system import CommunicationSystem
from app.core.event_bus import EventBus, EventType
from app.core.ground_pass import GroundPass, ReplayGroundPass, PassInfo
from app.core.health_monitor import HealthMonitor
from app.core.incident_manager import IncidentManager
from app.core.packet_queue import PacketQueue
from app.core.replay_engine import ReplayEngine
from app.core.router import AutonomousRouter, RouterContext, SafetyRules
from app.core.simulator import TelemetrySimulator
from app.database.database_manager import DatabaseManager
from app.exceptions import CommunicationFailureError, DatabaseOperationError, TelemetryCorruptionError
from app.models.enums import (
    IncidentSeverity,
    IncidentType,
    MissionMode,
    MissionState,
    PacketPriority,
    PacketStatus,
    PacketType,
)
from app.models.mission_state import StateMachine
from app.models.packet import DataPacket, create_packet
from app.models.satellite import Satellite
from app.models.telemetry import TelemetrySnapshot
from app.utils.helpers import format_met, now_iso

logger = logging.getLogger(__name__)


class MissionController:
    """Owns mission state and daemon workers; publishes plain events for Tk."""

    def __init__(self, db: DatabaseManager, bus: EventBus, rng_seed: int | None = None):
        self.db, self.bus = db, bus
        self.rng = np.random.default_rng(rng_seed)
        self._lock = threading.RLock()
        self._mission_stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._active = False
        self._mode: MissionMode | None = None
        self._mission_id: int | None = None
        self._mission_code = ""
        self._start_monotonic = 0.0
        self._ended_time = 0.0
        self._orbit_offset = 0.0
        self._replay_row_time = 0.0
        self._replay_row_wall = 0.0
        self._replay_pause_time = 0.0
        self._last_snapshot: TelemetrySnapshot | None = None
        self._last_pass: PassInfo | None = None
        self._last_phase = None
        self._last_generation = 0.0
        self._last_db_error = False
        self._next_packet_id = 100
        self._forced_safe = False
        self._signal_loss_until = -1.0
        self._drain_steps = 0
        self._heat_steps: deque[float] = deque(maxlen=len(config.THERMAL_SPIKE_STEPS))
        self._counters = {
            key: 0
            for key in (
                "generated",
                "sent",
                "failed",
                "deferred",
                "dropped",
                "corrupted",
                "decisions",
                "incidents",
                "retries",
            )
        }
        self.satellite = Satellite()
        self.ground_pass: GroundPass = GroundPass()
        self.queue = PacketQueue()
        self.comms = CommunicationSystem()
        self.state_machine = StateMachine()
        self.health = HealthMonitor(self.state_machine)
        self.incidents = IncidentManager(db)
        self._router = AutonomousRouter(self.comms.modes)
        self._simulator = TelemetrySimulator(self.satellite, self.ground_pass, self.rng)
        self._replay = ReplayEngine()

    @property
    def mission_active(self) -> bool:
        """Whether a mission currently owns workers."""
        with self._lock:
            return self._active

    @property
    def mode(self) -> MissionMode | None:
        """Current live or replay mode."""
        with self._lock:
            return self._mode

    @property
    def mission_id(self) -> int | None:
        """Current SQLite mission ID."""
        with self._lock:
            return self._mission_id

    @property
    def mission_code(self) -> str:
        """Current human-readable mission code."""
        with self._lock:
            return self._mission_code

    @property
    def paused(self) -> bool:
        """Replay pause state."""
        return self._mode is MissionMode.REPLAY and self._replay.paused

    @property
    def replay(self) -> ReplayEngine:
        """CSV replay engine owned by this controller."""
        return self._replay

    @property
    def state(self) -> MissionState:
        """Current health state."""
        with self._lock:
            return self.state_machine.state

    @property
    def counters(self) -> dict:
        """Copy of mission activity counters."""
        with self._lock:
            return dict(self._counters)

    def mission_time(self) -> float:
        """Return monotonic live MET or capped extrapolated replay MET."""
        with self._lock:
            if not self._active:
                return self._ended_time
            if self._mode is MissionMode.LIVE:
                return max(0.0, time.monotonic() - self._start_monotonic)
            if self._replay.paused:
                return self._replay_pause_time
            return self._replay_row_time + min(
                1.0, max(0.0, time.monotonic() - self._replay_row_wall) * self._replay.speed
            )

    def met_string(self) -> str:
        """Display current mission elapsed time."""
        return format_met(self.mission_time())

    def orbit_angle_now(self) -> float:
        """Smooth orbit angle for an animated view."""
        with self._lock:
            orbit_time = self.mission_time() + (self._orbit_offset if self._mode is MissionMode.LIVE else 0.0)
            return self.ground_pass.info(orbit_time).orbit_angle

    def latest_snapshot(self) -> dict | None:
        """Return the most recent validated frame as plain data."""
        with self._lock:
            return self._last_snapshot.to_dict() if self._last_snapshot else None

    def pass_info(self) -> dict | None:
        """Return current visibility as plain data."""
        with self._lock:
            return self._last_pass.to_dict() if self._last_pass else None

    def _log(self, severity: str, message: str) -> None:
        self.bus.publish(EventType.LOG, severity=severity, message=message, met=self.met_string())

    def _db(self, method: str, *args):
        """Keep workers running after one database failure; warn once per outage."""
        try:
            result = getattr(self.db, method)(*args)
            self._last_db_error = False
            return result
        except DatabaseOperationError:
            logger.exception("Database %s failed", method)
            if not self._last_db_error:
                self._last_db_error = True
                self._log("CRITICAL", "Database unavailable; mission continues in memory")
            return None

    def _reset_models(self) -> None:
        self.satellite.reset()
        self.queue.clear()
        self.comms.reset()
        self.state_machine.reset()
        self.health = HealthMonitor(self.state_machine)
        self.incidents.clear()
        self._router = AutonomousRouter(self.comms.modes)
        self._last_snapshot = self._last_pass = self._last_phase = None
        self._forced_safe = False
        self._signal_loss_until = -1.0
        self._drain_steps = 0
        self._heat_steps.clear()
        self._orbit_offset = 0.0
        self._last_generation = 0.0
        self._last_db_error = False
        self._counters = {key: 0 for key in self._counters}

    def _start(self, mode: MissionMode, name: str) -> None:
        if self.mission_active:
            self.stop_mission("ABORTED")
        with self._lock:
            self._reset_models()
            self._ended_time = 0.0
            self._mode = mode
            self._mission_stop = threading.Event()
            self._start_monotonic = time.monotonic()
            self._replay_row_wall = self._start_monotonic
            self._replay_row_time = 0.0
            self._mission_id, self._mission_code = self.db.start_mission(mode.value, name)
            self._next_packet_id = self.db.next_packet_id()
            self._active = True
            self.bus.publish(
                EventType.MISSION_STARTED,
                mission_id=self._mission_id,
                mission_code=self._mission_code,
                mode=mode.value,
                name=name,
            )
            self._log("SYSTEM", f"{mode.value.title()} mission started: {self._mission_code}")

    def _launch(self, name: str, target) -> None:
        thread = threading.Thread(name=name, target=target, daemon=True)
        self._threads.append(thread)
        thread.start()

    def start_live_mission(self) -> None:
        """Reset state, seed five packets, and start four daemon workers."""
        self._start(MissionMode.LIVE, "Live Mission")
        with self._lock:
            self.ground_pass = GroundPass()
            self._simulator = TelemetrySimulator(self.satellite, self.ground_pass, self.rng)
            for kind, priority, size in (
                (PacketType.HOUSEKEEPING, PacketPriority.HIGH, 4),
                (PacketType.TTC, PacketPriority.CRITICAL, 3),
                (PacketType.SSTV, PacketPriority.MEDIUM, 260),
                (PacketType.M17, PacketPriority.LOW, 45),
                (PacketType.CODEC2, PacketPriority.MEDIUM, 30),
            ):
                self._add_packet(kind, priority, size)
        self._launch("TelemetryWorker", self._telemetry_worker)
        self._launch("HealthMonitorWorker", self._health_worker)
        self._launch("RouterWorker", self._router_worker)
        self._launch("TransmissionWorker", self._transmission_worker)

    def start_replay_mission(self) -> None:
        """Start CSV-driven mission and replay, health, router, radio workers."""
        if self._replay.dataframe is None:
            raise ValueError("Load a replay CSV first")
        self._replay.reset()
        self._start(MissionMode.REPLAY, self._replay.source_name)
        with self._lock:
            self.ground_pass = ReplayGroundPass(self._replay.report.pass_windows)
        self._launch("HealthMonitorWorker", self._health_worker)
        self._launch("RouterWorker", self._router_worker)
        self._launch("TransmissionWorker", self._transmission_worker)
        self._launch("ReplayWorker", self._replay_worker)

    def stop_mission(self, status: str = "COMPLETED") -> None:
        """Stop workers, persist queued packets, and publish final status."""
        with self._lock:
            if not self._active:
                return
            self._mission_stop.set()
            threads = list(self._threads)
        # Joining outside the state lock lets other workers finish their last cycle.
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(config.THREAD_JOIN_TIMEOUT)
        with self._lock:
            if not self._active:
                return
            for packet in self.queue.snapshot():
                self._db("upsert_packet", self._mission_id, packet)
            self._db("end_mission", self._mission_id, status)
            self._ended_time = self.mission_time()
            self._active = False
            self.bus.publish(
                EventType.MISSION_ENDED,
                mission_id=self._mission_id,
                mission_code=self._mission_code,
                mode=self._mode.value,
                status=status,
            )
            self._log("SYSTEM", f"Mission ended: {status}")
            self._threads = []

    def shutdown(self) -> None:
        """Abort an active mission; safe to call repeatedly."""
        if self.mission_active:
            self.stop_mission("ABORTED")

    def pause_replay(self) -> None:
        """Freeze replay clock and CSV pacing."""
        with self._lock:
            if self._mode is MissionMode.REPLAY:
                self._replay_pause_time = self.mission_time()
                self._replay.pause()

    def resume_replay(self) -> None:
        """Continue replay from the paused row time."""
        with self._lock:
            if self._mode is MissionMode.REPLAY and self._replay.paused:
                self._replay_row_time = self._replay_pause_time
                self._replay_row_wall = time.monotonic()
                self._replay.resume()

    def set_replay_speed(self, speed: float) -> None:
        """Set supported replay speed while preserving current MET."""
        with self._lock:
            current = self.mission_time() if self._active else 0.0
            self._replay.set_speed(speed)
            if self._active and self._mode is MissionMode.REPLAY:
                self._replay_row_time, self._replay_row_wall = current, time.monotonic()

    def reset_replay(self) -> None:
        """End current replay and rewind its CSV cursor."""
        if self.mission_active:
            self.stop_mission("RESET")
        self._replay.reset()

    def _add_packet(self, kind: PacketType | str, priority: PacketPriority | str, size: float) -> DataPacket:
        packet = create_packet(kind, self._next_packet_id, priority, size, self.mission_time())
        self._next_packet_id += 1
        evicted = self.queue.add(packet)
        self._counters["generated"] += 1
        if evicted:
            self._counters["dropped"] += 1
            self._db("upsert_packet", self._mission_id, evicted)
        if evicted is not packet:
            self._db("upsert_packet", self._mission_id, packet)
            self.bus.publish(EventType.PACKET_ADDED, packet=packet.to_record(self.mission_time()))
        return packet

    def _random_packet(self) -> DataPacket:
        kinds = list(config.PACKET_TYPE_WEIGHTS)
        kind = str(self.rng.choice(kinds, p=list(config.PACKET_TYPE_WEIGHTS.values())))
        priorities = config.PACKET_PRIORITY_WEIGHTS[kind]
        priority = str(self.rng.choice(list(priorities), p=list(priorities.values())))
        low, high = config.PACKET_SIZE_RANGES_KB[kind]
        size = round(float(self.rng.uniform(low, high)), 1)
        return self._add_packet(kind, priority, size)

    def request_sstv_downlink(self) -> int:
        """Enqueue a high-priority image for operator downlink."""
        with self._lock:
            if not self._active:
                raise RuntimeError("Start a mission first")
            low, high = config.PACKET_SIZE_RANGES_KB["SSTV"]
            return self._add_packet(
                PacketType.SSTV, PacketPriority.HIGH, round(float(self.rng.uniform(low, high)), 1)
            ).packet_id

    def skip_to_next_pass(self) -> float:
        """Advance live orbit clock to three seconds before the next AOS."""
        with self._lock:
            if not self._active or self._mode is not MissionMode.LIVE:
                return 0.0
            orbit_now = self.mission_time() + self._orbit_offset
            seconds = self.ground_pass.next_aos_offset(orbit_now)
            advance = max(0.0, seconds - 3.0)
            self._orbit_offset += advance
            self._log("SYSTEM", f"Orbit advanced {advance:.1f} s toward next ground pass")
            return advance

    def _record_incident(
        self, kind: IncidentType, severity: IncidentSeverity, description: str, resolved: bool = False
    ) -> None:
        incident = self.incidents.record(
            self._mission_id, kind, severity, description, self.mission_time(), resolved
        )
        if self.incidents.db_failed and not self._last_db_error:
            self._last_db_error = True
            self._log("CRITICAL", "Database unavailable; mission continues in memory")
        self._counters["incidents"] += 1
        self.bus.publish(EventType.INCIDENT_CREATED, incident=incident.to_dict())

    def _resolve_incidents(self, kind: IncidentType) -> None:
        for incident in self.incidents.resolve_open(self._mission_id, kind):
            self.bus.publish(
                EventType.INCIDENT_RESOLVED, incident_id=incident.incident_id, incident_type=kind.value
            )
        if self.incidents.db_failed and not self._last_db_error:
            self._last_db_error = True
            self._log("CRITICAL", "Database unavailable; mission continues in memory")

    def inject_incident(self, incident_type: IncidentType) -> str:
        """Apply an operator fault and archive the action."""
        with self._lock:
            if not self._active:
                return "Start a mission before injecting an incident"
            kind = IncidentType(incident_type)
            now = self.mission_time()
            message = f"{kind.label} injected"
            severity = IncidentSeverity.WARNING
            if (
                kind in (IncidentType.BATTERY_DRAIN, IncidentType.THERMAL_SPIKE)
                and self._mode is MissionMode.REPLAY
            ):
                message = f"{kind.label} ignored: replay telemetry is CSV-driven"
            elif kind is IncidentType.BATTERY_DRAIN:
                self._drain_steps = config.BATTERY_DRAIN_STEPS
            elif kind is IncidentType.THERMAL_SPIKE:
                self._heat_steps.extend(config.THERMAL_SPIKE_STEPS)
            elif kind is IncidentType.SIGNAL_LOSS:
                self._signal_loss_until = now + config.SIGNAL_LOSS_DURATION
            elif kind is IncidentType.COMM_FAILURE:
                self.comms.trigger_link_failure(now, config.COMM_FAILURE_DURATION)
                severity = IncidentSeverity.CRITICAL
            elif kind is IncidentType.CORRUPTED_PACKET:
                packets = self.queue.snapshot()
                target = next(
                    (p for p in packets if p.status in (PacketStatus.QUEUED, PacketStatus.DEFERRED)), None
                )
                if target is None:
                    target = self._add_packet(PacketType.HOUSEKEEPING, PacketPriority.HIGH, 4)
                target.corrupt()
                severity = IncidentSeverity.CRITICAL
            elif kind is IncidentType.PACKET_BURST:
                for _ in range(config.PACKET_BURST_SIZE):
                    self._random_packet()
                message = f"Packet burst: {config.PACKET_BURST_SIZE} packets queued"
            elif kind is IncidentType.FORCE_SAFE_MODE:
                self._forced_safe = True
                severity = IncidentSeverity.CRITICAL
            elif kind is IncidentType.RESTORE_NOMINAL:
                self._forced_safe = False
                self._signal_loss_until = -1.0
                self._drain_steps = 0
                self._heat_steps.clear()
                self.comms._link_down_until = -1.0
                if self._mode is MissionMode.LIVE:
                    self.satellite.reset()
                for past in (
                    IncidentType.BATTERY_DRAIN,
                    IncidentType.THERMAL_SPIKE,
                    IncidentType.SIGNAL_LOSS,
                    IncidentType.COMM_FAILURE,
                    IncidentType.FORCE_SAFE_MODE,
                    IncidentType.LOW_POWER,
                    IncidentType.THERMAL_ALERT,
                    IncidentType.SAFE_MODE,
                ):
                    self._resolve_incidents(past)
                severity = IncidentSeverity.INFO
                message = "Nominal conditions restored"
            self._record_incident(kind, severity, message)
            self._log(
                (
                    "CRITICAL"
                    if severity is IncidentSeverity.CRITICAL
                    else "WARNING" if severity is IncidentSeverity.WARNING else "INFO"
                ),
                message,
            )
            return message

    def _quarantine(self, packet: DataPacket) -> None:
        self.queue.remove(packet.packet_id)
        packet.status = PacketStatus.DROPPED
        packet.corrupted = True
        self._counters["corrupted"] += 1
        self._counters["dropped"] += 1
        self._db("upsert_packet", self._mission_id, packet)
        self._record_incident(
            IncidentType.CORRUPTED_PACKET,
            IncidentSeverity.CRITICAL,
            f"Packet #{packet.packet_id} failed CRC and was quarantined",
            True,
        )
        self._log("CRITICAL", f"{packet.label} quarantined after CRC mismatch")

    def _ingest_snapshot(self, snapshot: TelemetrySnapshot, info: PassInfo) -> None:
        try:
            snapshot.validate()
        except TelemetryCorruptionError as exc:
            self._record_incident(IncidentType.TELEMETRY_CORRUPTION, IncidentSeverity.WARNING, str(exc), True)
            self._log("WARNING", f"Corrupted telemetry discarded: {exc}")
            return
        self._last_snapshot, self._last_pass = snapshot, info
        self._db("insert_telemetry", self._mission_id, snapshot)
        if self._last_phase is not None and info.phase is not self._last_phase:
            self.bus.publish(
                EventType.GROUND_PASS_CHANGED,
                old=self._last_phase.value,
                new=info.phase.value,
                **{"pass": info.to_dict()},
            )
            if info.phase.value == "AOS":
                self._log("SYSTEM", "Ground pass acquired — AOS")
            elif info.phase.value == "LOS":
                self._log("SYSTEM", "Loss of signal — LOS")
        self._last_phase = info.phase
        self.bus.publish(
            EventType.TELEMETRY_UPDATE,
            snapshot=snapshot.to_dict(),
            **{"pass": info.to_dict()},
            met=format_met(snapshot.mission_time),
            counters=self.counters,
        )

    def _telemetry_worker(self) -> None:
        """Thread 1 (LIVE): simulate one telemetry frame per second."""
        last = time.monotonic()
        while not self._mission_stop.wait(config.TELEMETRY_INTERVAL):
            try:
                with self._lock:
                    wall = time.monotonic()
                    dt, last = wall - last, wall
                    now = self.mission_time()
                    if self._drain_steps:
                        remaining = max(0.0, self.satellite.power.battery_level - config.BATTERY_DRAIN_TARGET)
                        self.satellite.power.drain(remaining / self._drain_steps)
                        self._drain_steps -= 1
                    if self._heat_steps:
                        self.satellite.thermal.inject_heat(self._heat_steps.popleft())
                    attenuation = config.SIGNAL_LOSS_ATTENUATION if now < self._signal_loss_until else 1.0
                    active_mode = self.comms.active.mode if self.comms.active else None
                    comm_state = (
                        "LINK DOWN" if self.comms.link_down(now) else "TRANSMITTING" if active_mode else ""
                    )
                    snapshot, info = self._simulator.step(
                        now,
                        now + self._orbit_offset,
                        dt,
                        active_mode,
                        self.state_machine.state,
                        attenuation,
                        len(self.queue),
                        comm_state,
                    )
                    self._ingest_snapshot(snapshot, info)
            except Exception:
                logger.exception("Telemetry worker iteration failed")

    def _health_worker(self) -> None:
        """Thread 2: evaluate the state machine and react to state changes."""
        while not self._mission_stop.wait(config.HEALTH_CHECK_INTERVAL):
            try:
                with self._lock:
                    snapshot = self._last_snapshot
                    if snapshot is None:
                        continue
                    now = self.mission_time()
                    transition, alerts = self.health.check(
                        snapshot, self.comms.link_down(now), self._forced_safe
                    )
                    for severity, message in alerts:
                        self._log(severity, message)
                    if transition:
                        old, new, reason = transition
                        self.bus.publish(EventType.STATE_CHANGED, old=old.value, new=new.value, reason=reason)
                        self._db("insert_state_transition", self._mission_id, old, new, reason, now)
                        self._log("SYSTEM", f"State → {new.value}: {reason}")
                        if (
                            old is MissionState.COMMUNICATION_LOSS
                            and new is not MissionState.COMMUNICATION_LOSS
                        ):
                            self._resolve_incidents(IncidentType.COMM_FAILURE)
                            self._log("INFO", "RF link recovered")
                        automatic = {
                            MissionState.LOW_POWER: (IncidentType.LOW_POWER, IncidentSeverity.WARNING),
                            MissionState.THERMAL_ALERT: (
                                IncidentType.THERMAL_ALERT,
                                IncidentSeverity.WARNING,
                            ),
                            MissionState.SAFE_MODE: (IncidentType.SAFE_MODE, IncidentSeverity.CRITICAL),
                        }
                        if old in automatic:
                            self._resolve_incidents(automatic[old][0])
                        if new in automatic:
                            kind, severity = automatic[new]
                            self._record_incident(kind, severity, reason)
                        tx = self.comms.active
                        if tx and (
                            tx.mode.mode_type.value not in config.STATE_ALLOWED_MODES[new.value]
                            or new is MissionState.SAFE_MODE
                            and tx.packet.priority is not PacketPriority.CRITICAL
                        ):
                            self.comms.abort()
                            tx.packet.status = PacketStatus.DEFERRED
                            tx.packet.hold_reason = f"{tx.mode.display_name} suspended in {new.label}"
                            self._counters["deferred"] += 1
                            self._db("upsert_packet", self._mission_id, tx.packet)
                            self._log("ROUTER", f"{tx.packet.label} suspended — {new.value}")
            except Exception:
                logger.exception("Health worker iteration failed")

    def _router_worker(self) -> None:
        """Thread 3: generate packets (LIVE) and run the autonomous router."""
        while not self._mission_stop.wait(config.ROUTER_INTERVAL):
            try:
                with self._lock:
                    if self._mode is MissionMode.REPLAY and self._replay.paused:
                        continue
                    now = self.mission_time()
                    if (
                        self._mode is MissionMode.LIVE
                        and now - self._last_generation >= config.PACKET_GENERATION_INTERVAL
                    ):
                        self._last_generation = now
                        if self.rng.random() < config.PACKET_GENERATION_PROBABILITY:
                            self._random_packet()
                    snapshot, info = self._last_snapshot, self._last_pass
                    if snapshot is None or info is None:
                        continue
                    ctx = RouterContext(
                        snapshot.battery,
                        snapshot.temperature,
                        snapshot.signal,
                        self.state_machine.state,
                        info.in_pass,
                        info.seconds_to_los,
                        not self.comms.link_down(now),
                        now,
                    )
                    result = self._router.evaluate(self.queue.snapshot(), ctx)
                    for packet in result.quarantined:
                        self._quarantine(packet)
                    for packet in result.newly_deferred:
                        self._counters["deferred"] += 1
                        self._db("upsert_packet", self._mission_id, packet)
                        self._log("ROUTER", f"{packet.label} deferred — {packet.hold_reason}")
                    if self.comms.active is None and result.decision:
                        decision = result.decision
                        packet = self.queue.get(decision.packet_id)
                        if packet:
                            packet.status = PacketStatus.SELECTED
                            packet.selected_at = now
                            self._db("insert_decision", self._mission_id, decision)
                            self._counters["decisions"] += 1
                            self.bus.publish(EventType.PACKET_SELECTED, decision=decision.to_dict())
                            tx = self.comms.begin(packet, now, ctx.signal)
                            self._db("upsert_packet", self._mission_id, packet)
                            self.bus.publish(
                                EventType.TRANSMISSION_STARTED,
                                packet=packet.to_record(now),
                                mode=tx.mode.mode_type.value,
                                estimated_time=tx.estimated_time,
                            )
                            self._log("ROUTER", f"Selected {packet.label}: score {decision.total_score:.1f}")
                    records = [
                        p.to_record(now)
                        for p in sorted(self.queue.snapshot(), key=lambda p: p.score, reverse=True)
                    ]
                    self.bus.publish(
                        EventType.QUEUE_UPDATE,
                        packets=records,
                        hold_reason=result.hold_reason,
                        active_rules=result.active_rules,
                        transmitting_id=self.comms.active.packet.packet_id if self.comms.active else None,
                    )
            except Exception:
                logger.exception("Router worker iteration failed")

    def _transmission_worker(self) -> None:
        """Thread 4: advance the active transmission; apply the retry policy on failure."""
        while not self._mission_stop.wait(config.TRANSMISSION_TICK):
            try:
                with self._lock:
                    tx = self.comms.active
                    if tx is None:
                        continue
                    scale = (
                        self._replay.speed
                        if self._mode is MissionMode.REPLAY and not self._replay.paused
                        else 0.0 if self._mode is MissionMode.REPLAY else 1.0
                    )
                    if scale == 0:
                        continue
                    now = self.mission_time()
                    signal = self._last_snapshot.signal if self._last_snapshot else 0.0
                    try:
                        tx = self.comms.step(config.TRANSMISSION_TICK * scale, signal, now)
                    except CommunicationFailureError as exc:
                        tx = self.comms.fail(str(exc))
                        packet = tx.packet
                        packet.retry_count += 1
                        self._counters["failed"] += 1
                        # Bounded retry policy: requeue until max_retries, then give up (FAILED).
                        # CRITICAL packets get more retries (config.MAX_RETRIES_CRITICAL).
                        requeued = packet.retry_count <= packet.max_retries
                        if requeued:
                            packet.status = PacketStatus.QUEUED
                            self._counters["retries"] += 1
                        else:
                            packet.status = PacketStatus.FAILED
                            self.queue.remove(packet.packet_id)
                        self._db("upsert_packet", self._mission_id, packet)
                        self.bus.publish(
                            EventType.TRANSMISSION_FAILED,
                            packet=packet.to_record(now),
                            mode=tx.mode.mode_type.value,
                            progress=tx.progress,
                            reason=str(exc),
                            requeued=requeued,
                        )
                        self._log("CRITICAL", f"{packet.label} transmission failed: {exc}")
                        continue
                    except TelemetryCorruptionError:
                        self.comms.abort()
                        self._quarantine(tx.packet)
                        continue
                    noise = getattr(tx.mode, "last_noise_level", 0.0)
                    eta = max(0.0, (tx.total_kb - tx.sent_kb) / max(tx.mode.data_rate, 1e-9))
                    self.bus.publish(
                        EventType.TRANSMISSION_PROGRESS,
                        packet_id=tx.packet.packet_id,
                        mode=tx.mode.mode_type.value,
                        progress=tx.progress,
                        sent_kb=tx.sent_kb,
                        total_kb=tx.total_kb,
                        signal=signal,
                        eta=eta,
                        noise=noise,
                    )
                    if tx.done:
                        tx = self.comms.complete()
                        packet = tx.packet
                        packet.transmitted_at = now
                        self.queue.remove(packet.packet_id)
                        self._counters["sent"] += 1
                        self._db("upsert_packet", self._mission_id, packet)
                        self.bus.publish(
                            EventType.TRANSMISSION_COMPLETE,
                            packet=packet.to_record(now),
                            mode=tx.mode.mode_type.value,
                            duration=now - tx.started_at,
                        )
                        self._log(
                            "INFO",
                            f"{packet.label} transmitted ({packet.size_kb:g} KB, {now - tx.started_at:.1f} s)",
                        )
            except Exception:
                logger.exception("Transmission worker iteration failed")

    def _replay_row(self, row: dict) -> None:
        with self._lock:
            now = float(row["t"])
            self._replay_row_time, self._replay_row_wall = now, time.monotonic()
            info = self.ground_pass.info(now)
            signal = float(row["signal"]) * (
                config.SIGNAL_LOSS_ATTENUATION if now < self._signal_loss_until else 1.0
            )
            battery = float(row["battery"])
            voltage = (
                config.BATTERY_VOLTAGE_EMPTY
                + (config.BATTERY_VOLTAGE_FULL - config.BATTERY_VOLTAGE_EMPTY) * battery / 100
            )
            snapshot = TelemetrySnapshot(
                now,
                battery,
                voltage,
                float(row["temp"]),
                signal,
                float(row["power_draw"]),
                float(row["packet_loss"]),
                len(self.queue),
                self.state_machine.state.value,
                "LINK DOWN" if self.comms.link_down(now) else "LINK READY" if info.in_pass else "NO PASS",
                info.phase.value,
                info.in_pass,
                info.sunlit,
                now_iso(),
            )
            self._ingest_snapshot(snapshot, info)
            if row.get("packet_type"):
                self._add_packet(row["packet_type"], row["priority"], float(row["size_kb"]))
            if row.get("event"):
                self.inject_incident(IncidentType(row["event"]))

    def _replay_worker(self) -> None:
        """Thread 5 (REPLAY): feed CSV rows through the same pipeline as live telemetry."""
        try:
            self._replay.run(
                self._mission_stop,
                self._replay_row,
                lambda progress: self.bus.publish(EventType.REPLAY_PROGRESS, **progress),
            )
            if not self._mission_stop.is_set():
                # The replay worker finalises directly; stop_mission skips joining itself.
                self.stop_mission("COMPLETED")
        except Exception:
            logger.exception("Replay worker failed")
            self.stop_mission("FAILED")
