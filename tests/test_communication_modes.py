import pytest
from app.models.communication_modes import CommunicationMode, TTCMode, SSTVMode, M17Mode, Codec2Mode
from app.models.packet import create_packet

def test_polymorphic_rates():
    with pytest.raises(TypeError): CommunicationMode()
    p = create_packet("sstv", 1, "medium", 260, 0)
    s = SSTVMode()
    assert s.estimate_transmission_time(p, 55) == s.estimate_transmission_time(p, 95)
    assert M17Mode().transmit(p, 90, 1) > M17Mode().transmit(p, 45, 1)
    assert Codec2Mode().power_draw != TTCMode().power_draw
