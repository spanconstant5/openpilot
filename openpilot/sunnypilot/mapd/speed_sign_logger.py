import json
import time
from datetime import UTC, datetime
from pathlib import Path

from openpilot.common.constants import CV
from openpilot.common.hardware.hw import Paths


STABLE_SECONDS = 1.5
CLEAR_SECONDS = 3.0
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_PATH = Path(Paths.mapd_root()) / "speed_sign_observations.jsonl"


class SpeedSignObservationLogger:
  """Record stable, car-observed speed limits at their first-seen GPS position."""

  def __init__(self, path: Path = LOG_PATH, stable_seconds: float = STABLE_SECONDS,
               clear_seconds: float = CLEAR_SECONDS, max_log_bytes: int = MAX_LOG_BYTES):
    self.path = path
    self.stable_seconds = stable_seconds
    self.clear_seconds = clear_seconds
    self.max_log_bytes = max_log_bytes
    self.candidate = 0.0
    self.candidate_since = 0.0
    self.candidate_gps = None
    self.candidate_map_limit = None
    self.clear_since = None
    self.last_logged = None

  @staticmethod
  def _normalize_limit(speed_limit_mps: float) -> float:
    return round(max(0.0, speed_limit_mps), 4)

  def _rotate_if_needed(self) -> None:
    if not self.path.exists() or self.path.stat().st_size < self.max_log_bytes:
      return
    backup = self.path.with_suffix(self.path.suffix + ".1")
    backup.unlink(missing_ok=True)
    self.path.replace(backup)

  def _write(self, record: dict) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    self._rotate_if_needed()
    with self.path.open("a", encoding="utf-8") as f:
      f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

  def update(self, now: float, speed_limit_mps: float, gps: dict | None,
             map_limit_mps: float | None, display_unit: str) -> dict | None:
    speed_limit = self._normalize_limit(speed_limit_mps)

    if speed_limit <= 0.0:
      self.candidate = 0.0
      self.candidate_gps = None
      self.candidate_map_limit = None
      if self.clear_since is None:
        self.clear_since = now
      elif now - self.clear_since >= self.clear_seconds:
        self.last_logged = None
      return None

    self.clear_since = None
    if speed_limit != self.candidate:
      self.candidate = speed_limit
      self.candidate_since = now
      self.candidate_gps = gps
      self.candidate_map_limit = map_limit_mps
      return None

    # Preserve the first valid fix after detection if GPS was briefly unavailable.
    if self.candidate_gps is None and gps is not None:
      self.candidate_gps = gps
      self.candidate_map_limit = map_limit_mps

    if now - self.candidate_since < self.stable_seconds or self.last_logged == speed_limit or self.candidate_gps is None:
      return None

    gps_fix = self.candidate_gps
    map_limit = self.candidate_map_limit
    timestamp_ms = int(gps_fix["unix_timestamp_ms"])
    record = {
      "schema_version": 1,
      "source": "toyota_rsa",
      "timestamp_utc": datetime.fromtimestamp(timestamp_ms / 1000.0, UTC).isoformat(),
      "unix_timestamp_ms": timestamp_ms,
      "latitude": gps_fix["latitude"],
      "longitude": gps_fix["longitude"],
      "bearing_deg": gps_fix["bearing_deg"],
      "bearing_accuracy_deg": gps_fix["bearing_accuracy_deg"],
      "horizontal_accuracy_m": gps_fix["horizontal_accuracy_m"],
      "vehicle_speed_mps": gps_fix["speed_mps"],
      "display_unit": display_unit,
      "speed_limit_mps": speed_limit,
      "speed_limit_mph": round(speed_limit * CV.MS_TO_MPH, 1),
      "speed_limit_kph": round(speed_limit * CV.MS_TO_KPH, 1),
      "map_speed_limit_mps": round(map_limit, 4) if map_limit is not None else None,
      "map_matches_observation": map_limit is not None and abs(map_limit - speed_limit) < 0.3,
    }
    self._write(record)
    self.last_logged = speed_limit
    return record


def main() -> None:
  import openpilot.cereal.messaging as messaging
  from openpilot.common.gps import get_gps_location_service
  from openpilot.common.params import Params

  params = Params()
  gps_service = get_gps_location_service(params)
  sm = messaging.SubMaster(["carStateSP", "liveMapDataSP", gps_service], poll="carStateSP")
  logger = SpeedSignObservationLogger()
  display_unit = "kph" if params.get_bool("IsMetric") else "mph"

  while True:
    sm.update()
    if not sm.updated["carStateSP"]:
      continue

    gps_msg = sm[gps_service]
    gps = None
    if sm.valid[gps_service] and sm.alive[gps_service] and gps_msg.hasFix and gps_msg.unixTimestampMillis > 0:
      gps = {
        "unix_timestamp_ms": gps_msg.unixTimestampMillis,
        "latitude": gps_msg.latitude,
        "longitude": gps_msg.longitude,
        "bearing_deg": gps_msg.bearingDeg,
        "bearing_accuracy_deg": gps_msg.bearingAccuracyDeg,
        "horizontal_accuracy_m": gps_msg.horizontalAccuracy,
        "speed_mps": gps_msg.speed,
      }

    map_data = sm["liveMapDataSP"]
    map_limit = None
    if sm.valid["liveMapDataSP"] and sm.alive["liveMapDataSP"] and map_data.speedLimitValid:
      map_limit = float(map_data.speedLimit)

    logger.update(time.monotonic(), float(sm["carStateSP"].speedLimit), gps, map_limit, display_unit)


if __name__ == "__main__":
  main()
