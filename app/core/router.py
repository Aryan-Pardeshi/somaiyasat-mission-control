"""The autonomous decision engine (the "AI" of this project).

It is a lightweight, explainable, rule + score based decision system —
NOT a trained machine-learning model. Every cycle it works in two layers:

LAYER 1 — SafetyRules (hard constraints, can never be outvoted)
    * no ground pass / RF link down        -> hold everything
    * mode not allowed in the current state (LOW_POWER, THERMAL_ALERT, SAFE_MODE)
    * SAFE_MODE                            -> only CRITICAL packets
    * weak signal / below the mode minimum -> defer
    * too much energy in LOW_POWER, or would not finish before LOS -> defer

LAYER 2 — Weighted score for every packet that passed layer 1
    score = 0.35*priority + 0.25*link + 0.15*urgency + 0.15*energy + 0.10*waiting
    (each component is on a 0-100 scale, so the total is also 0-100;
     the weights live in config.ROUTING_WEIGHTS)

The packet with the highest score is transmitted, and a human-readable reason
is produced for the UI and stored in the ``decisions`` table.
Choosing the best packet is a single pass over the queue: O(n).
"""

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
        if (
            ctx.state is MissionState.LOW_POWER
            and mode.calculate_energy_cost(packet, ctx.signal) > config.LOW_POWER_MAX_ENERGY_J
        ):
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

    def __init__(
        self,
        modes: dict[CommunicationType, CommunicationMode],
        weights=config.ROUTING_WEIGHTS,
        rules: SafetyRules | None = None,
    ):
        self.modes, self.weights, self.rules = modes, dict(weights), rules or SafetyRules()

    def score_packet(self, packet: DataPacket, ctx: RouterContext) -> ScoreBreakdown:
        """Layer 2: combine five 0-100 components into one weighted score."""
        mode = self.modes[packet.preferred_mode]
        # link: 50 when the signal just meets the mode's minimum, 100 at a perfect link.
        # energy: cheap packets score high; the penalty grows as the battery empties
        #         ("pressure" goes from 0.3 on a full battery to 1.0 when nearly empty).
        # waiting: grows with age -> old low-priority packets are not starved forever.
        req = mode.minimum_signal_required()
        link = clamp(50 + 50 * (ctx.signal - req) / max(1, 100 - req), 0, 100)
        cost = mode.calculate_energy_cost(packet, ctx.signal)
        pressure = clamp(1.2 - ctx.battery / 100, config.ENERGY_PRESSURE_MIN, config.ENERGY_PRESSURE_MAX)
        energy = clamp(100 - cost / config.ENERGY_REFERENCE_J * 100 * pressure, 0, 100)
        waiting = clamp(packet.age(ctx.now) / config.WAITING_FULL_BONUS_SECONDS * 100, 0, 100)
        values = dict(
            priority=config.PRIORITY_SCORES[packet.priority.value],
            link=link,
            urgency=packet.urgency,
            energy=energy,
            waiting=waiting,
        )
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
            breakdown = self.score_packet(packet, ctx)
            packet.score = breakdown.total
            packet.breakdown = breakdown.to_dict()
            packet.energy_cost = self.modes[packet.preferred_mode].calculate_energy_cost(packet, ctx.signal)
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
        decision = RoutingDecision(
            best.packet_id,
            best.packet_type.value,
            best.priority.value,
            best.size_kb,
            best.preferred_mode.value,
            score.total,
            score.priority,
            score.link,
            score.urgency,
            score.energy,
            score.waiting,
            ctx.battery,
            ctx.temperature,
            ctx.signal,
            ctx.state.value,
            self.explain(best, score, ctx),
            ctx.now,
            now_iso(),
            mode.estimate_transmission_time(best, ctx.signal),
            mode.calculate_energy_cost(best, ctx.signal),
        )
        return RouterResult(decision, "", quarantined, deferred, active)

    def explain(self, packet: DataPacket, breakdown: ScoreBreakdown, ctx: RouterContext) -> str:
        """Build the plain-English "WHY THIS DECISION?" text from real numbers."""
        mode = self.modes[packet.preferred_mode]
        required = mode.minimum_signal_required()
        cost = mode.calculate_energy_cost(packet, ctx.signal)
        priority_words = {
            "CRITICAL": "critical", "HIGH": "high-priority", "MEDIUM": "medium-priority", "LOW": "low-priority",
        }[packet.priority.value]
        margin = ctx.signal - required
        link_words = "comfortably exceeds" if margin >= 25 else "meets" if margin >= 8 else "only just meets"
        energy_words = "low" if cost < 5 else "moderate" if cost < 15 else "high"
        thermal = ("the satellite is thermally nominal" if ctx.temperature < config.TEMP_WARNING_THRESHOLD
                   else "the satellite is running hot, so only essential traffic is allowed")
        # The largest weighted contribution is the main reason for the choice.
        components = {"its priority": breakdown.priority, "the link quality": breakdown.link,
                      "the urgency of this data type": breakdown.urgency, "its low energy use": breakdown.energy,
                      "how long it has waited": breakdown.waiting}
        main_reason = max(components, key=components.get)
        return (
            f"Packet #{packet.packet_id} was selected because it contains {priority_words} "
            f"{packet.packet_type.label} data and scored highest ({breakdown.total:.1f}/100), mainly due to "
            f"{main_reason}. The current ground link ({ctx.signal:.0f} %) {link_words} the {required:.0f} % "
            f"that {mode.display_name} needs, and its {energy_words} energy cost ({cost:.1f} J) is acceptable "
            f"at {ctx.battery:.0f} % battery. State: {ctx.state.label}; {thermal} ({ctx.temperature:.1f} °C)."
        )
