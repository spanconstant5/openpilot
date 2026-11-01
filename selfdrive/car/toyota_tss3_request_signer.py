from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpilot.common.params import Params


DEFAULT_TOOL_PATH = Path("/data/tss3-oracle/tss3-request-signer")
DEFAULT_RUN_ROOT = Path("/data/tss3-oracle-runs")
EXPECTED_TARGET = "corolla-8965F1208000"
EXPECTED_APPLICATION_F181 = "023839363546313230383030300000000038413331313132313330303000000000"
EXPECTED_KIT_SCHEMA = "tss3-request-signer-build-v2"
# Reviewed output from kaikozlov/ghidra_rh850 commit 9a7c8a7ec6d0045fdbdb8452cac7d4cf52439e2c.
EXPECTED_HOST_SHA256 = "beab7cdeaa685ff98de2f7751ddc39f8a096dd6c177bf812ed8c7878aadd31b1"
EXPECTED_UI_BRINGUP_SHA256 = "9c0dd6733ae70250c493eac06c9f176e9762d2765cfb8691a282b6cada7121e6"
EXPECTED_LAUNCHER_SHA256 = "4c4dd0d56177908bf58b36bf6b57ea972b4ea635581202a0b2f5848252fcbfd6"
EXPECTED_RUNTIME_SOURCE_SHA256 = "03765858c09aba296ffff8670422e53f71d0051ec7ec70699212349eb8a64dcb"
EXPECTED_PAYLOAD_SHA256 = "6234bb5bd496a82fabb32c27b56b3db0f1907b5bf6482e4c19f8835153ff69fc"
# October 30 and 31 vehicle evidence proved this resident stops responding
# within about 8 seconds of installation even under continuous response-paced
# challenges. The old assembly implementation is not a usable control
# authority. Keep the hash explicit so an unchanged external kit fails closed
# when a reviewed successor is pinned above.
REVOKED_PAYLOAD_SHA256S = frozenset({
  "72ffc3eebbec7966177c700a12e3d132f4a5bd03682e61f266bfea62815f8122",
})
PASS_VERDICT = "request_signer_live_probe_pass"
COROLLA_TSS3_MODEL = "TOYOTA_COROLLA_TSS3"
TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH = Path("/tmp/openpilot-tss3-card-bridge-request")
TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH = Path("/tmp/openpilot-tss3-card-bridge-ready")


def tss3_startup_bridge_token() -> str | None:
  try:
    token = TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH.read_text(encoding="utf-8").strip()
    return token or None
  except OSError:
    return None


def tss3_startup_bridge_active() -> bool:
  return tss3_startup_bridge_token() is not None


def release_tss3_startup_bridge(expected_token: str | None = None) -> None:
  """Release only the lease this caller observed, never a newer UI request."""
  token = tss3_startup_bridge_token()
  if token is None or (expected_token is not None and token != expected_token):
    return
  TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH.unlink(missing_ok=True)
  try:
    if TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH.read_text(encoding="utf-8").strip() == token:
      TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH.unlink(missing_ok=True)
  except OSError:
    pass


def tss3_startup_bridge_release_ready(car_fingerprint: str, can_valid: bool, onroad: bool) -> bool:
  """Release prewarm ownership only after the real Corolla card path is live."""
  return car_fingerprint != COROLLA_TSS3_MODEL or (can_valid and onroad)


@dataclass(frozen=True)
class SignerKitCheck:
  compatible: bool
  detail: str


@dataclass(frozen=True)
class SignerInstallResult:
  passed: bool
  title: str
  detail: str
  output_path: Path | None = None
  returncode: int | None = None


def _sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def _runtime_source_sha256(runtime_root: Path) -> str:
  """Hash the complete executable Python/shell surface shipped by the kit."""
  digest = hashlib.sha256()
  paths = sorted(path for path in runtime_root.rglob("*") if path.is_file() and path.suffix in (".py", ".sh"))
  for path in paths:
    relative = path.relative_to(runtime_root).as_posix().encode()
    digest.update(len(relative).to_bytes(4, "big"))
    digest.update(relative)
    with path.open("rb") as f:
      for chunk in iter(lambda: f.read(1024 * 1024), b""):
        digest.update(chunk)
  return digest.hexdigest()


def _tool_path(tool_path: Path | None = None) -> Path:
  return tool_path or Path(os.getenv("TSS3_REQUEST_SIGNER_TOOL", str(DEFAULT_TOOL_PATH)))


def _run_root(run_root: Path | None = None) -> Path:
  return run_root or Path(os.getenv("TSS3_REQUEST_SIGNER_RUN_ROOT", str(DEFAULT_RUN_ROOT)))


