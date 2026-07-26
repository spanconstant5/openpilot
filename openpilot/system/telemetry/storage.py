from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import INSERT_SAMPLE_SQL, SAMPLE_COLUMNS, SCHEMA_VERSION, create_schema


DEFAULT_SEGMENT_SECONDS = 30 * 60
DEFAULT_COMMIT_SECONDS = 1.0


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(path.suffix + ".tmp")
  with temporary.open("w", encoding="utf-8", newline="\n") as stream:
    json.dump(value, stream, indent=2, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
  os.replace(temporary, path)


def load_manifest(path: Path) -> dict[str, Any]:
  with path.open("r", encoding="utf-8") as stream:
    manifest = json.load(stream)
  if manifest.get("schema_version") != SCHEMA_VERSION:
    raise ValueError(f"unsupported manifest schema: {manifest.get('schema_version')}")
  if not isinstance(manifest.get("segments"), list):
    raise ValueError("manifest is missing segments")
  return manifest


def _finish_recovered_database(path: Path, end_mono_ns: int, end_wall_ms: int) -> bool:
  try:
    connection = sqlite3.connect(path)
    result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or result[0] != "ok":
      connection.close()
      return False
    connection.execute(
      """UPDATE segment_metadata SET status = 'complete', end_mono_ns = ?,
         end_wall_ms = ?, close_reason = 'crash_recovered' WHERE status = 'active'""",
      (end_mono_ns, end_wall_ms),
    )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    return True
  except (OSError, sqlite3.DatabaseError):
    return False


def recover_active_segments(root: Path, now_mono_ns: int | None = None,
                            now_wall_ms: int | None = None) -> list[Path]:
  """Finalize WAL-backed segments left active by an unexpected process exit."""
  now_mono_ns = time.monotonic_ns() if now_mono_ns is None else now_mono_ns
  now_wall_ms = time.time_ns() // 1_000_000 if now_wall_ms is None else now_wall_ms
  recovered: list[Path] = []
  if not root.exists():
    return recovered

  for manifest_path in root.glob("*/drive_*/manifest.json"):
    try:
      manifest = load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
      continue

    changed = False
    for segment in manifest["segments"]:
      if segment.get("status") != "active":
        continue
      database_path = manifest_path.parent / str(segment.get("filename", ""))
      healthy = database_path.is_file() and _finish_recovered_database(database_path, now_mono_ns, now_wall_ms)
      segment["status"] = "complete" if healthy else "corrupt"
      segment["end_mono_ns"] = now_mono_ns
      segment["end_wall_ms"] = now_wall_ms
      segment["close_reason"] = "crash_recovered" if healthy else "recovery_failed"
      if healthy:
        segment["size_bytes"] = database_path.stat().st_size
        recovered.append(database_path)
      changed = True
    if changed:
      manifest["updated_wall_ms"] = now_wall_ms
      atomic_write_json(manifest_path, manifest)
  return recovered


def allocate_drive_directory(root: Path, wall_time_ms: int) -> tuple[str, Path]:
  date = datetime.fromtimestamp(wall_time_ms / 1000).astimezone().strftime("%Y-%m-%d")
  day_directory = root / date
  day_directory.mkdir(parents=True, exist_ok=True)
  used = {
    int(path.name.removeprefix("drive_"))
    for path in day_directory.glob("drive_[0-9][0-9][0-9]")
    if path.name.removeprefix("drive_").isdigit()
  }
  index = next(candidate for candidate in range(1, 1000) if candidate not in used)
  drive_id = f"drive_{index:03d}"
  drive_directory = day_directory / drive_id
  drive_directory.mkdir()
  return drive_id, drive_directory


@dataclass(frozen=True)
class SegmentClock:
  mono_ns: int
  wall_ms: int


class TelemetryStorage:
  def __init__(self, root: Path | str, start: SegmentClock | None = None,
               segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
               commit_seconds: float = DEFAULT_COMMIT_SECONDS,
               metadata: dict[str, Any] | None = None):
    self.root = Path(root)
    self.root.mkdir(parents=True, exist_ok=True)
    start = start or SegmentClock(time.monotonic_ns(), time.time_ns() // 1_000_000)
    recover_active_segments(self.root, start.mono_ns, start.wall_ms)
    self.drive_id, self.drive_directory = allocate_drive_directory(self.root, start.wall_ms)
    self.segment_duration_ns = segment_seconds * 1_000_000_000
    self.commit_interval_ns = int(commit_seconds * 1_000_000_000)
    self.segment_index = -1
    self.connection: sqlite3.Connection | None = None
    self.segment_start_mono_ns = start.mono_ns
    self.last_commit_mono_ns = start.mono_ns
    self.closed = False
    self.manifest: dict[str, Any] = {
      "schema_version": SCHEMA_VERSION,
      "drive_id": self.drive_id,
      "created_wall_ms": start.wall_ms,
      "updated_wall_ms": start.wall_ms,
      "segments": [],
      "video_segments": [],
    }
    self.metadata: dict[str, Any] = {
      "schema_version": SCHEMA_VERSION,
      "drive_id": self.drive_id,
      "created_wall_ms": start.wall_ms,
      "recording": "read-only telemetry; source video is stored by openpilot encoderd",
    }
    if metadata:
      self.metadata.update(metadata)
    atomic_write_json(self.drive_directory / "metadata.json", self.metadata)
    self._write_manifest(start.wall_ms)
    self._open_segment(start)

  @property
  def database_path(self) -> Path:
    return self.drive_directory / f"segment_{self.segment_index:03d}.db"

  def _write_manifest(self, wall_ms: int) -> None:
    self.manifest["updated_wall_ms"] = wall_ms
    atomic_write_json(self.drive_directory / "manifest.json", self.manifest)

  def _open_segment(self, start: SegmentClock) -> None:
    self.segment_index += 1
    self.segment_start_mono_ns = start.mono_ns
    self.last_commit_mono_ns = start.mono_ns
    filename = f"segment_{self.segment_index:03d}.db"
    self.connection = sqlite3.connect(self.drive_directory / filename)
    self.connection.execute("PRAGMA journal_mode=WAL")
    self.connection.execute("PRAGMA synchronous=NORMAL")
    create_schema(self.connection, self.drive_id, self.segment_index, start.mono_ns, start.wall_ms)
    self.manifest["segments"].append({
      "index": self.segment_index,
      "filename": filename,
      "status": "active",
      "start_mono_ns": start.mono_ns,
      "start_wall_ms": start.wall_ms,
    })
    self._write_manifest(start.wall_ms)

  def _close_segment(self, end: SegmentClock, reason: str) -> None:
    if self.connection is None:
      return
    self.connection.execute(
      """UPDATE segment_metadata SET status = 'complete', end_mono_ns = ?,
         end_wall_ms = ?, close_reason = ?""",
      (end.mono_ns, end.wall_ms, reason),
    )
    self.connection.commit()
    self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    self.connection.close()
    self.connection = None

    entry = self.manifest["segments"][-1]
    entry.update({
      "status": "complete",
      "end_mono_ns": end.mono_ns,
      "end_wall_ms": end.wall_ms,
      "close_reason": reason,
      "size_bytes": self.database_path.stat().st_size,
    })
    self._write_manifest(end.wall_ms)

  def _rotate_if_needed(self, clock: SegmentClock) -> None:
    if clock.mono_ns - self.segment_start_mono_ns < self.segment_duration_ns:
      return
    self._close_segment(clock, "rotation")
    self._open_segment(clock)

  def finalize_active_segment(self, clock: SegmentClock, reason: str) -> None:
    """Commit, checkpoint, and close the current file without ending the recorder object."""
    if self.closed:
      raise RuntimeError("telemetry storage is closed")
    self._close_segment(clock, reason)

  def resume(self, clock: SegmentClock) -> None:
    """Start a new segment after an ignition-off pause."""
    if self.closed:
      raise RuntimeError("telemetry storage is closed")
    if self.connection is None:
      self._open_segment(clock)

  def write_sample(self, sample: dict[str, Any], clock: SegmentClock) -> None:
    if self.closed or self.connection is None:
      raise RuntimeError("telemetry storage is closed")
    self._rotate_if_needed(clock)
    row = dict.fromkeys(SAMPLE_COLUMNS)
    row.update(sample)
    row["mono_time_ns"] = clock.mono_ns
    row["wall_time_ms"] = clock.wall_ms
    self.connection.execute(INSERT_SAMPLE_SQL, tuple(row[column] for column in SAMPLE_COLUMNS))
    if clock.mono_ns - self.last_commit_mono_ns >= self.commit_interval_ns:
      self.connection.commit()
      self.last_commit_mono_ns = clock.mono_ns

  def write_event(self, clock: SegmentClock, kind: str, value: str | None = None,
                  severity: str | None = None, details: dict[str, Any] | None = None) -> None:
    if self.connection is None:
      raise RuntimeError("telemetry storage is closed")
    self.connection.execute(
      """INSERT INTO events (mono_time_ns, wall_time_ms, kind, value, severity, details_json)
         VALUES (?, ?, ?, ?, ?, ?)""",
      (clock.mono_ns, clock.wall_ms, kind, value, severity,
       json.dumps(details, separators=(",", ":")) if details else None),
    )

  def write_model_path(self, clock: SegmentClock, frame_id: int,
                       x: list[float], y: list[float], z: list[float]) -> None:
    if self.connection is None:
      raise RuntimeError("telemetry storage is closed")
    self.connection.execute(
      """INSERT OR REPLACE INTO model_paths (mono_time_ns, frame_id, x_json, y_json, z_json)
         VALUES (?, ?, ?, ?, ?)""",
      (clock.mono_ns, frame_id, json.dumps(x, separators=(",", ":")),
       json.dumps(y, separators=(",", ":")), json.dumps(z, separators=(",", ":"))),
    )

  def associate_video(self, clock: SegmentClock, route: str, segment_num: int,
                      encode_time_ns: int | None = None) -> None:
    if self.connection is None or not route or segment_num < 0:
      return
    relative_path = f"{route}--{segment_num}/fcamera.hevc"
    self.connection.execute(
      """INSERT INTO video_segments
         (route, segment_num, relative_path, first_mono_ns, last_mono_ns, first_encode_time_ns, last_encode_time_ns)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(route, segment_num) DO UPDATE SET last_mono_ns = excluded.last_mono_ns,
         last_encode_time_ns = excluded.last_encode_time_ns""",
      (route, segment_num, relative_path, clock.mono_ns, clock.mono_ns, encode_time_ns, encode_time_ns),
    )
    identity = (route, segment_num)
    manifest_entry = next((item for item in self.manifest["video_segments"]
                           if (item["route"], item["segment_num"]) == identity), None)
    if manifest_entry is None:
      manifest_entry = {
        "route": route,
        "segment_num": segment_num,
        "source_relative_path": relative_path,
        "first_mono_ns": clock.mono_ns,
        "last_mono_ns": clock.mono_ns,
      }
      self.manifest["video_segments"].append(manifest_entry)
      if not self.metadata.get("openpilot_route"):
        self.metadata["openpilot_route"] = route
        atomic_write_json(self.drive_directory / "metadata.json", self.metadata)
    else:
      manifest_entry["last_mono_ns"] = clock.mono_ns

  def close(self, clock: SegmentClock | None = None, reason: str = "shutdown") -> None:
    if self.closed:
      return
    clock = clock or SegmentClock(time.monotonic_ns(), time.time_ns() // 1_000_000)
    self._close_segment(clock, reason)
    self.closed = True

  def __enter__(self) -> TelemetryStorage:
    return self

  def __exit__(self, exc_type, exc_value, traceback) -> None:
    self.close(reason="exception" if exc_type else "shutdown")
