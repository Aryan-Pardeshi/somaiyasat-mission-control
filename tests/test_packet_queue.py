import pytest
from app.models.packet import create_packet
from app.models.enums import PacketStatus
from app.core.packet_queue import PacketQueue
from app.exceptions import InvalidPacketError, TelemetryCorruptionError

def test_factory_integrity_and_queue():
    packet = create_packet(" tt&c ", 100, " critical ", 3, 0)
    assert packet.packet_type.value == "TTC"
    q = PacketQueue(2)
    q.add(packet)
    low = create_packet("m17", 101, "low", 3, 0)
    q.add(low)
    dropped = q.add(create_packet("sstv", 102, "high", 3, 1))
    assert dropped is low and dropped.status == PacketStatus.DROPPED
    assert q.eligible(lambda p: p.priority.value == "CRITICAL") == [packet]
    assert q.remove(100) is packet
    packet.corrupt()
    with pytest.raises(TelemetryCorruptionError): packet.verify_integrity()
    with pytest.raises(InvalidPacketError): create_packet("bad", 1, "low", 1, 0)
    with pytest.raises(InvalidPacketError): create_packet("ttc", 1, "high", "invalid", 0)
