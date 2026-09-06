#!/usr/bin/env python3
"""SSH-friendly, read-only access to openpilot's existing loggerd rlogs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .rlogs import RlogSegment, discover_rlogs, latest_routes, scan_can_messages


DEFAULT_LOG_ROOT = "/data/media/0/realdata"


def _human_bytes(value: int) -> str:
  amount = float(value)
  for unit in ("B", "KiB", "MiB", "GiB"):
    if amount < 1024 or unit == "GiB":
      return f"{amount:.1f} {unit}"
    amount /= 1024
  return f"{amount:.1f} GiB"


def _root(args: argparse.Namespace) -> Path:
  return Path(args.root).expanduser()


def _selected(args: argparse.Namespace) -> list[tuple[str, list[RlogSegment]]]:
  return latest_routes(discover_rlogs(_root(args)), args.latest)


def command_status(args: argparse.Namespace) -> int:
  root = _root(args)
  routes = _selected(args)
  print("Capture source: openpilot loggerd rlog (no extra recorder process)")
  print(f"Log root: {root}")
  if not routes:
    print("No completed or in-progress rlog segments found.")
    return 1

  route, segments = routes[0]
  print(f"Latest route: {route}")
  print(f"Segments found: {len(segments)} ({_human_bytes(sum(item.size for item in segments))})")
  print("Run this after the drive is over: python -m openpilot.system.tss3_cruise_recorder.control list")
  return 0


def command_list(args: argparse.Namespace) -> int:
  routes = _selected(args)
  if not routes:
    print(f"No rlog segments found in {_root(args)}")
    return 1

  for route, segments in routes:
    if not args.paths_only:
      print(f"Route {route}: {len(segments)} segment(s), {_human_bytes(sum(item.size for item in segments))}")
    for item in segments:
      print(item.path if args.paths_only else f"  segment {item.segment:>3}: {_human_bytes(item.size):>10}  {item.path}")
  return 0


def _paths_for_summary(args: argparse.Namespace) -> list[Path]:
  if args.paths:
    return [Path(value).expanduser() for value in args.paths]
  routes = _selected(args)
  return [item.path for _route, segments in routes for item in segments]


def _read_rlogs(paths: list[Path]):
  """Decode local rlogs without importing the network-aware LogReader toolchain."""
  import bz2

  import zstandard as zstd

  from openpilot.cereal import log as capnp_log

  for path in paths:
    if path.suffix == ".zst":
      with path.open("rb") as compressed, zstd.ZstdDecompressor().stream_reader(compressed) as reader:
        data = reader.read()
    elif path.suffix == ".bz2":
      data = bz2.decompress(path.read_bytes())
    else:
      data = path.read_bytes()
    yield from capnp_log.Event.read_multiple_bytes(data)


def command_summary(args: argparse.Namespace) -> int:
  paths = _paths_for_summary(args)
  if not paths:
    print(f"No rlog segments found in {_root(args)}")
    return 1
  missing = [path for path in paths if not path.is_file()]
  if missing:
    for path in missing:
      print(f"Missing rlog: {path}")
    return 1

  report = scan_can_messages(_read_rlogs(paths))
  report["files"] = [str(path) for path in paths]

  if args.json:
    output = Path(args.json).expanduser()
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")

  print(f"Files: {len(paths)}")
  print(f"Physical CAN frames: {report['physical_frames']}")
  print(f"CAN events: {report['can_events']}; ignored TX receipts: {report['ignored_tx_receipts']}")
  print(f"Distinct bus/address/length streams: {len(report['streams'])}")
  if report["invalid_events"]:
    print(f"Unreadable events/frames: {report['invalid_events']}")
  print(f"Most-changing streams (top {args.top}):")
  for row in report["streams"][:args.top]:
    capped = "+" if row["distinct_payloads_capped"] else ""
    description = f"bus {row['bus']}, {row['address_hex']}, {row['length']} bytes: "
    description += f"{row['frames']} frames, {row['transitions']} transitions, "
    description += f"{row['distinct_payloads']}{capped} payloads, mask {row['changed_bits_mask_hex']}"
    print(f"  {description}")
  return 0


def _add_common(parser: argparse.ArgumentParser, *, latest: int = 1) -> None:
  parser.add_argument("--root", default=os.environ.get("LOG_ROOT", DEFAULT_LOG_ROOT), help="loggerd realdata directory")
  parser.add_argument("--latest", type=int, default=latest, choices=range(1, 101), metavar="N", help="number of newest routes")


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Find and inspect loggerd rlogs for passive Toyota TSS3 research")
  commands = parser.add_subparsers(dest="command", required=True)

  status = commands.add_parser("status", help="show whether loggerd rlogs are available")
  _add_common(status)
  status.set_defaults(function=command_status)

  listing = commands.add_parser("list", help="list rlogs for recent routes")
  _add_common(listing, latest=3)
  listing.add_argument("--paths-only", action="store_true", help="print one copyable rlog path per line")
  listing.set_defaults(function=command_list)

  summary = commands.add_parser("summary", help="manually scan local rlogs; run only while parked/off-road")
  _add_common(summary)
  summary.add_argument("paths", nargs="*", help="specific rlogs; defaults to the newest route")
  summary.add_argument("--top", type=int, default=50, choices=range(1, 1001), metavar="N", help="number of streams to print")
  summary.add_argument("--json", metavar="PATH", help="also write the complete inventory as JSON")
  summary.set_defaults(function=command_summary)
  return parser


def main() -> int:
  args = build_parser().parse_args()
  return int(args.function(args))


if __name__ == "__main__":
  raise SystemExit(main())
