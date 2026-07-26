from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class CopyItem:
  remote_path: PurePosixPath
  local_relative_path: Path
  expected_size: int | None
  kind: str


def safe_relative_posix(value: str) -> PurePosixPath:
  path = PurePosixPath(value)
  if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
    raise ValueError(f"unsafe relative path: {value!r}")
  return path


def select_completed_files(manifest: dict[str, Any], remote_drive: PurePosixPath) -> list[CopyItem]:
  selected: list[CopyItem] = []
  seen: set[tuple[str, PurePosixPath]] = set()
  for segment in manifest.get("segments", []):
    if segment.get("status") != "complete":
      continue
    filename = safe_relative_posix(str(segment.get("filename", "")))
    if len(filename.parts) != 1 or filename.suffix != ".db":
      raise ValueError(f"invalid telemetry segment filename: {filename}")
    size = segment.get("size_bytes")
    item = CopyItem(remote_drive / filename, Path(*filename.parts), int(size) if size is not None else None, "telemetry")
    if (item.kind, item.remote_path) not in seen:
      selected.append(item)
      seen.add((item.kind, item.remote_path))

  for video in manifest.get("video_segments", []):
    relative = safe_relative_posix(str(video.get("source_relative_path", "")))
    if relative.name != "fcamera.hevc":
      raise ValueError(f"unexpected video path: {relative}")
    remote = PurePosixPath("/data/media/0/realdata") / relative
    item = CopyItem(remote, Path("video", *relative.parts), None, "video")
    if (item.kind, item.remote_path) not in seen:
      selected.append(item)
      seen.add((item.kind, item.remote_path))
  return selected


def needs_copy(destination: Path, expected_size: int) -> bool:
  return not destination.is_file() or destination.stat().st_size != expected_size
