"""Create a portable EPS Telescope report bundle for the local PC portal."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


DEFAULT_EXPORT_ROOT = Path("/data/media/0/telemetry/eps_telescope_exports")
EXPORT_SUFFIX = ".eps-telescope.zip"


def create_export_bundle(output_dir: Path, export_root: Path = DEFAULT_EXPORT_ROOT) -> Path:
  output_dir = output_dir.resolve()
  inputs = (output_dir / "probe.json", output_dir / "probe.md")
  if not all(path.is_file() for path in inputs):
    raise FileNotFoundError("EPS Telescope report is incomplete and cannot be exported")

  export_root.mkdir(parents=True, exist_ok=True)
  destination = export_root / f"{output_dir.name}{EXPORT_SUFFIX}"
  temporary = destination.with_suffix(destination.suffix + ".tmp")
  manifest = {
    "created_at": datetime.now(UTC).isoformat(),
    "source": str(output_dir),
    "contains_vehicle_identifiers": True,
    "privacy_note": "This bundle can include a VIN and ECU identifiers. Share it deliberately.",
  }
  with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
    for path in inputs:
      archive.write(path, arcname=path.name)
    archive.writestr("export_manifest.json", json.dumps(manifest, indent=2))
  os.replace(temporary, destination)
  return destination
