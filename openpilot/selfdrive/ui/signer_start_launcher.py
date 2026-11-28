from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


OUTPUT_ROOT = Path("/data/signer-start")
STATUS_FILE = OUTPUT_ROOT / "status.json"
LOG_FILE = OUTPUT_ROOT / "launcher.log"


def read_status() -> dict[str, Any] | None:
  try:
    value = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return value if value.get("schema") == "signer-start-status-v1" else None
  except (OSError, ValueError, TypeError):
    return None


def process_running(pid: int | None) -> bool:
  if not pid or pid <= 1:
    return False
  try:
    os.kill(pid, 0)
    return True
  except (OSError, ValueError):
    return False


def capture_running() -> bool:
  status = read_status()
  return bool(status and not status.get("done") and not status.get("error") and process_running(status.get("pid")))


def start_capture(duration: int = 60, wait_timeout: int = 180) -> tuple[bool, str]:
  if capture_running():
    return False, "A Signer Start capture is already running."
  OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
  command = [sys.executable, "-m", "openpilot.selfdrive.car.signer_start",
             "--duration", str(duration), "--wait-timeout", str(wait_timeout), "--output-root", str(OUTPUT_ROOT)]
  try:
    with LOG_FILE.open("ab", buffering=0) as log_file:
      process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                                 close_fds=True, start_new_session=True)
  except OSError as exc:
    return False, f"Could not start capture: {exc}"
  return True, f"Capture armed as process {process.pid}. Start the vehicle while parked within {wait_timeout} seconds."


def status_label() -> str:
  status = read_status()
  if capture_running():
    return f"{int(status.get('progress', 0))}%"
  if status and status.get("done"):
    return "SAVED"
  if status and status.get("error"):
    return "ERROR"
  return "START"


def status_message() -> str:
  status = read_status()
  if status is None:
    return "No Signer Start capture has run yet."
  detail = str(status.get("detail", ""))
  archive = status.get("archive")
  if archive:
    detail += f"\n\nCopy this package with SSH or Cyberduck:\n{archive}"
  return detail
