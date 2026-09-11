#!/usr/bin/env python3
"""Build a review-only CAN fingerprint candidate from complete Corolla rlogs."""

from __future__ import annotations

import argparse
import bz2
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


VIN_QUERY_ADDRS = {0x7DF, 0x7E0, 0x7E8}
MIN_CAPTURE_FRAMES = 1000


@dataclass(frozen=True)
class Candidate:
  fingerprint: dict[int, int]
  frame_count: int
  new_addresses_last_log: tuple[int, ...]


def build_candidate(logs: Iterable[Iterable[object]], bus: int) -> Candidate:
  counts: Counter[int] = Counter()
  lengths: dict[int, set[int]] = {}
  new_last: set[int] = set()
  saw_log = False

  for log in logs:
    saw_log = True
    before = set(counts)
    for event in log:
      if event.which() != "can":
        continue
      for msg in event.can:
        address = int(msg.address)
        if int(msg.src) != bus or address >= 0x800 or address in VIN_QUERY_ADDRS:
          continue
        counts[address] += 1
        lengths.setdefault(address, set()).add(len(msg.dat))
    new_last = set(counts) - before

  if not saw_log or sum(counts.values()) < MIN_CAPTURE_FRAMES:
    raise ValueError("capture is too short for a fingerprint candidate; use complete rlogs")

  unstable = {address: sorted(dlcs) for address, dlcs in lengths.items() if len(dlcs) != 1}
  if unstable:
    details = ", ".join(f"{address:#x}={dlcs}" for address, dlcs in sorted(unstable.items()))
    raise ValueError(f"address DLC changed within the capture: {details}")

  fingerprint = {address: next(iter(lengths[address])) for address in sorted(lengths)}
  return Candidate(fingerprint, sum(counts.values()), tuple(sorted(new_last)))


def read_rlog(path: str):
  import capnp
  import zstandard as zstd
  from cereal import log as capnp_log

  data = Path(path).read_bytes()
  if data.startswith(b"BZh9"):
    data = bz2.decompress(data)
  elif data.startswith(b"\x28\xB5\x2F\xFD"):
    with zstd.ZstdDecompressor().stream_reader(data) as reader:
      data = reader.read()
  try:
    yield from capnp_log.Event.read_multiple_bytes(data)
  except capnp.KjException as exc:
    raise ValueError(f"corrupt rlog {path}: {exc}") from exc


def render(candidate: Candidate, bus: int, log_count: int) -> str:
  lines = [
    "# REVIEW-ONLY candidate; this tool never edits fingerprints.py",
    f"# bus {bus}; {len(candidate.fingerprint)} addresses; {candidate.frame_count} frames; {log_count} rlogs",
  ]
  if candidate.new_addresses_last_log:
    values = ", ".join(hex(address) for address in candidate.new_addresses_last_log)
    lines.append(f"# NOT CONVERGED: last rlog added {values}")
  else:
    lines.append("# last rlog added no addresses; still review uniqueness before installation")
  lines.append("CAR.TOYOTA_COROLLA_TSS3: [{")
  lines.extend(f"  {address:#05x}: {dlc}," for address, dlc in candidate.fingerprint.items())
  lines.append("}],")
  return "\n".join(lines)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("rlogs", nargs="+", help="complete rlog.zst/rlog.bz2 files; qlogs are rejected as too short")
  parser.add_argument("--bus", type=int, default=0, help="logical bus used for legacy fingerprinting (default: 0)")
  args = parser.parse_args()

  try:
    candidate = build_candidate((read_rlog(path) for path in args.rlogs), args.bus)
  except (OSError, ValueError, ImportError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 1
  print(render(candidate, args.bus, len(args.rlogs)))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