def request_signer_tool_available(tool_path: Path | None = None) -> bool:
  tool = _tool_path(tool_path)
  return tool.is_file() and os.access(tool, os.X_OK)


def request_signer_kit_compatibility(tool_path: Path | None = None) -> SignerKitCheck:
  """Reject stale, Camry, or otherwise unreviewed signer kits before touching the EPS."""
  tool = _tool_path(tool_path)
  if not tool.is_file() or not os.access(tool, os.X_OK):
    return SignerKitCheck(False, f"Signer tool unavailable: {tool}")

  root = tool.parent
  runtime_root = root / "runtime"
  host_path = root / "runtime" / "tsk" / "ram_runtime" / "tss3_request_signer.py"
  ui_bringup_path = root / "runtime" / "tsk" / "ram_runtime" / "tss3_request_signer_ui_bringup.py"
  meta_path = root / "bundle" / "request_signer.json"
  payload_path = root / "bundle" / "payload.bin"

  for label, path in (("host runtime", host_path), ("UI bringup backend", ui_bringup_path),
                      ("metadata", meta_path), ("payload", payload_path)):
    if not path.is_file():
      return SignerKitCheck(False, f"Signer {label} missing: {path}")

  try:
    launcher = tool.read_text(encoding="utf-8")
  except (OSError, UnicodeDecodeError) as exc:
    return SignerKitCheck(False, f"Signer launcher unreadable: {type(exc).__name__}: {exc}")
  if "ui-bringup)" not in launcher:
    return SignerKitCheck(False, "Signer launcher does not support guided ui-bringup")

  try:
    meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as exc:
    return SignerKitCheck(False, f"Signer metadata invalid: {type(exc).__name__}: {exc}")

  target = meta.get("target") if isinstance(meta.get("target"), dict) else {}
  request = meta.get("request") if isinstance(meta.get("request"), dict) else {}
  response = meta.get("response") if isinstance(meta.get("response"), dict) else {}
  authenticated_payload = meta.get("authenticated_payload") if isinstance(meta.get("authenticated_payload"), dict) else {}

  if meta.get("schema") != EXPECTED_KIT_SCHEMA:
    return SignerKitCheck(False, f"Unsupported signer metadata schema: {meta.get('schema', 'missing')}")

  if target.get("name") != EXPECTED_TARGET or target.get("application_f181_hex") != EXPECTED_APPLICATION_F181:
    return SignerKitCheck(False, f"Wrong signer target: {target.get('name', 'unknown')}; need {EXPECTED_TARGET}")
  if (request.get("bus"), request.get("can_id"), request.get("codec"), request.get("carrier")) != \
     (0, "0x00000777", "four-frame", "functional-nibble4"):
    return SignerKitCheck(False, "Signer request transport is not the proven Corolla bus-0 four-frame profile")
  if (response.get("bus"), response.get("can_id")) != (0, "0x000007A9"):
    return SignerKitCheck(False, "Signer response transport is not the proven Corolla bus-0 profile")
  if authenticated_payload.get("sha256") in REVOKED_PAYLOAD_SHA256S:
    return SignerKitCheck(
      False,
      "Signer payload revoked: the old Corolla resident stops after about 8 seconds; " +
      "install the reviewed successor payload before vehicle validation",
    )
  if authenticated_payload.get("sha256") != EXPECTED_PAYLOAD_SHA256:
    return SignerKitCheck(False, "Signer metadata names an unexpected authenticated payload")

  try:
    launcher_sha256 = _sha256(tool)
    host_sha256 = _sha256(host_path)
    ui_bringup_sha256 = _sha256(ui_bringup_path)
    runtime_source_sha256 = _runtime_source_sha256(runtime_root)
    payload_sha256 = _sha256(payload_path)
  except OSError as exc:
    return SignerKitCheck(False, f"Could not hash signer kit: {type(exc).__name__}: {exc}")

  if launcher_sha256 != EXPECTED_LAUNCHER_SHA256:
    return SignerKitCheck(False, f"Signer launcher hash mismatch: {launcher_sha256}")
  if host_sha256 != EXPECTED_HOST_SHA256:
    return SignerKitCheck(False, f"Signer host runtime hash mismatch: {host_sha256}")
  if ui_bringup_sha256 != EXPECTED_UI_BRINGUP_SHA256:
    return SignerKitCheck(False, f"Signer UI bringup hash mismatch: {ui_bringup_sha256}")
  if runtime_source_sha256 != EXPECTED_RUNTIME_SOURCE_SHA256:
    return SignerKitCheck(False, f"Signer runtime source hash mismatch: {runtime_source_sha256}")
  if payload_sha256 != EXPECTED_PAYLOAD_SHA256:
    return SignerKitCheck(False, f"Signer payload hash mismatch: {payload_sha256}")

  return SignerKitCheck(True, "Corolla request-signer kit verified")


