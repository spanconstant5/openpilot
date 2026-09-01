#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpilot.common.tsk_sku import TskSkuProfile  # noqa: E402


PROFILE_DIR = ROOT / "sku" / "profiles"
ACTIVE_PATH = ROOT / "sku" / "active.json"
ACTIVE_README_PATH = ROOT / "sku" / "ACTIVE_PROFILE.md"


def main() -> int:
  parser = argparse.ArgumentParser(description="Select the passive Toyota TSK distribution profile for this branch")
  parser.add_argument("profile", choices=sorted(path.stem for path in PROFILE_DIR.glob("*.json")))
  args = parser.parse_args()

  source = PROFILE_DIR / f"{args.profile}.json"
  data = json.loads(source.read_text(encoding="utf-8"))
  profile = TskSkuProfile.from_dict(data)
  shutil.copyfile(source, ACTIVE_PATH)
  decoder = (f"`{profile.read_only_dbc}` on panda bus {profile.read_only_bus}"
             if profile.read_only_dbc is not None else "disabled pending a vehicle-specific passive capture")
  ACTIVE_README_PATH.write_text(
    "\n".join((
      f"# Active SKU: {profile.profile_id}",
      "",
      f"- Vehicle: {profile.vehicle} ({profile.model_years})",
      f"- Harness channel: {profile.harness_variant}",
      f"- Validation state: {profile.status}",
      f"- Pin-map state: {profile.pin_map_status}",
      f"- Read-only CAN decoder: {decoder}",
      "- Vehicle control: disabled (passive-only)",
      "",
      "This branch is a dashcam/telemetry research build. It does not claim active openpilot support for this vehicle.",
      "An unverified pin-swap profile is not a wiring instruction; verify the cavity map and continuity before use.",
      "",
    )), encoding="utf-8")
  print(f"Selected {profile.profile_id}: {profile.vehicle} / {profile.harness_variant} / {profile.status}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
