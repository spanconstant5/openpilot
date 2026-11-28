#!/usr/bin/env python3
"""Passive, topology-first capture for starting RAM-resident signer research.

This tool only records data already visible to openpilot. It never transmits CAN,
opens a diagnostic session, attempts SecurityAccess, reads ECU memory, or writes
RAM/flash. Its output is a discovery package, not an injection package.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import signal
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "signer-start-report-v1"
PORT_SEED_SCHEMA = "signer-start-port-seed-v1"
STATUS_SCHEMA = "signer-start-status-v1"
DEFAULT_OUTPUT_ROOT = Path("/data/signer-start")
EXPECTED_CHASSIS_BUS = 0
EXPECTED_CAMERA_BUS = 2
RECEIPT_BUS_MIN = 128

# Topology profiles are deliberately explicit. Address meanings are not
# portable across manufacturers, so an unknown family is blocked instead of
# being assigned a side from traffic volume alone. Add profiles as validated
# captures become available.
TOPOLOGY_PROFILES: dict[str, dict[str, Any]] = {
  "toyota_tss3": {
    "brands": {"toyota", "lexus"},
    "chassis_markers": {
      0x030: "EPS status",
      0x0AA: "wheel speeds",
      0x101: "brake module",
      0x116: "gas pedal",
      0x224: "brake status",
      0x226: "brake status alternate",
      0x260: "steering torque sensor",
    },
    "camera_markers": {
      0x08A: "TSS3 control request",
      0x180: "TSS3 radar geometry A",
      0x181: "TSS3 radar geometry B",
      0x182: "TSS3 radar geometry C",
      0x183: "TSS3 radar motion A",
      0x184: "TSS3 radar motion B",
      0x185: "TSS3 radar motion C",
      0x191: "LTA steering command",
      0x2E4: "LKA steering command",
      0x412: "LKAS HUD",
    },
  },
}

SIGNER_RESEARCH_ADDRESSES = {
  0x08A: "known control request",
  0x777: "known signer transport",
  0x7A1: "common EPS diagnostic request",
  0x7A9: "common EPS diagnostic response",
}

_stop_requested = False


def _request_stop(_signum: int, _frame: Any) -> None:
  global _stop_requested
  _stop_requested = True


@dataclass
class MessageStats:
  count: int = 0
  lengths: Counter[int] = field(default_factory=Counter)
  samples: list[str] = field(default_factory=list)
  first_ns: int | None = None
  last_ns: int | None = None

  def add(self, dat: bytes, mono_ns: int) -> None:
    self.count += 1
    self.lengths[len(dat)] += 1
    sample = dat.hex()
    if len(self.samples) < 3 and sample not in self.samples:
      self.samples.append(sample)
    self.first_ns = mono_ns if self.first_ns is None else self.first_ns
    self.last_ns = mono_ns

  def as_dict(self, capture_seconds: float) -> dict[str, Any]:
    return {
      "count": self.count,
      "rate_hz": round(self.count / max(capture_seconds, 0.001), 3),
      "lengths": {str(length): count for length, count in sorted(self.lengths.items())},
      "can_fd_observed": any(length > 8 for length in self.lengths),
      "samples": self.samples,
      "first_monotonic_ns": self.first_ns,
      "last_monotonic_ns": self.last_ns,
    }


def _bus_ids(messages: dict[int, MessageStats] | dict[str, Any]) -> set[int]:
  ret: set[int] = set()
  for address in messages:
    try:
      ret.add(int(address, 0) if isinstance(address, str) else int(address))
    except (TypeError, ValueError):
      pass
  return ret


def _message_count(messages: dict[int, MessageStats] | dict[str, Any]) -> int:
  return sum(stats.count if isinstance(stats, MessageStats) else int(stats.get("count", 0)) for stats in messages.values())


def _profile_for_brand(brand: str) -> tuple[str | None, dict[str, Any] | None]:
  normalized = brand.strip().lower()
  for name, profile in TOPOLOGY_PROFILES.items():
    if normalized in profile["brands"]:
      return name, profile
  return None, None


def _marker_evidence(ids: set[int], markers: dict[int, str]) -> list[dict[str, str]]:
  return [{"address": f"0x{address:03X}", "name": markers[address]} for address in sorted(ids & markers.keys())]


def analyze_topology(inventory: dict[int, dict[int, MessageStats]] | dict[str, Any], brand: str = "") -> dict[str, Any]:
  """Classify physical bus 0/2 conservatively and expose all evidence."""
  buses: dict[int, set[int]] = {}
  counts: dict[int, int] = {}
  for bus_key, messages in inventory.items():
    try:
      bus = int(bus_key)
    except (TypeError, ValueError):
      continue
    if bus >= RECEIPT_BUS_MIN:
      continue
    buses[bus] = _bus_ids(messages)
    counts[bus] = _message_count(messages)

  ids0 = buses.get(EXPECTED_CHASSIS_BUS, set())
  ids2 = buses.get(EXPECTED_CAMERA_BUS, set())
  union = ids0 | ids2
  overlap = len(ids0 & ids2) / len(union) if union else 0.0
  count_similarity = min(counts.get(0, 0), counts.get(2, 0)) / max(counts.get(0, 0), counts.get(2, 0), 1)
  profile_name, profile = _profile_for_brand(brand)
  evidence = [
    f"bus 0: {len(ids0)} unique IDs / {counts.get(0, 0)} frames",
    f"bus 2: {len(ids2)} unique IDs / {counts.get(2, 0)} frames",
    f"bus 0↔2 ID overlap: {overlap:.1%}; frame-count similarity: {count_similarity:.1%}",
  ]
  warnings: list[str] = []
  chassis_bus: int | None = None
  camera_bus: int | None = None
  chassis_hits: dict[int, list[dict[str, str]]] = {}
  camera_hits: dict[int, list[dict[str, str]]] = {}

  if not union or counts.get(0, 0) + counts.get(2, 0) < 50:
    status, confidence = "insufficient_data", 0.0
    warnings.append("Not enough physical bus 0/2 traffic was captured to determine topology.")
  elif overlap >= 0.80 and count_similarity >= 0.65:
    status, confidence = "bridged_or_mirrored", round(min(overlap, count_similarity), 3)
    warnings.append("CAN0 and CAN2 appear bridged or mirrored. Side assignment is not valid until the relay is open and the buses differ.")
  elif profile is None:
    status, confidence = "profile_needed", 0.0
    warnings.append(f"No validated topology profile exists for brand '{brand or 'unknown'}'. Traffic volume alone cannot prove which side is chassis.")
  else:
    chassis_markers = profile["chassis_markers"]
    camera_markers = profile["camera_markers"]
    chassis_hits = {bus: _marker_evidence(ids, chassis_markers) for bus, ids in buses.items()}
    camera_hits = {bus: _marker_evidence(ids, camera_markers) for bus, ids in buses.items()}
    chassis_scores = {bus: len(hits) for bus, hits in chassis_hits.items()}
    camera_scores = {bus: len(hits) for bus, hits in camera_hits.items()}
    if chassis_scores and max(chassis_scores.values()) >= 2:
      chassis_bus = max(chassis_scores, key=chassis_scores.get)
    if camera_scores and max(camera_scores.values()) >= 2:
      camera_bus = max(camera_scores, key=camera_scores.get)

    if chassis_bus is None or camera_bus is None or chassis_bus == camera_bus:
      status, confidence = "mixed_or_unknown", 0.2
      warnings.append("The validated marker profile did not isolate two different physical sides.")
    else:
      score = len(chassis_hits[chassis_bus]) + len(camera_hits[camera_bus])
      confidence = round(min(1.0, 0.45 + 0.07 * score), 3)
      if chassis_bus == EXPECTED_CHASSIS_BUS and camera_bus == EXPECTED_CAMERA_BUS:
        status = "resolved_standard"
      elif chassis_bus == EXPECTED_CAMERA_BUS and camera_bus == EXPECTED_CHASSIS_BUS:
        status = "resolved_reversed"
        warnings.append("Observed sides are reversed relative to comma harness convention: CAN0 car/chassis, CAN2 camera/ADAS.")
      else:
        status = "resolved_nonstandard"
        warnings.append("The profile resolved to a nonstandard bus pair. Physically verify the harness before proceeding.")
      evidence.append(f"chassis-marker leader: bus {chassis_bus} ({len(chassis_hits[chassis_bus])} markers)")
      evidence.append(f"camera-marker leader: bus {camera_bus} ({len(camera_hits[camera_bus])} markers)")

  passed = status == "resolved_standard"
  return {
    "gate": "PASS" if passed else "BLOCK",
    "status": status,
    "confidence": confidence,
    "profile": profile_name,
    "profile_brand": brand or None,
    "topology_resolved": status.startswith("resolved_"),
    "observed_chassis_bus": chassis_bus,
    "observed_camera_bus": camera_bus,
    "expected_harness_convention": {
      "chassis_bus": EXPECTED_CHASSIS_BUS,
      "camera_adas_bus": EXPECTED_CAMERA_BUS,
      "note": "comma harness convention; also verify connector continuity and labels physically",
    },
    "bus_0_to_2_id_overlap": round(overlap, 4),
    "bus_0_to_2_count_similarity": round(count_similarity, 4),
    "chassis_marker_evidence": {str(bus): hits for bus, hits in sorted(chassis_hits.items()) if hits},
    "camera_marker_evidence": {str(bus): hits for bus, hits in sorted(camera_hits.items()) if hits},
    "evidence_summary": evidence,
    "warnings": warnings,
    "gate_reason": (
      "Observed topology matches comma harness convention. This permits vehicle-specific lab analysis; it does not authorize injection."
      if passed else
      "Topology is unresolved, bridged, reversed, nonstandard, or lacks a validated profile. Resolve it before signer implementation work."
    ),
  }


def _enum_name(value: Any) -> str:
  try:
    return str(value)
  except Exception:
    return "unknown"


def _optional_int(obj: Any, name: str) -> int | None:
  try:
    return int(getattr(obj, name))
  except Exception:
    return None


def car_params_summary(raw: bytes | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
  if not raw:
    return {"available": False}, []
  try:
    from opendbc.car.structs import car
    with car.CarParams.from_bytes(raw) as cp:
      firmware = []
      for fw in cp.carFw:
        sub_address = _optional_int(fw, "subAddress")
        response_address = _optional_int(fw, "responseAddress")
        version = bytes(fw.fwVersion)
        firmware.append({
          "ecu": _enum_name(fw.ecu),
          "address": f"0x{int(fw.address):X}",
          "sub_address": f"0x{sub_address:X}" if sub_address else None,
          "response_address": f"0x{response_address:X}" if response_address else None,
          "firmware_version_hex": version.hex(),
          "firmware_version_text": version.decode("ascii", errors="replace"),
        })
      return {
        "available": True,
        "car_fingerprint": str(cp.carFingerprint),
        "brand": str(cp.brand),
        "vin": str(cp.carVin),
        "fuzzy_fingerprint": bool(cp.fuzzyFingerprint),
        "dashcam_only": bool(cp.dashcamOnly),
        "alpha_longitudinal_available": bool(cp.alphaLongitudinalAvailable),
        "openpilot_longitudinal_control": bool(cp.openpilotLongitudinalControl),
        "network_location": _enum_name(cp.networkLocation),
        "safety_configs": [
          {"model": _enum_name(config.safetyModel), "parameter": int(config.safetyParam)} for config in cp.safetyConfigs
        ],
        "firmware_entry_count": len(firmware),
      }, firmware
  except Exception as exc:
    return {"available": False, "parse_error": f"{type(exc).__name__}: {exc}"}, []


def _safe_param(params: Any, key: str) -> str | None:
  try:
    value = params.get(key)
  except Exception:
    return None
  if value is None:
    return None
  return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _recent_log_references(root: Path = Path("/data/media/0/realdata"), limit: int = 8) -> list[dict[str, Any]]:
  if not root.is_dir():
    return []
  try:
    entries = sorted((entry for entry in root.iterdir() if entry.is_dir()), key=lambda entry: entry.stat().st_mtime, reverse=True)[:limit]
  except OSError:
    return []
  ret = []
  for entry in entries:
    files = []
    try:
      for child in sorted(entry.iterdir()):
        if child.name.startswith(("qlog", "rlog")):
          files.append({"name": child.name, "size": child.stat().st_size})
    except OSError:
      pass
    ret.append({"route_or_segment": entry.name, "files": files})
  return ret


def _signer_evidence(inventory: dict[int, dict[int, MessageStats]], capture_seconds: float) -> list[dict[str, Any]]:
  ret = []
  for bus, messages in sorted(inventory.items()):
    if bus >= RECEIPT_BUS_MIN:
      continue
    for address, stats in sorted(messages.items()):
      if address in SIGNER_RESEARCH_ADDRESSES:
        ret.append({"bus": bus, "address": f"0x{address:03X}", "name": SIGNER_RESEARCH_ADDRESSES[address],
                    **stats.as_dict(capture_seconds)})
  return ret


def vehicle_enrollment(vehicle: dict[str, Any], firmware: list[dict[str, Any]]) -> dict[str, Any]:
  """Build a stable, non-VIN directory key for one car/firmware set."""
  vin = str(vehicle.get("vin", "")).strip()
  fingerprint = str(vehicle.get("car_fingerprint", "")).strip()
  meaningful_vin = len(vin) == 17 and vin not in {"0" * 17, "UNKNOWN"}
  firmware_identity = sorted(
    f"{entry.get('ecu')}:{entry.get('address')}:{entry.get('sub_address')}:{entry.get('firmware_version_hex')}"
    for entry in firmware
  )
  identity_parts = ([f"vin:{vin}"] if meaningful_vin else []) + [f"fingerprint:{fingerprint}", *firmware_identity]
  identity_material = "\n".join(identity_parts).encode("utf-8")
  identity_hash = hashlib.sha256(identity_material).hexdigest()[:16]
  brand = str(vehicle.get("brand", "unknown")).strip().lower() or "unknown"
  safe_brand = "".join(character if character.isalnum() else "-" for character in brand).strip("-")[:20] or "unknown"
  return {
    "enrollment_id": f"{safe_brand}-{identity_hash}",
    "scope": "one physical vehicle and its current ECU firmware set" if meaningful_vin else "one fingerprint/firmware set; VIN was unavailable",
    "identity_basis": ["vin", "fingerprint", "firmware"] if meaningful_vin else ["fingerprint", "firmware"],
    "vin_present": meaningful_vin,
    "firmware_tuple_count": len(firmware_identity),
  }


def _address_observations(inventory: dict[int, dict[int, MessageStats]], address: int,
                          capture_seconds: float) -> list[dict[str, Any]]:
  return [
    {"bus": bus, "address": f"0x{address:03X}", **messages[address].as_dict(capture_seconds)}
    for bus, messages in sorted(inventory.items())
    if bus < RECEIPT_BUS_MIN and address in messages
  ]


def tss3_vehicle_analysis(inventory: dict[int, dict[int, MessageStats]], capture_seconds: float,
                          vehicle: dict[str, Any], topology: dict[str, Any]) -> dict[str, Any]:
  brand = str(vehicle.get("brand", "")).strip().lower()
  control_request = _address_observations(inventory, 0x08A, capture_seconds)
  diagnostic_request = _address_observations(inventory, 0x7A1, capture_seconds)
  diagnostic_response = _address_observations(inventory, 0x7A9, capture_seconds)
  control_buses = [item["bus"] for item in control_request]
  candidate = brand in {"toyota", "lexus"} and (bool(control_request) or topology.get("profile") == "toyota_tss3")
  return {
    "candidate": candidate,
    "candidate_reason": (
      "Toyota/Lexus identity with TSS3 marker traffic."
      if candidate else "This capture does not yet establish a Toyota/Lexus TSS3 target."
    ),
    "control_request_0x08a": {
      "observed": bool(control_request),
      "observed_buses": control_buses,
      "camera_side_only": control_buses == [EXPECTED_CAMERA_BUS],
      "multiple_physical_sides": len(set(control_buses)) > 1,
      "observations": control_request,
    },
    "eps_diagnostic_request_0x7a1": diagnostic_request,
    "eps_diagnostic_response_0x7a9": diagnostic_response,
    "relay_separation_observed": topology.get("status") != "bridged_or_mirrored",
  }


def _capture_recommendations(topology: dict[str, Any], vehicle: dict[str, Any], firmware: list[dict[str, Any]],
                             tss3: dict[str, Any]) -> list[str]:
  recommendations = []
  if topology["status"] == "bridged_or_mirrored":
    recommendations.append("Repeat with the interception relay confirmed open; bridged CAN0/CAN2 cannot prove physical side ownership.")
  elif topology["gate"] != "PASS":
    recommendations.append("Physically verify harness connector sides and repeat until the topology gate passes.")
  if vehicle.get("car_fingerprint") in (None, "", "MOCK") or vehicle.get("fuzzy_fingerprint", True):
    recommendations.append("Allow firmware fingerprinting to finish after a full ignition cycle, then repeat for an exact identity.")
  if not firmware:
    recommendations.append("Wait for openpilot's firmware query to complete, power-cycle the car, and repeat to capture ECU firmware tuples.")
  if not any("eps" in entry.get("ecu", "").lower() for entry in firmware):
    recommendations.append("Capture or identify the EPS firmware response before treating this car as a signer-port candidate.")
  if tss3["candidate"] and not tss3["control_request_0x08a"]["observed"]:
    recommendations.append("Repeat with the FRC connected and ignition on so stock CONTROL_REQUEST 0x08A is present.")
  if tss3["control_request_0x08a"]["multiple_physical_sides"]:
    recommendations.append("Resolve why 0x08A appears on both physical sides before assigning message ownership.")
  return recommendations


def build_report(inventory: dict[int, dict[int, MessageStats]], capture_seconds: float, frame_count: int,
                 vehicle: dict[str, Any], firmware: list[dict[str, Any]], metadata: dict[str, Any],
                 log_references: list[dict[str, Any]], cancelled: bool = False) -> dict[str, Any]:
  topology = analyze_topology(inventory, str(vehicle.get("brand", "")))
  enrollment = vehicle_enrollment(vehicle, firmware)
  tss3 = tss3_vehicle_analysis(inventory, capture_seconds, vehicle, topology)
  bus_inventory = {
    str(bus): {f"0x{address:X}": stats.as_dict(capture_seconds) for address, stats in sorted(messages.items())}
    for bus, messages in sorted(inventory.items())
  }
  exact_identity = (vehicle.get("available", False) and vehicle.get("car_fingerprint") not in (None, "", "MOCK")
                    and not vehicle.get("fuzzy_fingerprint", True))
  eps_firmware = any("eps" in entry.get("ecu", "").lower() for entry in firmware)
  signer_traffic = _signer_evidence(inventory, capture_seconds)
  checks = [
    {"name": "physical topology", "passed": topology["gate"] == "PASS", "detail": topology["gate_reason"]},
    {"name": "exact vehicle identity", "passed": bool(exact_identity),
     "detail": "Exact non-fuzzy fingerprint recorded." if exact_identity else "Exact fingerprint is absent, mock, or fuzzy."},
    {"name": "firmware inventory", "passed": bool(firmware),
     "detail": f"Recorded {len(firmware)} cached ECU firmware responses." if firmware else "No cached firmware responses were available."},
    {"name": "EPS firmware identity", "passed": eps_firmware,
     "detail": "EPS firmware identity is present." if eps_firmware else "EPS firmware identity was not found."},
    {"name": "raw CAN capture", "passed": frame_count > 0,
     "detail": f"Recorded {frame_count} received frames." if frame_count else "No frames were recorded."},
  ]
  if tss3["candidate"]:
    control_request = tss3["control_request_0x08a"]
    checks.append({
      "name": "TSS3 CONTROL_REQUEST ownership",
      "passed": control_request["camera_side_only"],
      "detail": (
        "0x08A was observed only on the expected camera/FRC side (bus 2)."
        if control_request["camera_side_only"] else
        f"0x08A ownership is not isolated to bus 2; observed buses: {control_request['observed_buses']}."
      ),
    })
  ready = all(check["passed"] for check in checks)
  recommendations = _capture_recommendations(topology, vehicle, firmware, tss3)
  return {
    "schema": REPORT_SCHEMA,
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "topology": topology,
    "vehicle_enrollment": enrollment,
    "tss3_vehicle_analysis": tss3,
    "capture": {"capture_seconds": round(capture_seconds, 3), "frame_count": frame_count, "cancelled": cancelled,
                "raw_file": "can_capture.jsonl", "buses": bus_inventory},
    "vehicle": vehicle,
    "firmware_inventory": firmware,
    "signer_relevant_traffic": signer_traffic,
    "system_metadata": metadata,
    "recent_log_references": log_references,
    "readiness": {"status": "READY_FOR_AUTHORIZED_LAB_ANALYSIS" if ready else "MORE_DATA_REQUIRED", "checks": checks},
    "recommended_next_capture": recommendations,
    "still_requires_vehicle_specific_lab_work": [
      "authorized ECU firmware or RAM acquisition using vehicle-specific bench procedures",
      "firmware reverse engineering to identify the signature routine, state, and integrity checks",
      "an ECU-specific load method, memory layout, lifetimes, and safe rollback plan",
      "a replayable signature test vector and independently verified output",
      "safety review of relay behavior, bus routing, message ownership, and failure handling",
    ],
    "not_collected": [
      "SecurityAccess secrets, seed/key algorithms, or unlock attempts",
      "ECU memory or firmware dumps",
      "RAM addresses, code caves, or executable injection targets",
      "write/download/routine-control capability tests",
    ],
    "safety_boundary": "Passive receive and existing openpilot metadata only; no CAN transmission or ECU state change.",
  }


def render_markdown(report: dict[str, Any]) -> str:
  topology, vehicle = report["topology"], report["vehicle"]
  enrollment, tss3 = report["vehicle_enrollment"], report["tss3_vehicle_analysis"]
  lines = [
    "# Signer Start research capture", "",
    "## 1. Topology gate — resolve this first", "",
    f"- **Gate:** {topology['gate']}",
    f"- **Classification:** `{topology['status']}`",
    f"- **Validated profile:** `{topology['profile'] or 'none'}`",
    f"- **Confidence:** {topology['confidence']:.1%}",
    f"- **Observed chassis bus:** {topology['observed_chassis_bus']}",
    f"- **Observed camera/ADAS bus:** {topology['observed_camera_bus']}",
    f"- **Decision:** {topology['gate_reason']}", "",
  ]
  lines += [f"- Evidence: {item}" for item in topology["evidence_summary"]]
  lines += [f"- Warning: **{item}**" for item in topology["warnings"]]
  lines += [
    "", "## 2. Per-car enrollment", "",
    f"- Enrollment ID: `{enrollment['enrollment_id']}`",
    f"- Scope: {enrollment['scope']}",
    f"- Identity basis: {', '.join(enrollment['identity_basis'])}",
    f"- TSS3 candidate: `{tss3['candidate']}` — {tss3['candidate_reason']}",
    f"- 0x08A observed buses: `{tss3['control_request_0x08a']['observed_buses']}`",
    f"- 0x08A isolated to camera/FRC bus 2: `{tss3['control_request_0x08a']['camera_side_only']}`", "",
    "## 3. Vehicle identity and cached firmware", "",
    f"- Fingerprint: `{vehicle.get('car_fingerprint', 'unavailable')}`",
    f"- Brand: `{vehicle.get('brand', 'unavailable')}`",
    f"- VIN: `{vehicle.get('vin', 'unavailable')}`",
    f"- Fuzzy fingerprint: `{vehicle.get('fuzzy_fingerprint', 'unavailable')}`",
    f"- Firmware entries: {vehicle.get('firmware_entry_count', 0)}", "",
    "## 4. Passive capture", "",
    f"- Duration: {report['capture']['capture_seconds']:.3f} seconds",
    f"- Received frames: {report['capture']['frame_count']}",
    f"- Cancelled early: {report['capture']['cancelled']}",
    "- Raw stream: `can_capture.jsonl`", "",
    "## 5. Per-car port readiness", "",
  ]
  for check in report["readiness"]["checks"]:
    lines.append(f"- [{'x' if check['passed'] else ' '}] {check['name']}: {check['detail']}")
  lines += ["", f"Overall: **{report['readiness']['status']}**", ""]
  if report["recommended_next_capture"]:
    lines += ["## 6. Recommended next capture", ""]
    lines += [f"- {item}" for item in report["recommended_next_capture"]]
    lines.append("")
  lines += ["## 7. Vehicle-specific lab work still required", ""]
  lines += [f"- {item}" for item in report["still_requires_vehicle_specific_lab_work"]]
  lines += ["", "## Safety and privacy boundary", "",
            "This package contains vehicle identifiers and raw CAN traffic. Keep it private unless deliberately sharing it with a researcher. ",
            "Signer Start is passive: it does not transmit CAN, enter diagnostic sessions, attempt SecurityAccess, dump memory, write RAM/flash, or inject code. ",
            "A topology PASS only permits further authorized lab analysis.", ""]
  return "\n".join(lines)


def _write_json(path: Path, value: Any) -> None:
  temporary = path.with_suffix(path.suffix + ".tmp")
  temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  temporary.replace(path)


def _sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as source:
    while chunk := source.read(1024 * 1024):
      digest.update(chunk)
  return digest.hexdigest()


def _emit_status(output_root: Path, stage: str, title: str, detail: str, progress: int,
                 *, done: bool = False, error: bool = False, archive: str | None = None) -> None:
  status = {"schema": STATUS_SCHEMA, "updated_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
            "stage": stage, "title": title, "detail": detail, "progress": progress, "done": done, "error": error,
            "archive": archive}
  output_root.mkdir(parents=True, exist_ok=True)
  _write_json(output_root / "status.json", status)
  print(json.dumps(status, sort_keys=True), flush=True)


def build_port_seed(report: dict[str, Any]) -> dict[str, Any]:
  """Return the compact, per-car handoff used to start a new port."""
  return {
    "schema": PORT_SEED_SCHEMA,
    "created_utc": report["created_utc"],
    "vehicle_enrollment": report["vehicle_enrollment"],
    "vehicle": report["vehicle"],
    "firmware_match_seed": report["firmware_inventory"],
    "topology": report["topology"],
    "tss3": report["tss3_vehicle_analysis"],
    "readiness": report["readiness"],
    "recommended_next_capture": report["recommended_next_capture"],
    "raw_can_file": report["capture"]["raw_file"],
    "safety_boundary": report["safety_boundary"],
  }


def _write_package(run_dir: Path, report: dict[str, Any], raw_params: dict[str, bytes]) -> Path:
  _write_json(run_dir / "report.json", report)
  _write_json(run_dir / "port_seed.json", build_port_seed(report))
  (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
  for name, raw in raw_params.items():
    (run_dir / name).write_bytes(raw)
  manifest = {}
  for path in sorted(run_dir.iterdir()):
    if path.is_file():
      manifest[path.name] = {"size": path.stat().st_size, "sha256": _sha256_file(path)}
  _write_json(run_dir / "manifest.json", manifest)
  archive = run_dir.with_suffix(".zip")
  with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
    for path in sorted(run_dir.iterdir()):
      if path.is_file():
        zip_file.write(path, arcname=f"{run_dir.name}/{path.name}")
  return archive


def collect_live(duration: float, wait_timeout: float, output_root: Path) -> tuple[Path, dict[str, Any]]:
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params

  output_root.mkdir(parents=True, exist_ok=True)
  params = Params()
  raw_params = {key: value for key in ("CarParamsPersistent", "CarParamsCache", "CarParamsPrevRoute")
                if (value := params.get(key)) is not None}
  raw_cp = raw_params.get("CarParamsPersistent") or raw_params.get("CarParamsCache")
  vehicle, firmware = car_params_summary(raw_cp)
  enrollment = vehicle_enrollment(vehicle, firmware)
  stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
  vehicle_root = output_root / "vehicles" / enrollment["enrollment_id"]
  vehicle_root.mkdir(parents=True, exist_ok=True)
  run_dir = vehicle_root / f"{stamp}-{os.getpid()}"
  run_dir.mkdir(parents=True, exist_ok=False)
  metadata = {
    "platform": platform.platform(), "python": sys.version,
    **{key: _safe_param(params, key) for key in
       ("GitCommit", "GitBranch", "Version", "DongleId", "HardwareSerial", "PandaSignatures", "PandaFirmware")},
  }
  inventory: dict[int, dict[int, MessageStats]] = defaultdict(dict)
  frame_count = 0
  capture_start: float | None = None
  last_status_second = -1
  can_sock = messaging.sub_sock("can", conflate=False, timeout=1000)
  _emit_status(output_root, "waiting_for_can", "Topology capture armed",
               "Start the vehicle while parked. The timed capture begins on the first CAN frame.", 5)
  wait_deadline = time.monotonic() + wait_timeout
  with (run_dir / "can_capture.jsonl").open("w", encoding="utf-8", buffering=1024 * 1024) as raw_can:
    while not _stop_requested:
      now = time.monotonic()
      if capture_start is None and now >= wait_deadline:
        break
      if capture_start is not None and now - capture_start >= duration:
        break
      events = messaging.drain_sock(can_sock, wait_for_one=True)
      if not events:
        continue
      if capture_start is None:
        capture_start = time.monotonic()
        _emit_status(output_root, "capturing_topology", "Capturing topology first",
                     "Recording physical bus roles, overlap, rates, payload lengths, and raw frames.", 15)
      mono_ns = time.monotonic_ns()
      for event in events:
        event_ns = int(event.logMonoTime)
        for message in event.can:
          bus, address, dat = int(message.src), int(message.address), bytes(message.dat)
          inventory[bus].setdefault(address, MessageStats()).add(dat, event_ns or mono_ns)
          raw_can.write(json.dumps({"monotonic_ns": event_ns, "bus": bus, "address": address, "address_hex": f"0x{address:X}",
                                    "data": dat.hex(), "length": len(dat)}, separators=(",", ":")) + "\n")
          frame_count += 1
      elapsed = time.monotonic() - capture_start
      elapsed_second = int(elapsed)
      if elapsed_second != last_status_second and elapsed_second % 5 == 0:
        last_status_second = elapsed_second
        progress = 15 + min(70, int(70 * elapsed / max(duration, 0.1)))
        _emit_status(output_root, "capturing_can", "Passive CAN capture",
                     f"{frame_count} frames recorded; topology remains the first report gate.", progress)

  capture_seconds = 0.0 if capture_start is None else min(time.monotonic() - capture_start, duration)
  _emit_status(output_root, "analyzing", "Analyzing topology",
               "Checking CAN0/CAN2 separation and validated vehicle-family markers before readiness.", 88)
  report = build_report(inventory, capture_seconds, frame_count, vehicle, firmware, metadata,
                        _recent_log_references(), cancelled=_stop_requested)
  raw_files = {f"{key}.bin": value for key, value in raw_params.items()}
  archive = _write_package(run_dir, report, raw_files)
  (vehicle_root / "LATEST").write_text(str(run_dir) + "\n", encoding="utf-8")
  (output_root / "LATEST").write_text(str(run_dir) + "\n", encoding="utf-8")
  return archive, report


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--duration", type=float, default=60.0, help="capture seconds after the first CAN frame")
  parser.add_argument("--wait-timeout", type=float, default=180.0, help="seconds to wait for the first CAN frame")
  parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
  args = parser.parse_args()
  if not 10.0 <= args.duration <= 300.0:
    parser.error("--duration must be between 10 and 300 seconds")
  if not 10.0 <= args.wait_timeout <= 600.0:
    parser.error("--wait-timeout must be between 10 and 600 seconds")
  signal.signal(signal.SIGINT, _request_stop)
  signal.signal(signal.SIGTERM, _request_stop)
  args.output_root.mkdir(parents=True, exist_ok=True)
  lock_path = args.output_root / "capture.lock"
  with lock_path.open("w", encoding="utf-8") as lock_file:
    try:
      fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
      _emit_status(args.output_root, "error", "Capture already running", "Wait for the active Signer Start capture to finish.", 0, error=True)
      return 2
    try:
      archive, report = collect_live(args.duration, args.wait_timeout, args.output_root)
    except Exception as exc:
      _emit_status(args.output_root, "error", "Signer Start failed", f"{type(exc).__name__}: {exc}", 0, error=True)
      return 1
  topology = report["topology"]
  _emit_status(args.output_root, "done", "Research package saved",
               f"Topology {topology['gate']}: {topology['status']}. Package: {archive}", 100, done=True, archive=str(archive))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
