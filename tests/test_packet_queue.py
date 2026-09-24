"""Tests for packets and the packet queue."""
import pytest

from app.core.packet_queue import PacketQueue
from app.exceptions import InvalidPacketError, TelemetryCorruptionError
from app.models.enums import PacketStatus, PacketType
from app.models.packet import SSTVPacket, TTCPacket, create_packet


def test_factory_normalises_strings_and_picks_subclass():
    packet = create_packet(" tt&c ", 100, " critical ", 3, created_at=0)
    assert isinstance(packet, TTCPacket)
    assert packet.packet_type is PacketType.TTC
    assert isinstance(create_packet("sstv", 101, "low", 200, created_at=0), SSTVPacket)


def test_invalid_packets_are_rejected():
    with pytest.raises(InvalidPacketError):
        create_packet("ROCKET", 1, "LOW", 1, created_at=0)
    with pytest.raises(InvalidPacketError):
        create_packet("TTC", 1, "HIGH", -5, created_at=0)


def test_add_and_remove():
    queue = PacketQueue(max_size=5)
    packet = create_packet("TTC", 100, "HIGH", 3, created_at=0)
    assert queue.add(packet) is None
    assert len(queue) == 1 and queue.get(100) is packet
    assert queue.remove(100) is packet
    assert len(queue) == 0


def test_full_queue_evicts_lowest_priority_packet():
    queue = PacketQueue(max_size=2)
    critical = create_packet("TTC", 100, "CRITICAL", 3, created_at=0)
    low = create_packet("M17", 101, "LOW", 30, created_at=0)
    queue.add(critical)
    queue.add(low)
    evicted = queue.add(create_packet("SSTV", 102, "HIGH", 200, created_at=1))
    assert evicted is low
    assert evicted.status is PacketStatus.DROPPED
    assert queue.get(100) is critical


def test_eligible_uses_a_filter_predicate():
    queue = PacketQueue()
    queue.add(create_packet("TTC", 100, "CRITICAL", 3, created_at=0))
    queue.add(create_packet("M17", 101, "LOW", 30, created_at=0))
    critical = queue.eligible(lambda p: p.priority.value == "CRITICAL")
    assert [p.packet_id for p in critical] == [100]


def test_status_changes_deferred_then_queued_again(router, make_context):
    sstv = create_packet("SSTV", 1, "MEDIUM", 200, created_at=0)
    router.evaluate([sstv], make_context(signal=40))
    assert sstv.status is PacketStatus.DEFERRED
    router.evaluate([sstv], make_context(signal=90))
    assert sstv.status is PacketStatus.QUEUED


def test_crc_detects_corruption():
    packet = create_packet("HOUSEKEEPING", 1, "HIGH", 4, created_at=0)
    packet.verify_integrity()                # intact packet: no exception
    packet.corrupt()
    with pytest.raises(TelemetryCorruptionError):
        packet.verify_integrity()
    assert packet.corrupted
