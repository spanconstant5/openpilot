from __future__ import annotations

from openpilot.system.telemetry.storage import SegmentClock, TelemetryStorage
from openpilot.tools.telemetry_viewer.model import DriveData


def create_drive(tmp_path):
  start = SegmentClock(1_000_000_000, 1_700_000_000_000)
  storage = TelemetryStorage(tmp_path, start=start)
  for index, speed in enumerate((0.0, 10.0, 20.0)):
    clock = SegmentClock(start.mono_ns + index * 500_000_000, start.wall_ms + index * 500)
    storage.write_sample({"v_ego_mps": speed, "gps_has_fix": False, "driver_distracted": index == 1}, clock)
  storage.write_event(SegmentClock(1_500_000_000, start.wall_ms + 500), "driver_distraction", "True")
  storage.close(SegmentClock(2_100_000_000, start.wall_ms + 1_100))
  return storage.drive_directory


def test_nearest_sample_synchronization(tmp_path):
  drive = DriveData.open(create_drive(tmp_path))
  assert drive.nearest_sample(1_240_000_000)["v_ego_mps"] == 0.0
  assert drive.nearest_sample(1_260_000_000)["v_ego_mps"] == 10.0
  assert drive.sample_at_seconds(1.0)["v_ego_mps"] == 20.0


def test_summary_and_markers(tmp_path):
  drive = DriveData.open(create_drive(tmp_path))
  summary = drive.summary()
  assert summary.duration_seconds == 1.0
  assert summary.distance_meters == 10.0
  assert summary.average_speed_mps == 10.0
  assert summary.maximum_speed_mps == 20.0
  assert summary.distracted_seconds == 0.5
  assert [event.kind for event in drive.markers()] == ["driver_distraction"]
