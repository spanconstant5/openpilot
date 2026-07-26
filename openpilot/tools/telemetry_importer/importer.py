from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from openpilot.tools.telemetry_importer.selection import CopyItem, needs_copy, select_completed_files


REMOTE_ROOT = PurePosixPath("/data/media/0/telemetry")
DEFAULT_ADB_ENDPOINT = "192.168.43.1:5555"


class ImportFailure(RuntimeError):
  pass


def find_adb(explicit: Path | None = None) -> Path:
  candidates: list[Path] = []
  if explicit is not None:
    candidates.append(explicit)
  module_path = Path(__file__).resolve()
  repository_root = module_path.parents[3]
  candidates.extend((module_path.parent / "adb.exe", repository_root / "tools" / "telemetry_importer" / "adb.exe"))
  local_app_data = os.environ.get("LOCALAPPDATA")
  if local_app_data:
    winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    candidates.extend(winget_root.glob("Google.PlatformTools_*/platform-tools/adb.exe"))
  from_path = shutil.which("adb") or shutil.which("adb.exe")
  if from_path:
    candidates.append(Path(from_path))
  for candidate in candidates:
    if candidate.is_file():
      return candidate.resolve()
  raise ImportFailure("adb was not found. Put adb.exe beside Import.bat or add Android platform-tools to PATH.")


def run_adb(adb: Path, serial: str | None, arguments: list[str], binary: bool = False) -> bytes | str:
  command = [str(adb)]
  if serial:
    command.extend(("-s", serial))
  command.extend(arguments)
  result = subprocess.run(command, capture_output=True, check=False)
  if result.returncode:
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise ImportFailure(f"adb command failed ({' '.join(arguments)}): {detail or 'unknown error'}")
  return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def _device_states(output: str) -> tuple[list[str], list[str]]:
  lines = [line.split() for line in output.splitlines()[1:] if line.strip()]
  authorized = [parts[0] for parts in lines if len(parts) >= 2 and parts[1] == "device"]
  unauthorized = [parts[0] for parts in lines if len(parts) >= 2 and parts[1] == "unauthorized"]
  return authorized, unauthorized


def connected_device(adb: Path, network_endpoint: str = DEFAULT_ADB_ENDPOINT) -> str:
  authorized, unauthorized = _device_states(str(run_adb(adb, None, ["devices"])))
  if unauthorized:
    raise ImportFailure("The comma is visible but unauthorized. Accept its ADB authorization prompt, then try again.")
  if not authorized and network_endpoint:
    print(f"No USB ADB device found; trying {network_endpoint}...")
    try:
      run_adb(adb, None, ["connect", network_endpoint])
    except ImportFailure:
      pass
    authorized, unauthorized = _device_states(str(run_adb(adb, None, ["devices"])))
    if unauthorized:
      raise ImportFailure("The comma is visible but unauthorized. Accept its ADB authorization prompt, then try again.")
    if not authorized:
      raise ImportFailure(
      "No comma was detected by USB or network ADB. On comma 3X/four, enable ADB, power port 2, " +
      "connect the PC with a data cable to port 1, or join the comma network/tether and retry."
    )
  if len(authorized) != 1:
    raise ImportFailure(f"Expected one comma device, found {len(authorized)}. Disconnect extra ADB devices.")
  return authorized[0]


def remote_manifests(adb: Path, serial: str) -> list[PurePosixPath]:
  output = str(run_adb(adb, serial, ["shell", "find", str(REMOTE_ROOT), "-type", "f", "-name", "manifest.json"]))
  paths = []
  for value in output.splitlines():
    path = PurePosixPath(value.strip())
    try:
      path.relative_to(REMOTE_ROOT)
    except ValueError:
      continue
    paths.append(path)
  return sorted(paths)


