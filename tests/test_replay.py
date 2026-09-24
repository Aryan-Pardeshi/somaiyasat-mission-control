"""Tests for CSV mission replay validation (Pandas)."""
import pytest

from app import config
from app.core.replay_engine import ReplayEngine
from app.exceptions import ReplayDataError
from app.utils.validation import parse_timestamp

HEADER = "timestamp,battery,temp,signal,power_draw,packet_loss,packet_type,priority,size_kb,event\n"


def write_csv(tmp_path, body: str, header: str = HEADER):
    path = tmp_path / "mission.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def test_valid_csv_loads_and_finds_pass_windows(tmp_path):
    path = write_csv(tmp_path,
                     "00:00:00,90,27,0,0.5,0,,,,\n"
                     "00:00:01,90,27,80,1.0,1,TTC,HIGH,3,\n"
                     "00:00:02,89,28,85,1.0,1,,,,\n"
                     "00:00:03,89,28,90,1.0,1,SSTV,MEDIUM,250,\n"
                     "00:00:04,89,28,0,0.5,0,,,,\n")
    report = ReplayEngine().load_csv(path)
    assert report.valid_rows == 5 and report.invalid_rows == 0
    assert report.pass_windows == [(1.0, 3.0)]
    assert report.duration == 4.0


def test_missing_columns_raise_replay_error(tmp_path):
    path = write_csv(tmp_path, "0,90\n", header="timestamp,battery\n")
    with pytest.raises(ReplayDataError, match="signal"):
        ReplayEngine().load_csv(path)


def test_invalid_rows_are_reported_and_dropped(tmp_path):
    path = write_csv(tmp_path,
                     "00:00:01,90,27,80,1,0,TTC,HIGH,3,\n"
                     "00:00:02,140,27,80,1,0,,,,\n"          # battery out of range
                     "00:00:03,90,27,80,1,0,ROCKET,HIGH,3,\n"  # unknown packet type
                     "00:00:04,90,27,abc,1,0,,,,\n"           # non-numeric signal
                     "00:00:05,90,27,80,1,0,SSTV,MEDIUM,250,\n")
    report = ReplayEngine().load_csv(path)
    assert report.valid_rows == 2
    assert report.invalid_rows == 3
    assert any("battery" in error for error in report.errors)


def test_all_invalid_rows_raise_replay_error(tmp_path):
    path = write_csv(tmp_path, "0,140,27,80,1,0,,,,\n")
    with pytest.raises(ReplayDataError):
        ReplayEngine().load_csv(path)


def test_missing_file_raises_replay_error(tmp_path):
    with pytest.raises(ReplayDataError):
        ReplayEngine().load_csv(tmp_path / "does_not_exist.csv")


def test_timestamp_formats():
    assert parse_timestamp("01:02") == 62
    assert parse_timestamp("01:02:03") == 3723
    assert parse_timestamp("15") == 15
    assert parse_timestamp("2026-09-25T00:00:10") > 0


@pytest.mark.parametrize("path", [config.SAMPLE_MISSION_CSV, config.STRESSFUL_MISSION_CSV])
def test_bundled_sample_missions_are_valid(path):
    report = ReplayEngine().load_csv(path)
    assert report.invalid_rows == 0
    assert report.valid_rows >= 400
    assert len(report.pass_windows) >= 2
