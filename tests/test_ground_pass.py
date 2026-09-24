"""Tests for the simulated ground-station pass (AOS / LOS)."""
import numpy as np

from app import config
from app.core.ground_pass import GroundPass
from app.models.enums import PassPhase

AOS = config.INITIAL_TIME_TO_AOS          # first pass starts 12 s into the mission


def test_pass_lifecycle_phases():
    gp = GroundPass()
    assert gp.info(0).phase is PassPhase.PRE_PASS
    assert gp.info(AOS + 1).phase is PassPhase.AOS
    assert gp.info(AOS + 30).phase is PassPhase.ACTIVE
    assert gp.info(AOS + config.PASS_DURATION + 1).phase is PassPhase.LOS
    assert gp.info(AOS + config.PASS_DURATION + 30).phase is PassPhase.PRE_PASS


def test_countdowns():
    gp = GroundPass()
    assert gp.info(0).seconds_to_aos == AOS
    during = gp.info(AOS + 20)
    assert during.in_pass
    assert during.seconds_to_los == config.PASS_DURATION - 20
    assert gp.next_aos_offset(0) == AOS


def test_signal_is_strongest_mid_pass():
    gp = GroundPass()
    mid = gp.signal_profile(gp.info(AOS + config.PASS_DURATION / 2), np.random.default_rng(1))
    edge = gp.signal_profile(gp.info(AOS + 1), np.random.default_rng(1))
    outside = gp.signal_profile(gp.info(0), np.random.default_rng(1))
    assert mid > edge > outside
    assert 0 <= outside <= config.OUT_OF_PASS_SIGNAL_MAX


def test_satellite_is_over_the_ground_station_mid_pass():
    gp = GroundPass()
    angle = gp.info(AOS + config.PASS_DURATION / 2).orbit_angle
    assert abs(angle - config.GROUND_STATION_ANGLE) < 1.0
