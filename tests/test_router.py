from app.core.router import AutonomousRouter, RouterContext
from app.models.communication_modes import build_modes
from app.models.enums import MissionState, PacketStatus
from app.models.packet import create_packet
from app import config

def context(**changes):
    return RouterContext(**(dict(battery=90, temperature=27, signal=95, state=MissionState.NOMINAL, in_pass=True, seconds_to_los=60, comm_ok=True, now=5) | changes))

def test_safety_and_scoring():
    router = AutonomousRouter(build_modes())
    packets = [create_packet("ttc", 1, "critical", 3, 0),
               create_packet("sstv", 2, "medium", 5, 0),
               create_packet("m17", 3, "low", 5, 0)]
    assert router.evaluate(packets, context()).decision.packet_id == 1
    assert router.evaluate(packets, context(signal=25)).decision.packet_id == 1
    assert packets[1].status == PacketStatus.DEFERRED
    assert router.evaluate(packets, context(in_pass=False)).decision is None
    assert router.evaluate(packets, context(state=MissionState.SAFE_MODE)).decision.packet_id == 1
    assert router.evaluate(packets, context(state=MissionState.LOW_POWER)).decision.packet_id == 1
    assert packets[1].status == packets[2].status == PacketStatus.DEFERRED
    score = router.score_packet(packets[0], context())
    assert round(sum((score.priority, score.link, score.urgency, score.energy, score.waiting)), 1) == score.total
    assert sum(config.ROUTING_WEIGHTS.values()) == 1
    packets[0].corrupt()
    assert packets[0] in router.evaluate(packets, context()).quarantined

def test_waiting_bonus():
    router = AutonomousRouter(build_modes())
    old = create_packet("codec2", 1, "low", 10, 0)
    fresh = create_packet("codec2", 2, "low", 10, 150)
    assert router.evaluate([fresh, old], context(now=150)).decision.packet_id == 1
