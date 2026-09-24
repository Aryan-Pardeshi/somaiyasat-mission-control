import numpy as np
from app.core.ground_pass import GroundPass
from app.models.enums import PassPhase

def test_pass_and_profile():
    gp = GroundPass()
    assert gp.info(0).phase == PassPhase.PRE_PASS
    assert gp.info(12).phase == PassPhase.AOS
    assert gp.info(42).phase == PassPhase.ACTIVE
    assert gp.info(72).phase == PassPhase.LOS
    assert gp.next_aos_offset(0) == 12
    assert gp.signal_profile(gp.info(42), np.random.default_rng(1)) > gp.signal_profile(gp.info(12), np.random.default_rng(1))
