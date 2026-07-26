#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
python="${PYTHON:-$repo/.venv/bin/python}"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi
cd "$repo"
"$python" -m pip install 'PySide6>=6.7,<7' pyinstaller
"$python" -m PyInstaller --noconfirm --clean --windowed --name tskdash-viewer \
  --paths "$repo" openpilot/tools/telemetry_viewer/viewer.py
"$python" -m PyInstaller --noconfirm --clean --console --name tskdash-import \
  --paths "$repo" openpilot/tools/telemetry_importer/importer.py
printf 'Unsigned local builds are in %s/dist\n' "$repo"
