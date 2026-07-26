#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  printf 'Homebrew is required to install Python, ADB, and FFmpeg. Install Homebrew now? [y/N] '
  read -r answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    printf 'Cancelled. No system packages were installed.\n'
    exit 1
  fi
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

brew install python@3.12 ffmpeg
brew install --cask android-platform-tools
python="$(brew --prefix python@3.12)/bin/python3.12"
"$python" -m venv "$repo/.venv"
"$repo/.venv/bin/python" -m pip install --upgrade pip
"$repo/.venv/bin/python" -m pip install -r "$repo/tools/telemetry_viewer/requirements.txt" pyinstaller

printf '\nTSKDash dependencies are ready. Press Return to close.'
read -r
