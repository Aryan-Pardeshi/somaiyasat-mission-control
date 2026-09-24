import pytest
from app.core.replay_engine import ReplayEngine
from app.exceptions import ReplayDataError
from app.utils.validation import parse_timestamp

HEADER = "timestamp,battery,temp,signal,power_draw,packet_loss,packet_type,priority,size_kb,event\n"
def test_validation_and_windows(tmp_path):
    path = tmp_path / "replay.csv"
    path.write_text(HEADER + "00:00:00,90,27,0,1,0,,,,\n00:00:01,90,27,80,1,0,TTC,HIGH,3,\n00:00:02,140,27,80,1,0,,,,\n00:00:03,89,27,90,1,0,,,,\n00:00:04,89,27,0,1,0,,,,\n")
    engine = ReplayEngine()
    report = engine.load_csv(path)
    assert report.valid_rows == 4 and report.invalid_rows == 1
    assert report.pass_windows == [(1.0, 3.0)]
    assert parse_timestamp("01:02") == 62
    assert parse_timestamp("01:02:03") == 3723
    assert parse_timestamp("2026-09-25T00:00:00") > 0
    path.write_text("timestamp,battery\n0,1\n")
    with pytest.raises(ReplayDataError): engine.load_csv(path)
    path.write_text(HEADER + "0,140,27,80,1,0,,,,\n")
    with pytest.raises(ReplayDataError): engine.load_csv(path)
