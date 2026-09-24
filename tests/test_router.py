"""Tests for the autonomous router (Layer 1 safety rules + Layer 2 scoring)."""
from app import config
from app.models.enums import MissionState, PacketStatus
from app.models.packet import create_packet


def sample_queue():
    """The example queue from the project brief."""
    return [
        create_packet("HOUSEKEEPING", 103, "HIGH", 4, created_at=0),
        create_packet("TTC", 104, "CRITICAL", 3, created_at=0),
        create_packet("SSTV", 105, "MEDIUM", 260, created_at=0),
        create_packet("M17", 106, "LOW", 45, created_at=0),
    ]


def test_critical_ttc_is_selected_in_nominal_conditions(router, make_context):
    result = router.evaluate(sample_queue(), make_context())
    assert result.decision is not None
    assert result.decision.packet_id == 104
    assert result.decision.selected_mode == "TTC"


def test_low_signal_defers_packet_whose_mode_needs_more_signal(router, make_context):
    packets = sample_queue()
    # 45 % is enough for TT&C (15 %) but not for SSTV (55 %).
    router.evaluate(packets, make_context(signal=45))
    sstv = packets[2]
    assert sstv.status is PacketStatus.DEFERRED
    assert "55" in sstv.hold_reason


def test_waiting_bonus_prevents_starvation(router, make_context):
    fresh = create_packet("CODEC2", 1, "LOW", 10, created_at=150)
    old = create_packet("CODEC2", 2, "LOW", 10, created_at=0)
    decision = router.evaluate([fresh, old], make_context(now=150)).decision
    assert decision.packet_id == 2          # identical packets: the older one wins
    assert decision.waiting_score > 0


def test_low_power_state_changes_the_decision(router, make_context):
    sstv = create_packet("SSTV", 1, "HIGH", 300, created_at=0)
    codec2 = create_packet("CODEC2", 2, "LOW", 20, created_at=0)
    nominal = router.evaluate([sstv, codec2], make_context())
    assert nominal.decision.packet_id == 1
    low_power = router.evaluate([sstv, codec2], make_context(battery=20, state=MissionState.LOW_POWER))
    assert low_power.decision.packet_id == 2
    assert sstv.status is PacketStatus.DEFERRED


def test_safe_mode_only_allows_critical_packets(router, make_context):
    packets = sample_queue()
    result = router.evaluate(packets, make_context(battery=12, state=MissionState.SAFE_MODE))
    assert result.decision.packet_id == 104
    assert all(p.status is PacketStatus.DEFERRED for p in packets if p.packet_id != 104)


def test_no_ground_pass_means_no_transmission(router, make_context):
    result = router.evaluate(sample_queue(), make_context(in_pass=False, signal=2))
    assert result.decision is None
    assert "ground pass" in result.hold_reason


def test_rf_link_down_holds_everything(router, make_context):
    result = router.evaluate(sample_queue(), make_context(comm_ok=False))
    assert result.decision is None
    assert "RF link down" in result.hold_reason


def test_corrupted_packet_is_quarantined_not_sent(router, make_context):
    packets = sample_queue()
    packets[1].corrupt()                     # flip bytes in the critical TT&C packet
    result = router.evaluate(packets, make_context())
    assert packets[1] in result.quarantined
    assert result.decision.packet_id != 104


def test_packet_that_would_not_finish_before_los_is_deferred(router, make_context):
    sstv = create_packet("SSTV", 1, "HIGH", 400, created_at=0)
    router.evaluate([sstv], make_context(seconds_to_los=3))
    assert sstv.status is PacketStatus.DEFERRED
    assert "LOS" in sstv.hold_reason


def test_score_components_add_up_to_the_total(router, make_context):
    assert abs(sum(config.ROUTING_WEIGHTS.values()) - 1.0) < 1e-9
    breakdown = router.score_packet(create_packet("TTC", 1, "CRITICAL", 3, created_at=0), make_context())
    parts = breakdown.priority + breakdown.link + breakdown.urgency + breakdown.energy + breakdown.waiting
    assert round(parts, 1) == breakdown.total
    assert 0 <= breakdown.total <= 100


def test_explanation_is_human_readable(router, make_context):
    decision = router.evaluate(sample_queue(), make_context()).decision
    assert "Packet #104 was selected" in decision.reason
    assert "TT&C" in decision.reason
