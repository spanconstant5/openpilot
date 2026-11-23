import json

from openpilot.common.constants import CV
from openpilot.sunnypilot.mapd.speed_sign_logger import SpeedSignObservationLogger


def gps_fix(timestamp_ms=1_700_000_000_000):
  return {
    "unix_timestamp_ms": timestamp_ms,
    "latitude": 41.9,
    "longitude": -87.6,
    "bearing_deg": 90.0,
    "bearing_accuracy_deg": 1.5,
    "horizontal_accuracy_m": 2.0,
    "speed_mps": 12.0,
  }


def test_logs_stable_sign_at_first_seen_position(tmp_path):
  path = tmp_path / "observations.jsonl"
  logger = SpeedSignObservationLogger(path, stable_seconds=1.0)
  limit = 35 * CV.MPH_TO_MS

  assert logger.update(10.0, limit, gps_fix(), None, "mph") is None
  assert logger.update(10.9, limit, gps_fix(1_700_000_001_000), None, "mph") is None
  record = logger.update(11.1, limit, gps_fix(1_700_000_002_000), None, "mph")

  assert record is not None
  assert record["unix_timestamp_ms"] == 1_700_000_000_000
  assert record["speed_limit_mph"] == 35.0
  assert json.loads(path.read_text().strip()) == record


def test_deduplicates_until_sign_clears(tmp_path):
  logger = SpeedSignObservationLogger(tmp_path / "observations.jsonl", stable_seconds=0.5, clear_seconds=1.0)
  limit = 45 * CV.MPH_TO_MS

  logger.update(0.0, limit, gps_fix(), limit, "mph")
  assert logger.update(0.6, limit, gps_fix(), limit, "mph") is not None
  assert logger.update(2.0, limit, gps_fix(), limit, "mph") is None
  logger.update(3.0, 0.0, gps_fix(), limit, "mph")
  logger.update(4.1, 0.0, gps_fix(), limit, "mph")
  logger.update(5.0, limit, gps_fix(), limit, "mph")
  assert logger.update(5.6, limit, gps_fix(), limit, "mph") is not None
