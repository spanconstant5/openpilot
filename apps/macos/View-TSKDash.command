#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
python="$repo/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi
cd "$repo"
exec "$python" -m openpilot.tools.telemetry_viewer.viewer "$@"