def read_remote_json(adb: Path, serial: str, path: PurePosixPath) -> dict[str, Any]:
  raw = run_adb(adb, serial, ["exec-out", "cat", str(path)], binary=True)
  try:
    value = json.loads(bytes(raw).decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise ImportFailure(f"Invalid JSON from {path}: {error}") from error
  if not isinstance(value, dict):
    raise ImportFailure(f"Expected a JSON object in {path}")
  return value


def remote_size(adb: Path, serial: str, path: PurePosixPath) -> int:
  output = str(run_adb(adb, serial, ["shell", "stat", "-c", "%s", str(path)])).strip()
  try:
    return int(output)
  except ValueError as error:
    raise ImportFailure(f"Could not determine the size of {path}: {output!r}") from error


def pull(adb: Path, serial: str, remote: PurePosixPath, destination: Path) -> None:
  destination.parent.mkdir(parents=True, exist_ok=True)
  run_adb(adb, serial, ["pull", "-a", str(remote), str(destination)])


def copy_item(adb: Path, serial: str, item: CopyItem, local_drive: Path) -> tuple[bool, int]:
  size = item.expected_size if item.expected_size is not None else remote_size(adb, serial, item.remote_path)
  destination = local_drive / item.local_relative_path
  if not needs_copy(destination, size):
    print(f"skip  {destination} ({size:,} bytes)")
    return False, size
  print(f"copy  {item.remote_path}")
  pull(adb, serial, item.remote_path, destination)
  if destination.stat().st_size != size:
    raise ImportFailure(f"Size verification failed for {destination}")
  return True, size


def import_drive(adb: Path, serial: str, manifest_path: PurePosixPath, destination_root: Path) -> tuple[int, int]:
  relative_manifest = manifest_path.relative_to(REMOTE_ROOT)
  if relative_manifest.name != "manifest.json" or len(relative_manifest.parts) < 3:
    raise ImportFailure(f"Unexpected telemetry manifest path: {manifest_path}")
  drive_relative = relative_manifest.parent
  local_drive = destination_root.joinpath(*drive_relative.parts)
  manifest = read_remote_json(adb, serial, manifest_path)
  items = select_completed_files(manifest, manifest_path.parent)
  copied = 0
  total_bytes = 0
  for item in items:
    did_copy, size = copy_item(adb, serial, item, local_drive)
    copied += int(did_copy)
    total_bytes += size

  for name in ("metadata.json", "manifest.json"):
    remote = manifest_path.parent / name
    try:
      size = remote_size(adb, serial, remote)
    except ImportFailure:
      if name == "metadata.json":
        continue
      raise
    destination = local_drive / name
    if needs_copy(destination, size):
      pull(adb, serial, remote, destination)
  return copied, total_bytes


def default_destination() -> Path:
  profile = os.environ.get("USERPROFILE")
  if not profile:
    raise ImportFailure("USERPROFILE is unavailable; pass --destination explicitly.")
  return Path(profile) / "Documents" / "Comma Telemetry"


def main() -> None:
  parser = argparse.ArgumentParser(description="Import completed comma telemetry and associated road video")
  parser.add_argument("--adb", type=Path, help="path to adb.exe")
  parser.add_argument("--adb-endpoint", default=DEFAULT_ADB_ENDPOINT,
                      help="network ADB endpoint tried when no USB device is visible; pass an empty value to disable")
  parser.add_argument("--destination", type=Path, default=None, help="import root")
  args = parser.parse_args()
  try:
    adb = find_adb(args.adb)
    serial = connected_device(adb, args.adb_endpoint)
    destination = args.destination or default_destination()
    destination.mkdir(parents=True, exist_ok=True)
    manifests = remote_manifests(adb, serial)
    if not manifests:
      raise ImportFailure(f"No telemetry drives found under {REMOTE_ROOT}")
    print(f"Device: {serial}")
    print(f"Destination: {destination}")
    copied = 0
    total_bytes = 0
    for manifest_path in manifests:
      drive_copied, drive_bytes = import_drive(adb, serial, manifest_path, destination)
      copied += drive_copied
      total_bytes += drive_bytes
    print(f"Import complete: {copied} file(s) copied, {total_bytes / (1024 ** 2):.1f} MiB selected.")
  except (ImportFailure, OSError) as error:
    print(f"Import failed: {error}", file=sys.stderr)
    raise SystemExit(1) from error


if __name__ == "__main__":
  main()
