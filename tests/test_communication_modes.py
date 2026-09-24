"""Tests for the CommunicationMode inheritance hierarchy (polymorphism)."""
import pytest

from app import config
from app.exceptions import TelemetryCorruptionError
from app.models.communication_modes import (CommunicationMode, Codec2Mode, M17Mode, SSTVMode, TTCMode,
                                            build_modes)
from app.models.packet import create_packet


def test_abstract_base_class_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CommunicationMode()


def test_build_modes_creates_one_object_per_supported_mode():
    modes = build_modes()
    assert {mode.value for mode in modes} == config.SUPPORTED_MODES
    assert all(isinstance(mode, CommunicationMode) for mode in modes.values())


def test_sstv_speed_does_not_depend_on_signal():
    image = create_packet("SSTV", 1, "MEDIUM", 260, created_at=0)
    sstv = SSTVMode()
    assert sstv.estimate_transmission_time(image, 56) == sstv.estimate_transmission_time(image, 95)


def test_m17_is_much_faster_on_a_strong_signal():
    voice = create_packet("M17", 1, "LOW", 50, created_at=0)
    assert M17Mode().transmit(voice, 90, 1.0) > 2 * M17Mode().transmit(voice, 42, 1.0)


def test_same_method_call_behaves_differently_per_class():
    packet = create_packet("HOUSEKEEPING", 1, "HIGH", 10, created_at=0)
    times = {cls.__name__: cls().estimate_transmission_time(packet, 60)
             for cls in (TTCMode, M17Mode, Codec2Mode, SSTVMode)}
    assert len(set(times.values())) == 4


def test_sstv_energy_includes_encoder_overhead():
    image = create_packet("SSTV", 1, "MEDIUM", 200, created_at=0)
    sstv = SSTVMode()
    rf_only = sstv.power_draw * sstv.estimate_transmission_time(image, 80)
    assert sstv.calculate_energy_cost(image, 80) == pytest.approx(rf_only + config.SSTV_ENCODER_OVERHEAD_J)


def test_transmit_refuses_corrupted_packets():
    packet = create_packet("TTC", 1, "CRITICAL", 3, created_at=0)
    packet.corrupt()
    with pytest.raises(TelemetryCorruptionError):
        TTCMode().transmit(packet, 80, 0.1)
