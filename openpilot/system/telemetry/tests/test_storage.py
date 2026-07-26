from __future__ import annotations

import json
import sqlite3

from openpilot.system.telemetry.schema import SCHEMA_VERSION, schema_version
from openpilot.system.telemetry.storage import SegmentClock, TelemetryStorage, load_manifest, recover_active_segments


START = SegmentClock(1_000_000_000, 1_700_000_000_000)


def test_schema_creation(tmp_path):
  storage = TelemetryStorage(tmp_path, start=START)
  path = storage.database_path
  storage.close(SegmentClock(1_100_000_000, START.wall_ms + 100))

  with sqlite3.connect(path) as connection:
    assert schema_version(connection) == SCHEMA_VERSION
    status, drive_id = connection.execute("SELECT status, drive_id FROM segment_metadata").fetchone()
    assert status == "complete"
    assert drive_id == "drive_001"
    sample_columns = {row[1] for row in connection.execute("PRAGMA table_info(samples)")}
    assert {"engine_running", "ev_mode", "power_flow_kw", "lta_active", "tss_status"} <= sample_columns


def test_rotation_marks_only_closed_segments_complete(tmp_path):
  storage = TelemetryStorage(tmp_path, start=START, segment_seconds=1)
  storage.write_sample({"v_ego_mps": 1.0}, SegmentClock(1_100_000_000, START.wall_ms + 100))
  storage.write_sample({"v_ego_mps": 2.0}, SegmentClock(2_100_000_000, START.wall_ms + 1_100))

  manifest = load_manifest(storage.drive_directory / "manifest.json")
  assert [segment["status"] for segment in manifest["segments"]] == ["complete", "active"]

  storage.close(SegmentClock(2_200_000_000, START.wall_ms + 1_200))
  manifest = load_manifest(storage.drive_directory / "manifest.json")
  assert [segment["status"] for segment in manifest["segments"]] == ["complete", "complete"]
  assert manifest["segments"][0]["close_reason"] == "rotation"


def test_recovery_finalizes_healthy_wal_segment(tmp_path):
  storage = TelemetryStorage(tmp_path, start=START)
  storage.write_sample({"v_ego_mps": 3.0}, SegmentClock(1_100_000_000, START.wall_ms + 100))
  assert storage.connection is not None
  storage.connection.commit()
  database_path = storage.database_path
  manifest_path = storage.drive_directory / "manifest.json"
  storage.connection.close()  # simulate process death before the status update
  storage.connection = None
  storage.closed = True

  recovered = recover_active_segments(tmp_path, 1_200_000_000, START.wall_ms + 200)
  assert recovered == [database_path]
  manifest = load_manifest(manifest_path)
  assert manifest["segments"][0]["status"] == "complete"
  assert manifest["segments"][0]["close_reason"] == "crash_recovered"

  with sqlite3.connect(database_path) as connection:
    status, reason = connection.execute("SELECT status, close_reason FROM segment_metadata").fetchone()
    assert (status, reason) == ("complete", "crash_recovered")


def test_invalid_manifest_version_is_rejected(tmp_path):
  path = tmp_path / "manifest.json"
  path.write_text(json.dumps({"schema_version": 999, "segments": []}), encoding="utf-8")
  try:
    load_manifest(path)
  except ValueError as error:
    assert "unsupported manifest schema" in str(error)
  else:
    raise AssertionError("invalid schema version was accepted")


def test_video_association_is_deduplicated(tmp_path):
  storage = TelemetryStorage(tmp_path, start=START)
  storage.associate_video(START, "00000001--abcdef1234", 7, 900_000_000)
  storage.associate_video(SegmentClock(1_200_000_000, START.wall_ms + 200), "00000001--abcdef1234", 7, 1_100_000_000)
  storage.close(SegmentClock(1_300_000_000, START.wall_ms + 300))

  manifest = load_manifest(storage.drive_directory / "manifest.json")
  assert len(manifest["video_segments"]) == 1
  assert manifest["video_segments"][0]["last_mono_ns"] == 1_200_000_000
  with sqlite3.connect(storage.database_path) as connection:
    assert connection.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0] == 1


def test_ignition_off_finalizes_and_resume_opens_a_new_segment(tmp_path):
  storage = TelemetryStorage(tmp_path, start=START)
  off = SegmentClock(1_200_000_000, START.wall_ms + 200)
  storage.write_sample({"v_ego_mps": 0.0}, SegmentClock(1_100_000_000, START.wall_ms + 100))
  storage.finalize_active_segment(off, "ignition_off")
  manifest = load_manifest(storage.drive_directory / "manifest.json")
  assert manifest["segments"][0]["status"] == "complete"
  assert manifest["segments"][0]["close_reason"] == "ignition_off"

  storage.resume(SegmentClock(2_000_000_000, START.wall_ms + 1_000))
  storage.write_sample({"v_ego_mps": 1.0}, SegmentClock(2_100_000_000, START.wall_ms + 1_100))
  storage.close(SegmentClock(2_200_000_000, START.wall_ms + 1_200))
  manifest = load_manifest(storage.drive_directory / "manifest.json")
  assert [segment["status"] for segment in manifest["segments"]] == ["complete", "complete"]
