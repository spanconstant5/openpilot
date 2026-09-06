"""Bounded, private JSONL storage for passive CAN evidence."""

from __future__ import annotations

import json
import gzip
import io
import os
import shutil
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, TextIO
from uuid import uuid4


MARKER_TEXT = "toyota-tss3-passive-cruise-recorder-v1\n"
MARKER_NAME = ".passive-recorder-root"
DEFAULT_MAX_PART_BYTES = 8 * 1024 * 1024
DEFAULT_ROTATE_NS = 30 * 60 * 1_000_000_000
DEFAULT_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
DEFAULT_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


def utc_text(wall_time_ns: int) -> str:
  return datetime.fromtimestamp(wall_time_ns / 1_000_000_000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_log_root() -> Path:
  return Path(os.environ.get("TSS3_CRUISE_LOG_ROOT", "/data/tss3-cruise-probe/logs"))


def default_status_path() -> Path:
  return Path(os.environ.get("TSS3_CRUISE_STATUS_PATH", "/dev/shm/tss3_cruise_probe_status.json"))


def prepare_log_root(root: Path) -> Path:
  if root.exists() and root.is_symlink():
    raise RuntimeError(f"refusing symlink log root: {root}")
  root.mkdir(parents=True, exist_ok=True, mode=0o700)
  os.chmod(root, 0o700)
  marker = root / MARKER_NAME
  if marker.exists():
    if marker.is_symlink() or marker.read_text(encoding="ascii") != MARKER_TEXT:
      raise RuntimeError(f"invalid recorder marker: {marker}")
  else:
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
      stream.write(MARKER_TEXT)
      stream.flush()
      os.fsync(stream.fileno())
  return root


def _completed_files(root: Path) -> list[Path]:
  return sorted(
    (path for pattern in ("*.jsonl", "*.jsonl.gz") for path in root.glob(pattern) if path.is_file() and not path.is_symlink()),
    key=lambda path: (path.stat().st_mtime_ns, path.name),
  )


def archive_size(root: Path) -> int:
  if not root.exists() or root.is_symlink():
    return 0
  return sum(
    path.stat().st_size
    for pattern in ("*.jsonl", "*.jsonl.gz", "*.active")
    for path in root.glob(pattern)
    if path.is_file() and not path.is_symlink()
  )


def recover_active_files(root: Path) -> list[Path]:
  prepare_log_root(root)
  recovered: list[Path] = []
  for active in sorted(root.glob("*.active")):
    if not active.is_file() or active.is_symlink():
      continue
    suffix = ".recovered.jsonl.gz" if active.name.endswith(".jsonl.gz.active") else ".recovered.jsonl"
    destination = active.with_suffix(suffix)
    if destination.exists():
      destination = active.with_name(f"{active.stem}-{uuid4().hex[:8]}{suffix}")
    os.replace(active, destination)
    recovered.append(destination)
  return recovered


def prune_completed(root: Path, max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
                    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
                    free_space: Callable[[Path], int] | None = None) -> list[Path]:
  prepare_log_root(root)
  free_space = free_space or (lambda path: shutil.disk_usage(path).free)
  files = _completed_files(root)
  total = sum(path.stat().st_size for path in files)
  removed: list[Path] = []
  while files and (total > max_archive_bytes or free_space(root) < min_free_bytes):
    oldest = files.pop(0)
    size = oldest.stat().st_size
    oldest.unlink()
    total -= size
    removed.append(oldest)
  if free_space(root) < min_free_bytes:
    raise OSError(f"recorder free-space floor not met at {root}")
  return removed


class StatusStore:
  def __init__(self, path: Path | None = None):
    self.path = path or default_status_path()

  def write(self, value: dict[str, object]) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
      with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
      os.replace(temporary, self.path)
      os.chmod(self.path, 0o600)
    finally:
      temporary.unlink(missing_ok=True)


class ArchiveWriter:
  def __init__(self, root: Path | None = None, *, max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
               rotate_ns: int = DEFAULT_ROTATE_NS, max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
               min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
               free_space: Callable[[Path], int] | None = None, start_mono_ns: int,
               start_wall_ns: int, compressed: bool = False, metadata: dict[str, object] | None = None):
    self.root = prepare_log_root(root or default_log_root())
    self.max_part_bytes = max_part_bytes
    self.rotate_ns = rotate_ns
    self.max_archive_bytes = max_archive_bytes
    self.min_free_bytes = min_free_bytes
    self.free_space = free_space
    self.compressed = compressed
    self.metadata = metadata or {}
    recover_active_files(self.root)
    prune_completed(self.root, self.max_archive_bytes, self.min_free_bytes, self.free_space)

    timestamp = datetime.fromtimestamp(start_wall_ns / 1_000_000_000, tz=UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    self.session_id = f"{timestamp}-{uuid4().hex[:12]}"
    self.part = -1
    self.stream: TextIO | None = None
    self.raw_stream: BinaryIO | None = None
    self.active_path: Path | None = None
    self.completed_paths: list[Path] = []
    self.part_started_ns = start_mono_ns
    self.bytes_written = 0
    self.closed = False
    self.last_flush_ns = start_mono_ns
    self.last_space_check_ns = start_mono_ns
    self._open_part(start_mono_ns, start_wall_ns)

  def _open_part(self, mono_time_ns: int, wall_time_ns: int) -> None:
    self.part += 1
    self.part_started_ns = mono_time_ns
    self.bytes_written = 0
    suffix = ".jsonl.gz.active" if self.compressed else ".active"
    self.active_path = self.root / f"session-{self.session_id}-part-{self.part:03d}{suffix}"
    descriptor = os.open(self.active_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if self.compressed:
      self.raw_stream = os.fdopen(descriptor, "wb", buffering=64 * 1024)
      compressed_stream = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw_stream, compresslevel=1, mtime=0)
      self.stream = io.TextIOWrapper(compressed_stream, encoding="utf-8", newline="\n")
    else:
      self.stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n", buffering=64 * 1024)
    self._write_line({
      "type": "session_start" if self.part == 0 else "part_start",
      "schema_version": 1,
      "session_id": self.session_id,
      "part": self.part,
      "mode": "receive_only",
      "mono_time_ns": mono_time_ns,
      "wall_time_ns": wall_time_ns,
      "utc": utc_text(wall_time_ns),
      "capture": self.metadata,
    })

  def _write_line(self, record: dict[str, object]) -> None:
    if self.stream is None:
      raise RuntimeError("archive part is not open")
    line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
    self.stream.write(line)
    self.bytes_written += len(line.encode("utf-8"))

  def _finish_part(self, mono_time_ns: int, wall_time_ns: int, reason: str) -> None:
    if self.stream is None or self.active_path is None:
      return
    self._write_line({
      "type": "part_end",
      "session_id": self.session_id,
      "part": self.part,
      "reason": reason,
      "mono_time_ns": mono_time_ns,
      "wall_time_ns": wall_time_ns,
      "utc": utc_text(wall_time_ns),
    })
    self.stream.flush()
    if self.raw_stream is not None:
      self.stream.close()  # Finish gzip footer before syncing the backing file.
      self.raw_stream.flush()
      os.fsync(self.raw_stream.fileno())
      self.raw_stream.close()
      self.raw_stream = None
    else:
      os.fsync(self.stream.fileno())
      self.stream.close()
    self.stream = None
    completed = self.active_path.with_suffix("") if self.compressed else self.active_path.with_suffix(".jsonl")
    os.replace(self.active_path, completed)
    self.active_path = None
    self.completed_paths.append(completed)
    prune_completed(self.root, self.max_archive_bytes, self.min_free_bytes, self.free_space)

  def write(self, records: Iterable[dict[str, object]], mono_time_ns: int,
            wall_time_ns: int, flush: bool = False) -> None:
    if self.closed:
      raise RuntimeError("archive is closed")
    # Limits apply to uncompressed bytes, so compressed parts cannot grow unbounded.
    for record in records:
      line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
      size = len(line.encode("utf-8"))
      if self.bytes_written + size >= self.max_part_bytes or mono_time_ns - self.part_started_ns >= self.rotate_ns:
        self._finish_part(mono_time_ns, wall_time_ns, "rotation")
        self._open_part(mono_time_ns, wall_time_ns)
      if self.stream is None:
        raise RuntimeError("archive part is not open")
      self.stream.write(line)
      self.bytes_written += size
    self.maintain(mono_time_ns, flush)

  def maintain(self, mono_time_ns: int, flush: bool = False) -> None:
    if (flush or mono_time_ns - self.last_flush_ns >= 1_000_000_000) and self.stream is not None:
      self.stream.flush()
      if self.raw_stream is not None:
        self.raw_stream.flush()
      self.last_flush_ns = mono_time_ns
    if mono_time_ns - self.last_space_check_ns >= 5_000_000_000:
      prune_completed(self.root, self.max_archive_bytes, self.min_free_bytes, self.free_space)
      self.last_space_check_ns = mono_time_ns

  def close(self, mono_time_ns: int, wall_time_ns: int, reason: str = "shutdown") -> None:
    if self.closed:
      return
    self.closed = True
    self._finish_part(mono_time_ns, wall_time_ns, reason)

  def abort(self) -> None:
    """Close a failed active stream without attempting more writes or renames."""
    self.closed = True
    if self.stream is not None:
      try:
        self.stream.close()
      except OSError:
        pass
      finally:
        self.stream = None
    if self.raw_stream is not None:
      try:
        self.raw_stream.close()
      except OSError:
        pass
      finally:
        self.raw_stream = None
