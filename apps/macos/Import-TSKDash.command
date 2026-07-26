#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
python="$repo/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi
cd "$repo"
"$python" -m openpilot.tools.telemetry_importer.importer "$@"
printf '\nImport finished. Press Return to close.'
read -r
