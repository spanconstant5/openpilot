"""Read-only helpers for finding and summarizing loggerd rlogs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RLOG_FILENAMES = ("rlog.zst", "rlog.bz2", "rlog")
MAX_DISTINCT_PAYLOADS = 256


@dataclass(frozen=True)
class RlogSegment:
  route: str
  segment: int
  path: Path
  mtime_ns: int
  size: int


def _parse_segment(path: Path) -> tuple[str, int] | None:
  route, separator, segment_text = path.parent.name.rpartition("--")
  if not separator or not route:
    return None
  try:
    segment = int(segment_text)
  except ValueError:
    return None
  return route, segment


def discover_rlogs(root: Path) -> list[RlogSegment]:
  """Return loggerd route segments without modifying or opening the log files."""
  found: list[RlogSegment] = []
  if not root.is_dir():
    return found

  for filename in RLOG_FILENAMES:
    for path in root.glob(f"*/{filename}"):
      if not path.is_file() or path.is_symlink():
        continue
      parsed = _parse_segment(path)
      if parsed is None:
        continue
      stat = path.stat()
      found.append(RlogSegment(*parsed, path=path, mtime_ns=stat.st_mtime_ns, size=stat.st_size))
  return sorted(found, key=lambda item: (item.mtime_ns, item.route, item.segment), reverse=True)


def latest_routes(segments: Iterable[RlogSegment], count: int) -> list[tuple[str, list[RlogSegment]]]:
  grouped: dict[str, list[RlogSegment]] = {}
  for item in segments:
    grouped.setdefault(item.route, []).append(item)

  routes = sorted(grouped.items(), key=lambda pair: max(item.mtime_ns for item in pair[1]), reverse=True)
  return [(route, sorted(items, key=lambda item: item.segment)) for route, items in routes[:count]]


@dataclass
class _StreamStats:
  frames: int = 0
  transitions: int = 0
  first_mono_ns: int | None = None
  last_mono_ns: int | None = None
  last_payload: bytes | None = None
  change_mask: bytearray = field(default_factory=bytearray)
  distinct_payloads: set[bytes] = field(default_factory=set)
  distinct_payloads_capped: bool = False

  def add(self, payload: bytes, mono_ns: int) -> None:
    self.frames += 1
    if self.first_mono_ns is None:
      self.first_mono_ns = mono_ns
    self.last_mono_ns = mono_ns

    if len(self.distinct_payloads) < MAX_DISTINCT_PAYLOADS:
      self.distinct_payloads.add(payload)
    elif payload not in self.distinct_payloads:
      self.distinct_payloads_capped = True

    if self.last_payload is not None and self.last_payload != payload:
      self.transitions += 1
      if len(self.change_mask) < len(payload):
        self.change_mask.extend(b"\x00" * (len(payload) - len(self.change_mask)))
      for index, (before, after) in enumerate(zip(self.last_payload, payload, strict=True)):
        self.change_mask[index] |= before ^ after
    self.last_payload = payload


def scan_can_messages(messages: Iterable[Any]) -> dict[str, Any]:
  """Build bounded per-stream change statistics from decoded cereal events."""
  streams: dict[tuple[int, int, int], _StreamStats] = {}
  can_events = 0
  physical_frames = 0
  ignored_tx_receipts = 0
  invalid_events = 0

  for message in messages:
    try:
      if message.which() != "can":
        continue
      mono_ns = int(message.logMonoTime)
      frames = message.can
    except Exception:
      invalid_events += 1
      continue

    can_events += 1
    for frame in frames:
      try:
        bus = int(frame.src)
        if bus >= 0x80:
          ignored_tx_receipts += 1
          continue
        address = int(frame.address)
        payload = bytes(frame.dat)
      except Exception:
        invalid_events += 1
        continue

      physical_frames += 1
      streams.setdefault((bus, address, len(payload)), _StreamStats()).add(payload, mono_ns)

  rows = []
  for (bus, address, length), stats in streams.items():
    rows.append({
      "bus": bus,
      "address": address,
      "address_hex": f"0x{address:X}",
      "length": length,
      "frames": stats.frames,
      "transitions": stats.transitions,
      "distinct_payloads": len(stats.distinct_payloads),
      "distinct_payloads_capped": stats.distinct_payloads_capped,
      "changed_bits_mask_hex": bytes(stats.change_mask).hex().ljust(length * 2, "0"),
      "first_mono_time_ns": stats.first_mono_ns,
      "last_mono_time_ns": stats.last_mono_ns,
    })

  rows.sort(key=lambda row: (-row["transitions"], -row["distinct_payloads"], row["bus"], row["address"]))
  return {
    "format": "tss3-rlog-can-inventory-v1",
    "can_events": can_events,
    "physical_frames": physical_frames,
    "ignored_tx_receipts": ignored_tx_receipts,
    "invalid_events": invalid_events,
    "streams": rows,
  }
