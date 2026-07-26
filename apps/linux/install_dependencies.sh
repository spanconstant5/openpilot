#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  elevate=()
elif command -v sudo >/dev/null 2>&1; then
  elevate=(sudo)
else
  printf 'Root access or sudo is required to install system packages.\n' >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  "${elevate[@]}" apt-get update
  "${elevate[@]}" apt-get install -y python3 python3-venv python3-pip adb ffmpeg \
    libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
elif command -v dnf >/dev/null 2>&1; then
  "${elevate[@]}" dnf install -y python3 python3-pip android-tools ffmpeg \
    mesa-libEGL mesa-libGL libxkbcommon-x11 xcb-util-cursor
elif command -v pacman >/dev/null 2>&1; then
  "${elevate[@]}" pacman -S --needed --noconfirm python python-pip android-tools ffmpeg \
    libglvnd libxkbcommon-x11 xcb-util-cursor
else
  printf 'Supported package managers: apt-get, dnf, and pacman. Install Python 3, ADB, and FFmpeg manually on this distribution.\n' >&2
  exit 1
fi

python3 -c 'import sys; sys.exit("Python 3.12 or newer is required") if sys.version_info < (3, 12) else None'
python3 -m venv "$repo/.venv"
"$repo/.venv/bin/python" -m pip install --upgrade pip
"$repo/.venv/bin/python" -m pip install -r "$repo/tools/telemetry_viewer/requirements.txt" pyinstaller

printf '\nTSKDash dependencies are ready.\n'
