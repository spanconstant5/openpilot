"""Safe orchestration around the vendored EPS Telescope probe primitives."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from openpilot.tools.eps_telescope.upstream import load_probe_modules


deep_probe, report, uds_probe, vehicle_fingerprint, DID_APPLICATION, EcuTransport, EnvelopeAuthError, load_openpilot_bindings = load_probe_modules()


MODE_UDS = "uds"
MODE_SECURITY = "sa"
MODE_DEEP = "shellcode"
MODES = (MODE_UDS, MODE_SECURITY, MODE_DEEP)

ProgressCallback = Callable[[str, str, float], None]


@dataclass(frozen=True)
class ProbeConfig:
  mode: str = MODE_UDS
  addr: int = 0x7A1
  serial: str | None = None
  scan_egg: bool = True
  fingerprint_vehicle: bool = True
  artifacts_dir: str = "/data/eps_telescope"

  def __post_init__(self):
    if self.mode not in MODES:
      raise ValueError(f"unsupported EPS Telescope mode: {self.mode}")


def _notify(callback: ProgressCallback | None, stage: str, message: str, progress: float) -> None:
  if callback is not None:
    callback(stage, message, progress)


def _read_f181(transport) -> bytes:
  return bytes(transport.uds.read_data_by_identifier(DID_APPLICATION))


def _probe_vehicle(transport) -> dict:
  bindings = load_openpilot_bindings()
  panda = transport.panda
  bus = transport.bus

  def uds_factory(addr):
    return bindings.UdsClient(panda, addr, addr + 8, bus, timeout=vehicle_fingerprint.FINGERPRINT_TIMEOUT)

  main_uds = uds_factory(vehicle_fingerprint.MAIN_ECU_ADDR)
  try:
    return vehicle_fingerprint.fingerprint(main_uds, uds_factory)
  finally:
    main_uds.close()


def _run_deep(transport, payload: bytes, scan_egg: bool) -> dict:
  deep = deep_probe.run_deep_probe(transport, shellcode=payload, scan_egg=scan_egg)
  deep["fingerprint"] = deep_probe.verify_patch_fingerprint(
    deep["regions"], deep["egg_candidates"], region_bad=deep["region_bad"],
  )
  deep["boot_integrity"] = deep_probe.verify_boot_integrity(
    deep["regions"], region_bad=deep["region_bad"],
  )
  deep["classification"] = deep_probe.classify_target(
    deep["fingerprint"],
    deep["boot_integrity"],
    sa_ok=True,
    envelope_ok=deep["envelope_ok"],
    stream_ok=deep["stream_valid"],
    scan_egg=scan_egg,
  )
  return deep


def _json_default(value):
  if isinstance(value, bytes):
    return value.hex()
  raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _write_artifacts(base_dir: str, report_data: dict) -> Path:
  root = Path(base_dir)
  stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
  out_dir = root / stamp
  out_dir.mkdir(parents=True, exist_ok=False)

  outputs = {
    "probe.json": json.dumps(report_data["json"], default=_json_default, indent=2).encode(),
    "probe.md": report_data["markdown"].encode(),
  }
  for name, contents in outputs.items():
    target = out_dir / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(contents)
    os.replace(temporary, target)
  return out_dir


def run_probe(config: ProbeConfig, *, payload: bytes | None = None,
              transport_factory=None, progress_callback: ProgressCallback | None = None) -> Path:
  """Run one probe with mode-specific gates and always restore the default session.

  Unlike the upstream CLI, UDS and Security modes never enter the programming
  session. Only Deep mode probes RequestDownload or uploads the pinned RAM
  payload.
  """
  if transport_factory is None:
    def transport_factory():
      return EcuTransport(serial=config.serial, addr=config.addr)

  sessions = {
    MODE_UDS: [uds_probe.SESSION_DEFAULT],
    MODE_SECURITY: [uds_probe.SESSION_DEFAULT, uds_probe.SESSION_EXTENDED],
    MODE_DEEP: [uds_probe.SESSION_DEFAULT, uds_probe.SESSION_EXTENDED, uds_probe.SESSION_PROGRAMMING],
  }[config.mode]

  layer1: dict = {"sessions": [], "dids": [], "routines": [], "download": {}}
  layer2: dict = {"sa_ok": None, "nrc": None, "envelope_ok": None, "envelope_nrc": None}
  layer3: dict | None = None
  app_f181: bytes | None = None
  boot_f181: bytes | None = None
  identity_error: str | None = None

  _notify(progress_callback, "connecting", "Taking exclusive control of the Panda", 0.05)
  transport = transport_factory()
  with transport:
    try:
      try:
        app_f181 = _read_f181(transport)
      except Exception as exc:
        identity_error = str(exc)

      _notify(progress_callback, "uds", "Reading the EPS diagnostic surface", 0.18)
      layer1["sessions"] = uds_probe.probe_sessions(transport, sessions)
      layer1["dids"] = uds_probe.probe_dids(transport)

      if config.mode in (MODE_SECURITY, MODE_DEEP):
        _notify(progress_callback, "capabilities", "Checking protected EPS capabilities", 0.38)
        layer1["routines"] = uds_probe.probe_routines(transport)
      if config.mode == MODE_DEEP:
        layer1["download"] = uds_probe.probe_download_acceptance(transport)
        try:
          boot_f181 = _read_f181(transport)
        except Exception:
          pass

      if config.fingerprint_vehicle:
        _notify(progress_callback, "vehicle", "Identifying the Toyota platform", 0.52)
        try:
          layer1["vehicle"] = _probe_vehicle(transport)
        except Exception as exc:
          layer1["vehicle"] = {"error": str(exc)}

      if config.mode in (MODE_SECURITY, MODE_DEEP):
        _notify(progress_callback, "security", "Checking EPS Security Access", 0.65)
        sa_ok, sa_nrc = transport.security_access()
        layer2["sa_ok"] = sa_ok
        layer2["nrc"] = sa_nrc

        if config.mode == MODE_DEEP and sa_ok:
          if payload is None:
            raise RuntimeError("the pinned deep-probe payload is missing")
          _notify(progress_callback, "deep_probe", "Reading the firmware fingerprint from RAM", 0.76)
          try:
            layer3 = _run_deep(transport, payload, config.scan_egg)
          except EnvelopeAuthError as exc:
            layer2["envelope_ok"] = False
            layer2["envelope_nrc"] = exc.nrc
            layer3 = {
              "envelope_ok": False,
              "error": str(exc),
              "classification": deep_probe.classify_target(
                {"status": "NO_DATA", "candidates": []},
                {"adjust_word": None, "state": "unknown"},
                sa_ok=True,
                envelope_ok=False,
              ),
            }
          else:
            layer2["envelope_ok"] = layer3["envelope_ok"]
    finally:
      _notify(progress_callback, "restoring", "Returning the EPS to its normal diagnostic session", 0.93)
      try:
        transport.uds.diagnostic_session_control(uds_probe.SESSION_DEFAULT)
      except Exception:
        pass

  meta = {
    "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "addr": f"0x{config.addr:X}",
    "serial": config.serial,
    "depth": config.mode,
    "app_f181": None if app_f181 is None else app_f181.hex(),
    "boot_f181": None if boot_f181 is None else boot_f181.hex(),
  }
  if identity_error is not None:
    meta["identity_error"] = identity_error

  _notify(progress_callback, "saving", "Saving the report on the comma", 0.97)
  return _write_artifacts(config.artifacts_dir, report.build_report(meta, layer1, layer2, layer3))


def summarize_report(report_path: Path, mode: str) -> dict:
  data = json.loads(report_path.read_text())
  classification = data.get("classification") or {}
  layer2 = data.get("layer2") or {}
  if classification.get("classification"):
    outcome = classification["classification"]
  elif mode in (MODE_SECURITY, MODE_DEEP):
    outcome = "security_access_passed" if layer2.get("sa_ok") else "security_access_blocked"
  else:
    outcome = "uds_scan_complete"
  return {
    "timestamp": data.get("meta", {}).get("timestamp"),
    "mode": mode,
    "outcome": outcome,
    "classification": classification.get("classification"),
    "power_cycle_recommended": mode == MODE_DEEP,
    "report": str(report_path),
  }
