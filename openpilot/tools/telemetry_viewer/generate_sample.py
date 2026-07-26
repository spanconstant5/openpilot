from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from openpilot.system.telemetry.storage import SegmentClock, TelemetryStorage


def generate_sample(output: Path, duration_seconds: int = 180, sample_rate_hz: int = 20) -> Path:
  start_wall_ms = time.time_ns() // 1_000_000
  start_mono_ns = 10_000_000_000
  start = SegmentClock(start_mono_ns, start_wall_ms)
  storage = TelemetryStorage(output, start=start, metadata={
    "sample_rate_hz": sample_rate_hz,
    "sample_data": True,
      "hardware_targets": ["comma 3", "comma 3X", "comma 4"],
      "vehicle_brand": "toyota",
  })
  transitions: dict[str, bool] = {}
  for index in range(duration_seconds * sample_rate_hz):
    elapsed = index / sample_rate_hz
    mono_ns = start_mono_ns + round(elapsed * 1e9)
    wall_ms = start_wall_ms + round(elapsed * 1000)
    speed = max(0.0, 22.0 + 7.0 * math.sin(elapsed / 18.0))
    steering = 18.0 * math.sin(elapsed / 7.0)
    gas = max(0.0, min(1.0, 0.35 + 0.3 * math.sin(elapsed / 11.0)))
    braking = 62 <= elapsed < 67
    distracted = 95 <= elapsed < 103
    engaged = elapsed >= 8 and not (125 <= elapsed < 135)
    sample = {
      "v_ego_mps": speed,
      "a_ego_mps2": 7.0 / 18.0 * math.cos(elapsed / 18.0),
      "steering_angle_deg": steering,
      "steering_torque": 0.6 * math.sin(elapsed / 7.0),
      "steering_pressed": 42 <= elapsed < 46,
      "gas": 0.0 if braking else gas,
      "gas_pressed": not braking,
      "brake": 0.75 if braking else 0.0,
      "brake_pressed": braking,
      "engine_rpm": 900 + speed * 52,
      "engine_running": True,
      "hybrid_battery_percent": 61.0 + 8.0 * math.sin(elapsed / 45.0),
      "ev_mode": False,
      "power_flow_kw": speed * (7.0 / 18.0 * math.cos(elapsed / 18.0)) * 1.45,
      "power_flow_source": "estimated_traction",
      "hybrid_drive_force_n": None,
      "stock_aeb": False,
      "cruise_available": True,
      "cruise_enabled": engaged,
      "lta_active": engaged,
      "tss_status": "TSS ACTIVE · RADAR + LTA" if engaged else "TSS READY",
      "selfdrive_state": "enabled" if engaged else "disabled",
      "engaged": engaged,
      "active": engaged,
      "engageable": True,
      "gps_latitude": 41.8781 + elapsed * 0.00001,
      "gps_longitude": -87.6298 + elapsed * 0.000015,
      "gps_speed_mps": speed,
      "gps_bearing_deg": 58.0,
      "gps_accuracy_m": 1.8,
      "gps_has_fix": True,
      "gps_unix_time_ms": wall_ms,
      "driver_face_detected": True,
      "driver_distracted": distracted,
      "driver_awareness": 0.55 if distracted else 1.0,
      "driver_face_probability": 0.98,
      "driver_face_pitch": 0.03,
      "driver_face_yaw": 0.12 if distracted else 0.01,
      "driver_face_roll": 0.0,
    }
    clock = SegmentClock(mono_ns, wall_ms)
    storage.write_sample(sample, clock)
    if index % (sample_rate_hz // 5) == 0:
      x = [float(point) for point in range(0, 101, 5)]
      y = [math.sin(elapsed / 7.0) * point * point / 8000.0 for point in x]
      storage.write_model_path(clock, index, x, y, [0.0] * len(x))
    for kind, active in (("brake_override", braking), ("steering_override", 42 <= elapsed < 46),
                         ("driver_distraction", distracted), ("engagement", engaged)):
      previous = transitions.get(kind)
      if previous is None or previous != active:
        storage.write_event(clock, kind, str(active))
        transitions[kind] = active
  storage.close(SegmentClock(start_mono_ns + duration_seconds * 1_000_000_000,
                             start_wall_ms + duration_seconds * 1000))
  return storage.drive_directory


def main() -> None:
  parser = argparse.ArgumentParser(description="Generate a synthetic dashcam telemetry drive")
  parser.add_argument("output", type=Path, nargs="?", default=Path("sample_telemetry"))
  parser.add_argument("--duration", type=int, default=180, help="sample duration in seconds")
  args = parser.parse_args()
  print(generate_sample(args.output, args.duration))


if __name__ == "__main__":
  main()
