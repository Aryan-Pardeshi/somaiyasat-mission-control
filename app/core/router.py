"""Explainable autonomous routing: hard safety rules then weighted scores."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import logging
from app import config
from app.exceptions import TelemetryCorruptionError
from app.models.communication_modes import CommunicationMode
from app.models.enums import CommunicationType, MissionState, PacketPriority, PacketStatus
from app.models.packet import DataPacket
from app.utils.helpers import now_iso
from app.utils.validation import clamp

logger = logging.getLogger(__name__)

@dataclass
class RouterContext:
    """Immutable-by-convention inputs for one router evaluation."""
    battery: float
    temperature: float
    signal: float
    state: MissionState
    in_pass: bool
    seconds_to_los: float
    comm_ok: bool
    now: float

@dataclass
class ScoreBreakdown:
    """Weighted point contributions with a rounded total."""
    priority: float
    link: float
    urgency: float
    energy: float
    waiting: float
    total: float
    def to_dict(self) -> dict:
        """Return plain numeric components."""
        return asdict(self)

@dataclass
class RoutingDecision:
    """Persistable explanation of a selected packet."""
    packet_id: int
    packet_type: str
    priority: str
    size_kb: float
    selected_mode: str
    total_score: float
    priority_score: float
    link_score: float
    urgency_score: float
    energy_score: float
    waiting_score: float
    battery: float
    temperature: float
    signal: float
    system_state: str
    reason: str
    mission_time: float
    timestamp: str
    estimated_time: float
    energy_cost: float
    def to_dict(self) -> dict:
        """Return a thread-safe UI event record."""
        return asdict(self)

@dataclass
class RouterResult:
    """Selected decision and packet status changes from one cycle."""
    decision: RoutingDecision | None
    hold_reason: str
    quarantined: list[DataPacket]
    newly_deferred: list[DataPacket]
    active_rules: list[str]

class SafetyRules:
    """Layer one: prohibit unsafe transmissions before any scoring."""
    def global_hold(self, ctx: RouterContext) -> str:
        """Return a reason when no packet may transmit."""
        if not ctx.in_pass:
            return "No active ground pass — packets held until AOS"
        if not ctx.comm_ok or ctx.state is MissionState.COMMUNICATION_LOSS:
            return "RF link down — holding all transmissions"
        return ""
    def check(self, packet: DataPacket, mode: CommunicationMode, ctx: RouterContext) -> str:
        """Return the first packet-specific safety restriction."""
        if mode.mode_type.value not in config.STATE_ALLOWED_MODES[ctx.state.value]:
            return f"{mode.display_name} suspended in {ctx.state.label}"
        if ctx.state is MissionState.SAFE_MODE and packet.priority is not PacketPriority.CRITICAL:
            return "Safe mode: only CRITICAL packets allowed"
        if ctx.signal < config.SIGNAL_MIN_THRESHOLD and packet.priority is not PacketPriority.CRITICAL:
            return f"Signal below {config.SIGNAL_MIN_THRESHOLD:g} % — non-critical held"
        if ctx.signal < mode.minimum_signal_required():
            return f"Needs {mode.minimum_signal_required():g}% signal, link at {ctx.signal:.0f}%"
        if ctx.state is MissionState.LOW_POWER and mode.calculate_energy_cost(packet, ctx.signal) > config.LOW_POWER_MAX_ENERGY_J:
            return "Energy cost too high for low-power state"
        if mode.estimate_transmission_time(packet, ctx.signal) > ctx.seconds_to_los:
            return "Would not finish before LOS"
        return ""
    def describe_active_rules(self, ctx: RouterContext) -> list[str]:
        """List restrictions that operators should see now."""
        rules: list[str] = []
        if not ctx.in_pass:
            rules.append("No ground pass — transmissions held")
        if not ctx.comm_ok or ctx.state is MissionState.COMMUNICATION_LOSS:
            rules.append("RF link down — transmissions held")
        if ctx.state is MissionState.LOW_POWER:
            rules.append("LOW_POWER — SSTV and M17 suspended")
        if ctx.state is MissionState.THERMAL_ALERT:
            rules.append("THERMAL_ALERT — only TT&C mode available")
        if ctx.state is MissionState.SAFE_MODE:
            rules.append("SAFE_MODE — only CRITICAL TT&C allowed")
        if ctx.signal < config.SIGNAL_MIN_THRESHOLD and ctx.in_pass:
            rules.append(f"Signal {ctx.signal:.0f} % < {config.SIGNAL_MIN_THRESHOLD:g} % — non-critical held")
        return rules

class AutonomousRouter:
    """Evaluate all packets in O(n) and select the highest safe score."""
    def __init__(self, modes: dict[CommunicationType, CommunicationMode], weights=config.ROUTING_WEIGHTS,
                 rules: SafetyRules | None = None):
        self.modes, self.weights, self.rules = modes, dict(weights), rules or SafetyRules()
    def score_packet(self, packet: DataPacket, ctx: RouterContext) -> ScoreBreakdown:
        """Combine priority, link, urgency, energy, and waiting points."""
        mode = self.modes[packet.preferred_mode]
        req = mode.minimum_signal_required()
        link = clamp(50 + 50 * (ctx.signal - req) / max(1, 100 - req), 0, 100)
        cost = mode.calculate_energy_cost(packet, ctx.signal)
        pressure = clamp(1.2 - ctx.battery / 100, config.ENERGY_PRESSURE_MIN, config.ENERGY_PRESSURE_MAX)
        energy = clamp(100 - cost / config.ENERGY_REFERENCE_J * 100 * pressure, 0, 100)
        waiting = clamp(packet.age(ctx.now) / config.WAITING_FULL_BONUS_SECONDS * 100, 0, 100)
        values = dict(priority=config.PRIORITY_SCORES[packet.priority.value], link=link,
                      urgency=packet.urgency, energy=energy, waiting=waiting)
        weighted = {key: value * self.weights[key] for key, value in values.items()}
        return ScoreBreakdown(**weighted, total=round(sum(weighted.values()), 1))
    def evaluate(self, packets: list[DataPacket], ctx: RouterContext) -> RouterResult:
        """Quarantine bad packets, apply safety rules, then select a winner."""
        quarantined, deferred = [], []
        intact = []
        for packet in packets:
            try:
                packet.verify_integrity()
                intact.append(packet)
            except TelemetryCorruptionError:
                quarantined.append(packet)
        hold = self.rules.global_hold(ctx)
        active = self.rules.describe_active_rules(ctx)
        for packet in intact:
            packet.score = self.score_packet(packet, ctx).total
            if hold:
                packet.hold_reason = hold
                continue
            reason = self.rules.check(packet, self.modes[packet.preferred_mode], ctx)
            if reason:
                if packet.status is not PacketStatus.DEFERRED:
                    deferred.append(packet)
                packet.status = PacketStatus.DEFERRED
                packet.hold_reason = reason
            elif packet.status not in (PacketStatus.TRANSMITTING, PacketStatus.SELECTED):
                packet.status = PacketStatus.QUEUED
                packet.hold_reason = ""
        eligible = list(filter(lambda p: p.status is PacketStatus.QUEUED and not p.hold_reason, intact))
        if hold or not eligible:
            return RouterResult(None, hold or "No eligible packets", quarantined, deferred, active)
        best = max(eligible, key=lambda p: p.score)
        score = self.score_packet(best, ctx)
        mode = self.modes[best.preferred_mode]
        decision = RoutingDecision(best.packet_id, best.packet_type.value, best.priority.value, best.size_kb,
                                   best.preferred_mode.value, score.total, score.priority, score.link,
                                   score.urgency, score.energy, score.waiting, ctx.battery, ctx.temperature,
                                   ctx.signal, ctx.state.value, self.explain(best, score, ctx), ctx.now,
                                   now_iso(), mode.estimate_transmission_time(best, ctx.signal),
                                   mode.calculate_energy_cost(best, ctx.signal))
        return RouterResult(decision, "", quarantined, deferred, active)
    def explain(self, packet: DataPacket, breakdown: ScoreBreakdown, ctx: RouterContext) -> str:
        """Explain the link margin, energy cost, and spacecraft condition."""
        mode = self.modes[packet.preferred_mode]
        req = mode.minimum_signal_required()
        cost = mode.calculate_energy_cost(packet, ctx.signal)
        return (f"Packet #{packet.packet_id} ({packet.packet_type.label}, {packet.priority.value} priority) scores {breakdown.total:.1f} points. "
                f"The link is {ctx.signal:.0f} %, {ctx.signal - req:+.0f} points against its {req:.0f} % requirement; "
                f"energy cost is {cost:.1f} J with {ctx.battery:.1f} % battery. "
                f"Thermal reading is {ctx.temperature:.1f} °C and the satellite is {ctx.state.label}.")
