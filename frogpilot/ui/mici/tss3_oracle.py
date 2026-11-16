import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from cereal import car, messaging
from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app


TOOL_PATH = Path(BASEDIR) / "selfdrive/car/toyota_tss3_oracle/tss3-request-signer"
CAROLLA_EPS_FIRMWARE = b"8965F1208000"


def _is_verified_corolla_tss3(CP) -> bool:
  if CP.brand == "toyota" and (bool(CP.flags & (1 << 12)) or CP.carFingerprint == "TOYOTA_COROLLA_TSS3"):
    return True
  return any(fw.ecu == "eps" and fw.address == 0x7A1 and CAROLLA_EPS_FIRMWARE in fw.fwVersion for fw in CP.carFw)


def _target_verified() -> bool:
  for key in ("CarParamsPersistent", "CarParamsCache", "CarParamsPrevRoute"):
    raw = ui_state.params.get(key)
    if raw is None:
      continue
    try:
      if _is_verified_corolla_tss3(messaging.log_from_bytes(raw, car.CarParams)):
        return True
    except Exception:
      continue
  return False


class Tss3OracleBigButton(BigButton):
  def __init__(self):
    super().__init__("TSS3 bringup", "start car once")
    self._process: subprocess.Popen | None = None
    self._run_dir: Path | None = None
    self._stage = ""
    self.set_click_callback(self._clicked)
    ui_state.add_offroad_transition_callback(self.refresh)
    self.refresh()

  def refresh(self):
    ui_state.update_params()
    if self._process is not None and self._process.poll() is None:
      return
    self._process = None
    target_verified = _target_verified()
    if not os.access(TOOL_PATH, os.X_OK):
      self.set_value("kit missing")
    elif target_verified:
      self.set_value("arm")
    else:
      self.set_value("start car once")

  def _clicked(self):
    if self._process is not None and self._process.poll() is None:
      if self._stage in ("arming", "armed") and self._run_dir is not None:
        try:
          (self._run_dir / "cancel-requested").write_text("cancel\n", encoding="utf-8")
          self.set_value("canceling")
        except OSError:
          gui_app.set_modal_overlay(BigDialog("Cancellation failed", "Leave the device connected and let bringup finish."))
      else:
        gui_app.set_modal_overlay(BigDialog("Bringup is running", "It has passed the safe cancellation point. Leave the device connected and let it finish."))
      return

    self.refresh()
    if ui_state.started:
      gui_app.set_modal_overlay(BigDialog("Turn the vehicle fully off", "TSS3 bringup can only be armed while the vehicle is off and in Park."))
    elif not _target_verified():
      gui_app.set_modal_overlay(BigDialog("Verify Corolla first", "Power the car on once and wait for fingerprinting to finish, then turn it fully off and return here. Bringup will not arm an unknown EPS target."))
    elif not os.access(TOOL_PATH, os.X_OK):
      gui_app.set_modal_overlay(BigDialog("TSS3 kit missing", "The bundled request signer is missing or not executable."))
    else:
      gui_app.set_modal_overlay(BigDialog(
        "Arm TSS3 bringup?",
        "Keep the vehicle fully off and in Park. Then press the brake and POWER normally. The signer is loaded into RAM only.",
        right_btn="ARM", right_btn_callback=self._start))

  def _start(self):
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    self._run_dir = Path(f"/data/tss3-oracle-runs/{timestamp}-{os.getpid()}")
    try:
      self._run_dir.mkdir(parents=True, exist_ok=False)
    except OSError:
      self.set_value("start failed")
      return
    self._stage = "arming"
    self.set_value("cancel")
    try:
      self._process = subprocess.Popen(
        [str(TOOL_PATH), "ui-bringup", str(self._run_dir)], cwd=TOOL_PATH.parent,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError:
      self._process = None
      self.set_value("start failed")
      return
    threading.Thread(target=self._read_status, daemon=True).start()

  def _read_status(self):
    assert self._process is not None and self._process.stdout is not None
    for line in self._process.stdout:
      try:
        status = json.loads(line)
      except (TypeError, ValueError):
        continue
      if not isinstance(status, dict):
        continue
      if status.get("schema") != "tss3-request-signer-ui-status-v1":
        continue
      stage = status.get("stage", "")
      progress = status.get("progress")
      if not isinstance(progress, int) or not 0 <= progress <= 100:
        continue
      self._stage = stage
      if stage == "done":
        self.set_value("done")
      elif stage == "error":
        self.set_value("error")
      elif stage in ("arming", "armed"):
        self.set_value("cancel")
      else:
        self.set_value(f"{progress}%")
    if self._stage not in ("done", "error"):
      self.set_value("failed")
