from __future__ import annotations

import bisect
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1
MARKER_KINDS = {"driver_distraction", "brake_override", "steering_override", "engagement", "alert"}


@dataclass(frozen=True)
class Event:
  mono_time_ns: int
  wall_time_ms: int
  kind: str
  value: str | None
  severity: str | None
  details: dict[str, Any] | None


@dataclass(frozen=True)
class VideoSegment:
  route: str
  segment_num: int
  source_relative_path: str
  first_mono_ns: int
  last_mono_ns: int
  local_path: Path | None


@dataclass(frozen=True)
class DriveSummary:
  start_wall_ms: int
  duration_seconds: float
  distance_meters: float
  average_speed_mps: float
  maximum_speed_mps: float
  distracted_seconds: float
  engaged_seconds: float
  driver_override_seconds: float
  maximum_steering_angle_deg: float
  sample_count: int
  gps_fix_percent: float
  event_counts: dict[str, int]
  gps_route: list[tuple[float, float]]


def _read_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
  try:
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY mono_time_ns")
  except sqlite3.DatabaseError:
    return []
  columns = [description[0] for description in cursor.description]
  return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _resolve_video(drive_directory: Path, relative_path: str) -> Path | None:
  candidates = (
    drive_directory / "video" / relative_path,
    drive_directory / relative_path,
    drive_directory.parent / "realdata" / relative_path,
  )
  return next((candidate for candidate in candidates if candidate.is_file()), None)


class DriveData:
  def __init__(self, drive_directory: Path, manifest: dict[str, Any], metadata: dict[str, Any], samples: list[dict[str, Any]],
               events: list[Event], videos: list[VideoSegment]):
    self.drive_directory = drive_directory
    self.manifest = manifest
    self.metadata = metadata
    self.samples = sorted(samples, key=lambda sample: int(sample["mono_time_ns"]))
    self.sample_times = [int(sample["mono_time_ns"]) for sample in self.samples]
    self.events = sorted(events, key=lambda event: event.mono_time_ns)
    self.videos = sorted(videos, key=lambda video: video.first_mono_ns)
    self.start_mono_ns = self.sample_times[0] if self.sample_times else 0
    self.end_mono_ns = self.sample_times[-1] if self.sample_times else 0

  @classmethod
  def open(cls, drive_directory: Path | str) -> DriveData:
    drive_directory = Path(drive_directory)
    manifest_path = drive_directory / "manifest.json"
    if not manifest_path.is_file():
      raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_path = drive_directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    version = int(manifest.get("schema_version", 0))
    if version < 1 or version > SUPPORTED_SCHEMA_VERSION:
      raise ValueError(f"unsupported telemetry schema version: {version}")

    samples: list[dict[str, Any]] = []
    events: list[Event] = []
    for segment in manifest.get("segments", []):
      if segment.get("status") != "complete":
        continue
      database_path = drive_directory / str(segment.get("filename", ""))
      if not database_path.is_file():
        continue
      with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
        samples.extend(_read_rows(connection, "samples"))
        for row in _read_rows(connection, "events"):
          details = json.loads(row["details_json"]) if row.get("details_json") else None
          events.append(Event(int(row["mono_time_ns"]), int(row["wall_time_ms"]), str(row["kind"]),
                              row.get("value"), row.get("severity"), details))

    videos = []
    for item in manifest.get("video_segments", []):
      relative_path = str(item.get("source_relative_path", ""))
      videos.append(VideoSegment(
        route=str(item.get("route", "")),
        segment_num=int(item.get("segment_num", -1)),
        source_relative_path=relative_path,
        first_mono_ns=int(item.get("first_mono_ns", 0)),
        last_mono_ns=int(item.get("last_mono_ns", item.get("first_mono_ns", 0))),
        local_path=_resolve_video(drive_directory, relative_path),
      ))
    return cls(drive_directory, manifest, metadata, samples, events, videos)

  @property
  def duration_seconds(self) -> float:
    return max(0.0, (self.end_mono_ns - self.start_mono_ns) / 1e9)

  def nearest_sample(self, mono_time_ns: int) -> dict[str, Any] | None:
    if not self.samples:
      return None
    index = bisect.bisect_left(self.sample_times, mono_time_ns)
    if index == 0:
      return self.samples[0]
    if index == len(self.samples):
      return self.samples[-1]
    before = self.sample_times[index - 1]
    after = self.sample_times[index]
    return self.samples[index - 1 if mono_time_ns - before <= after - mono_time_ns else index]

  def sample_at_seconds(self, seconds: float) -> dict[str, Any] | None:
    return self.nearest_sample(self.start_mono_ns + int(max(0.0, seconds) * 1e9))

  def video_for_mono_time(self, mono_time_ns: int) -> VideoSegment | None:
    if not self.videos:
      return None
    starts = [video.first_mono_ns for video in self.videos]
    index = bisect.bisect_right(starts, mono_time_ns) - 1
    return self.videos[max(0, index)]

  def markers(self) -> list[Event]:
    return [event for event in self.events if event.kind in MARKER_KINDS]

  def summary(self) -> DriveSummary:
    if not self.samples:
      return DriveSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, {}, [])
    distance = 0.0
    distracted = 0.0
    engaged = 0.0
    driver_override = 0.0
    gps_route: list[tuple[float, float]] = []
    maximum_speed = max(float(sample.get("v_ego_mps") or 0.0) for sample in self.samples)
    maximum_steering_angle = max(abs(float(sample.get("steering_angle_deg") or 0.0)) for sample in self.samples)
    for previous, current in zip(self.samples, self.samples[1:], strict=False):
      dt = (int(current["mono_time_ns"]) - int(previous["mono_time_ns"])) / 1e9
      if 0.0 < dt <= 1.0:
        previous_speed = float(previous.get("v_ego_mps") or 0.0)
        current_speed = float(current.get("v_ego_mps") or 0.0)
        distance += (previous_speed + current_speed) * 0.5 * dt
        if previous.get("driver_distracted"):
          distracted += dt
        if previous.get("engaged"):
          engaged += dt
        if previous.get("steering_pressed") or previous.get("gas_pressed") or previous.get("brake_pressed"):
          driver_override += dt
    for sample in self.samples:
      if sample.get("gps_has_fix") and sample.get("gps_latitude") is not None and sample.get("gps_longitude") is not None:
        point = (float(sample["gps_latitude"]), float(sample["gps_longitude"]))
        if not gps_route or point != gps_route[-1]:
          gps_route.append(point)
    duration = self.duration_seconds
    gps_fix_samples = sum(bool(sample.get("gps_has_fix")) for sample in self.samples)
    event_counts: dict[str, int] = {}
    for event in self.events:
      value = str(event.value).strip().lower() if event.value is not None else ""
      if event.kind == "alert" or value in ("", "1", "true", "on", "active"):
        event_counts[event.kind] = event_counts.get(event.kind, 0) + 1
    return DriveSummary(
      start_wall_ms=int(self.samples[0].get("wall_time_ms") or 0),
      duration_seconds=duration,
      distance_meters=distance,
      average_speed_mps=distance / duration if duration > 0 else 0.0,
      maximum_speed_mps=maximum_speed,
      distracted_seconds=distracted,
      engaged_seconds=engaged,
      driver_override_seconds=driver_override,
      maximum_steering_angle_deg=maximum_steering_angle,
      sample_count=len(self.samples),
      gps_fix_percent=gps_fix_samples / len(self.samples) * 100.0,
      event_counts=event_counts,
      gps_route=gps_route,
    )
