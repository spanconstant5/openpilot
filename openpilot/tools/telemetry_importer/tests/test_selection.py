from pathlib import Path, PurePosixPath

from openpilot.tools.telemetry_importer.selection import needs_copy, safe_relative_posix, select_completed_files


def test_selects_complete_segments_and_associated_video():
  manifest = {
    "segments": [
      {"filename": "segment_000.db", "status": "complete", "size_bytes": 123},
      {"filename": "segment_001.db", "status": "active", "size_bytes": 456},
      {"filename": "segment_002.db", "status": "corrupt", "size_bytes": 789},
    ],
    "video_segments": [
      {"source_relative_path": "route--0/fcamera.hevc"},
      {"source_relative_path": "route--0/fcamera.hevc"},
    ],
  }
  selected = select_completed_files(manifest, PurePosixPath("/data/media/0/telemetry/2026-01-01/drive_001"))
  assert [item.kind for item in selected] == ["telemetry", "video"]
  assert selected[0].expected_size == 123
  assert selected[1].local_relative_path == Path("video", "route--0", "fcamera.hevc")


def test_rejects_unsafe_paths():
  for value in ("../segment.db", "/absolute.db", "route/../../escape", ""):
    try:
      safe_relative_posix(value)
    except ValueError:
      pass
    else:
      raise AssertionError(f"unsafe path was accepted: {value!r}")


def test_size_match_skips_copy(tmp_path):
  destination = tmp_path / "segment.db"
  destination.write_bytes(b"1234")
  assert not needs_copy(destination, 4)
  assert needs_copy(destination, 5)
  assert needs_copy(tmp_path / "missing.db", 4)
