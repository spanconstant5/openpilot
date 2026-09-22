from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openpilot.selfdrive.ui.ui_state import device
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.system.ui.widgets.scroller import NavScroller
from opendbc.car.toyota.values import CAR

TOOL_PATH = Path(os.getenv("TSS3_ORACLE_TOOL", "/data/tss3-oracle/tss3-unified-signer"))
RUN_ROOT = Path(os.getenv("TSS3_ORACLE_RUN_ROOT", "/data/tss3-oracle-runs"))
STATUS_SCHEMA = "camry-f33-oracle-ui-status-v1"

_oracle_bringup_active = False

STAGE_LABELS = {
  "arming": "starting",
  "armed": "waiting for POWER",
  "programming": "installing RAM oracle",
  "waiting_ready": "waiting for READY / Park",
  "verifying": "checking DRCC + native MAC",
  "done": "complete",
  "error": "failed",
}


def tool_available() -> bool:
  return TOOL_PATH.is_file() and os.access(TOOL_PATH, os.X_OK)


def oracle_bringup_active() -> bool:
  return _oracle_bringup_active


class Tss3OracleBringupPage(NavScroller):
  """Native comma page for TSS3 RAM-oracle bringup (Camry and Corolla)."""

  def __init__(self, fingerprint=None):
    super().__init__()
    self._fingerprint = fingerprint
    self._is_corolla = fingerprint == CAR.TOYOTA_COROLLA_TSS3
    self._lock = threading.Lock()
    detail = "Put car in NRTD/Park, then tap install." if self._is_corolla else "Preparing the startup catcher."
    self._status: dict[str, Any] = {
      "stage": "arming",
      "title": "TSS3 oracle bringup",
      "detail": detail,
      "progress": 0,
      "done": False,
      "error": False,
    }
    self._last_output = ""
    self._proc: subprocess.Popen[str] | None = None
    self._run_dir: Path | None = None

    self._status_card = GreyBigButton("oracle bringup", detail)
    self._progress_card = GreyBigButton("progress", "0%\nstarting")
    contract_detail = (
      "Put car in NRTD/Park first.\nNo EPS flash writes.\nDo NOT press READY until done."
      if self._is_corolla else
      "No EPS flash writes.\nNo Brake/FRC resets on a healthy run.\nKeep the vehicle in Park."
    )
    self._contract_card = GreyBigButton("RAM-only install", contract_detail)
    self._action_button = BigButton("cancel bringup", "swipe down also works")
    self._action_button.set_click_callback(self.dismiss)

    self._scroller.add_widgets([
      self._status_card,
      self._progress_card,
      self._contract_card,
      self._action_button,
    ])

    self._start_worker()

  def show_event(self):
    global _oracle_bringup_active
    super().show_event()
    _oracle_bringup_active = True
    device.set_override_interactive_timeout(300)

  def hide_event(self):
    global _oracle_bringup_active
    _oracle_bringup_active = False
    device.set_override_interactive_timeout(None)

    status = self._snapshot()
    proc = self._proc
    if proc is not None and proc.poll() is None and not status.get("done") and not status.get("error"):
      try:
        os.killpg(proc.pid, signal.SIGTERM)
      except ProcessLookupError:
        pass

    super().hide_event()

  def _snapshot(self) -> dict[str, Any]:
    with self._lock:
      return dict(self._status)

  def _set_status(self, status: dict[str, Any]) -> None:
    with self._lock:
      self._status = dict(status)

  def _start_worker(self) -> None:
    if not tool_available():
      self._set_status({
        "stage": "error",
        "title": "Oracle tool unavailable",
        "detail": f"Expected {TOOL_PATH}",
        "progress": 0,
        "done": False,
        "error": True,
      })
      return

    stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    self._run_dir = RUN_ROOT / f"{stamp}-{os.getpid()}"
    if self._is_corolla:
      cmd = [str(TOOL_PATH), "--topology", "camry-post-repin", "bringup", str(self._run_dir)]
    else:
      cmd = [str(TOOL_PATH), "--topology", "camry-post-repin", "oracle-ui-bringup", str(self._run_dir)]

    try:
      self._proc = subprocess.Popen(
        cmd,
        cwd=str(TOOL_PATH.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
      )
    except OSError as exc:
      self._set_status({
        "stage": "error",
        "title": "Could not start oracle bringup",
        "detail": f"{type(exc).__name__}: {exc}",
        "progress": 0,
        "done": False,
        "error": True,
      })
      return

    threading.Thread(target=self._reader, name="tss3_oracle_ui", daemon=True).start()

  def _reader(self) -> None:
    assert self._proc is not None and self._proc.stdout is not None
    for raw in self._proc.stdout:
      line = raw.strip()
      if not line:
        continue
      try:
        status = json.loads(line)
      except json.JSONDecodeError:
        with self._lock:
          self._last_output = line
        continue
      if isinstance(status, dict) and status.get("schema") == STATUS_SCHEMA:
        self._set_status(status)

    rc = self._proc.wait()
    status = self._snapshot()
    if not status.get("done") and not status.get("error"):
      with self._lock:
        detail = self._last_output or f"backend exited with status {rc}"
      self._set_status({
        "stage": "error",
        "title": "Oracle bringup stopped",
        "detail": detail,
        "progress": 0,
        "done": False,
        "error": True,
      })

  def _update_state(self):
    super()._update_state()
    status = self._snapshot()
    stage = str(status.get("stage", "arming"))
    progress = max(0, min(100, int(status.get("progress", 0))))

    self._status_card.set_text(str(status.get("title", "Oracle bringup")))
    self._status_card.set_value(str(status.get("detail", "")))
    self._progress_card.set_value(f"{progress}%\n{STAGE_LABELS.get(stage, stage)}")

    if status.get("done"):
      self._action_button.set_text("close")
      self._action_button.set_value("bringup passed")
    elif status.get("error"):
      self._action_button.set_text("close")
      self._action_button.set_value("bringup failed")
    else:
      self._action_button.set_text("cancel bringup")
      self._action_button.set_value("swipe down also works")