def _write_log(path: Path, text: str) -> None:
  try:
    path.write_text(text, encoding="utf-8")
  except OSError:
    pass


def _timeout_text(value: str | bytes | None) -> str:
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="replace")
  return value or ""


def _failure(title: str, detail: str, output_path: Path | None = None,
             returncode: int | None = None) -> SignerInstallResult:
  return SignerInstallResult(False, title, detail, output_path, returncode)


def run_request_signer_install(tool_path: Path | None = None, run_root: Path | None = None) -> SignerInstallResult:
  """Run the proven volatile Corolla install and cycle controls to restore Panda car safety."""
  tool = _tool_path(tool_path)
  check = request_signer_kit_compatibility(tool)
  if not check.compatible:
    return _failure("RAM signer not installed", check.detail)

  try:
    doctor = subprocess.run(
      [str(tool), "doctor"], cwd=str(tool.parent), stdin=subprocess.DEVNULL,
      capture_output=True, text=True, timeout=30, check=False,
    )
  except (OSError, subprocess.TimeoutExpired) as exc:
    return _failure("RAM signer preflight failed", f"{type(exc).__name__}: {exc}")
  if doctor.returncode != 0:
    detail = (doctor.stderr or doctor.stdout or "doctor returned no details").strip()[-1200:]
    return _failure("RAM signer preflight failed", detail, returncode=doctor.returncode)

  stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
  run_dir = _run_root(run_root) / f"ui-{stamp}-{os.getpid()}"
  try:
    run_dir.mkdir(parents=True, exist_ok=False)
  except FileExistsError:
    run_dir = run_dir.with_name(f"{run_dir.name}-{time.monotonic_ns()}")
    run_dir.mkdir(parents=True, exist_ok=False)
  except OSError as exc:
    return _failure("RAM signer could not start", f"Could not create result directory: {exc}")

  output_path = run_dir / "install.json"
  try:
    install = subprocess.run(
      [str(tool), "install", str(output_path)], cwd=str(tool.parent), stdin=subprocess.DEVNULL,
      capture_output=True, text=True, timeout=120, check=False,
    )
  except subprocess.TimeoutExpired as exc:
    _write_log(run_dir / "install.log", _timeout_text(exc.stdout) + _timeout_text(exc.stderr))
    return _failure("RAM signer install timed out", "Installer exceeded the 120 second limit. Keep the car parked and inspect the saved log.", output_path)
  except OSError as exc:
    return _failure("RAM signer could not start", f"{type(exc).__name__}: {exc}", output_path)

  _write_log(run_dir / "install.log", install.stdout + install.stderr)
  if install.returncode != 0:
    detail = (install.stderr or install.stdout or "installer returned no details").strip()[-1200:]
    return _failure("RAM signer install failed", detail, output_path, install.returncode)

  try:
    result = json.loads(output_path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as exc:
    return _failure("RAM signer result invalid", f"Installer exited successfully but its JSON could not be read: {exc}", output_path, install.returncode)

  if result.get("schema") != "tss3-request-signer-install-v1" or result.get("verdict") != PASS_VERDICT:
    return _failure("RAM signer live probe failed", f"Unexpected verdict: {result.get('verdict', 'missing')}", output_path, install.returncode)

  probe = result.get("signer_probe") if isinstance(result.get("signer_probe"), dict) else {}
  elapsed_ms = probe.get("elapsed_ms")
  latency = f" Live probe: {float(elapsed_ms):.2f} ms." if isinstance(elapsed_ms, (int, float)) else ""

  # The installer deliberately leaves Panda in ELM327 safety. Force a short
  # offroad/onroad process cycle so pandad reapplies the reviewed Toyota safety
  # configuration before any control attempt.
  try:
    Params().put_bool("OnroadCycleRequested", True)
  except Exception as exc:
    detail = "The authenticated probe passed, but openpilot could not restore Panda car safety automatically: " + \
             f"{type(exc).__name__}: {exc}. Do not drive. Reboot openpilot before testing."
    return _failure(
      "RAM signer live; controls cycle failed",
      detail,
      output_path,
      install.returncode,
    )
  return SignerInstallResult(
    True,
    "Corolla RAM signer is live",
    f"Authenticated bus-0 probe passed.{latency} Controls are cycling to restore Corolla Panda safety.",
    output_path,
    install.returncode,
  )
