#!/usr/bin/env python3
"""SSH-friendly status and log inspection commands."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from .storage import archive_size, default_log_root, default_status_path


def _human_bytes(value: int) -> str:
  amount = float(value)
  for unit in ("B", "KiB", "MiB", "GiB"):
    if amount < 1024 or unit == "GiB":
      return f"{amount:.1f} {unit}"
    amount /= 1024
  return f"{amount:.1f} GiB"


def _log_files(root: Path, include_active: bool = False) -> list[Path]:
  patterns = ("*.jsonl", "*.active") if include_active else ("*.jsonl",)
  return sorted(
    (path for pattern in patterns for path in root.glob(pattern) if path.is_file() and not path.is_symlink()),
    key=lambda path: (path.stat().st_mtime_ns, path.name),
  )


def command_status(_args: argparse.Namespace) -> int:
  path = default_status_path()
  if not path.is_file():
    print("No recorder status exists yet. Complete an on-road startup first.")
    return 1
  try:
    value = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    print(f"Recorder status is unreadable: {error}")
    return 1

  updated_ns = value.get("updated_wall_time_ns")
  age_seconds = None
  if isinstance(updated_ns, int):
    age_seconds = max(0.0, (time.time_ns() - updated_ns) / 1_000_000_000)
  print(f"State: {value.get('state', 'unknown')} ({value.get('mode', 'unknown')})")
  print(f"Status age: {age_seconds:.1f} seconds" if age_seconds is not None else "Status age: unknown")
  print(f"Buses seen: {value.get('discovered_buses', [])}")
  print(f"Button press/release edges: {value.get('press_edges', 0)}/{value.get('release_edges', 0)}")
  print(f"Buttons: {value.get('button_presses', {})}")
  print(f"Archive: {_human_bytes(int(value.get('archive_bytes', 0)))} at {value.get('log_root', default_log_root())}")
  print(f"Active file: {value.get('active_file') or 'none'}")
  print(f"Last error: {value.get('last_error') or 'none'}")
  return 0


def command_list(args: argparse.Namespace) -> int:
  root = default_log_root()
  files = _log_files(root, args.include_active) if root.exists() else []
  if not files:
    print(f"No {'active or completed' if args.include_active else 'completed'} logs in {root}")
    return 0
  for path in files:
    print(f"{_human_bytes(path.stat().st_size):>10}  {path}")
  print(f"Total archive: {_human_bytes(archive_size(root))}")
  return 0


def _summarize(paths: list[Path]) -> tuple[Counter[str], Counter[str], int]:
  reasons: Counter[str] = Counter()
  buttons: Counter[str] = Counter()
  invalid_lines = 0
  for path in paths:
    try:
      with path.open(encoding="utf-8") as stream:
        for line in stream:
          try:
            record = json.loads(line)
          except json.JSONDecodeError:
            invalid_lines += 1
            continue
          if record.get("type") != "can_frame":
            continue
          reason = str(record.get("reason", "unknown"))
          reasons[reason] += 1
          if reason in ("button_press", "button_change"):
            for name in record.get("pressed_buttons", record.get("decoded", {}).get("names", [])):
              buttons[str(name)] += 1
    except OSError:
      invalid_lines += 1
  return reasons, buttons, invalid_lines


def command_summary(args: argparse.Namespace) -> int:
  root = default_log_root()
  paths = [Path(path) for path in args.paths] if args.paths else _log_files(root, args.include_active)
  reasons, buttons, invalid_lines = _summarize(paths)
  print(f"Files: {len(paths)}")
  print(f"Button presses: {dict(sorted(buttons.items()))}")
  print(f"Record reasons: {dict(sorted(reasons.items()))}")
  print(f"Unreadable/truncated lines: {invalid_lines}")
  return 0


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Inspect automatic Toyota TSS3 passive-recorder logs")
  commands = parser.add_subparsers(dest="command", required=True)

  status = commands.add_parser("status", help="show recorder health and counters")
  status.set_defaults(function=command_status)

  listing = commands.add_parser("list", help="list locally retained logs")
  listing.add_argument("--include-active", action="store_true", help="also show the current in-progress part")
  listing.set_defaults(function=command_list)

  summary = commands.add_parser("summary", help="count button edges in logs")
  summary.add_argument("paths", nargs="*", help="specific logs; defaults to all completed logs")
  summary.add_argument("--include-active", action="store_true", help="include the current in-progress part")
  summary.set_defaults(function=command_summary)
  return parser


def main() -> int:
  args = build_parser().parse_args()
  return int(args.function(args))


if __name__ == "__main__":
  raise SystemExit(main())
