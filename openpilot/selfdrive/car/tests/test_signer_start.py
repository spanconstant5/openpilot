import json
import zipfile
from pathlib import Path

from openpilot.selfdrive.car.signer_start import MessageStats, _write_package, analyze_topology, build_report, render_markdown


def stats(count: int = 100) -> MessageStats:
  value = MessageStats(count=count)
  value.lengths[8] = count
  return value


def inventory(bus0: list[int], bus2: list[int]) -> dict[int, dict[int, MessageStats]]:
  return {
    0: {address: stats() for address in bus0},
    2: {address: stats() for address in bus2},
  }


CHASSIS = [0x030, 0x0AA, 0x101, 0x116, 0x260]
CAMERA = [0x08A, 0x180, 0x181, 0x182, 0x183]


def test_topology_standard() -> None:
  result = analyze_topology(inventory(CHASSIS, CAMERA), "toyota")
  assert result["gate"] == "PASS"
  assert result["status"] == "resolved_standard"
  assert result["observed_chassis_bus"] == 0
  assert result["observed_camera_bus"] == 2


def test_topology_reversed_is_blocked() -> None:
  result = analyze_topology(inventory(CAMERA, CHASSIS), "toyota")
  assert result["gate"] == "BLOCK"
  assert result["status"] == "resolved_reversed"
  assert result["observed_chassis_bus"] == 2
  assert result["observed_camera_bus"] == 0


def test_topology_bridged_is_blocked_before_marker_classification() -> None:
  mirrored = CHASSIS + CAMERA
  result = analyze_topology(inventory(mirrored, mirrored), "toyota")
  assert result["gate"] == "BLOCK"
  assert result["status"] == "bridged_or_mirrored"
  assert result["observed_chassis_bus"] is None


def test_unknown_brand_requires_profile() -> None:
  result = analyze_topology(inventory(CHASSIS, CAMERA), "some-new-brand")
  assert result["gate"] == "BLOCK"
  assert result["status"] == "profile_needed"
  assert result["profile"] is None


def test_receipt_buses_cannot_win_topology() -> None:
  data = inventory(CHASSIS, CAMERA)
  data[128] = {address: stats(10000) for address in CAMERA + CHASSIS}
  result = analyze_topology(data, "toyota")
  assert result["gate"] == "PASS"
  assert result["observed_chassis_bus"] == 0
  assert result["observed_camera_bus"] == 2


def test_report_puts_topology_first_and_never_claims_injection_readiness(tmp_path: Path) -> None:
  vehicle = {
    "available": True,
    "brand": "toyota",
    "car_fingerprint": "TEST CAR",
    "fuzzy_fingerprint": False,
    "firmware_entry_count": 1,
  }
  firmware = [{"ecu": "eps", "address": "0x7A1"}]
  report = build_report(inventory(CHASSIS, CAMERA), 60.0, 1000, vehicle, firmware, {}, [])
  markdown = render_markdown(report)

  assert markdown.index("Topology gate") < markdown.index("Vehicle identity")
  assert report["readiness"]["status"] == "READY_FOR_AUTHORIZED_LAB_ANALYSIS"
  assert "injection package" not in report["readiness"]["status"].lower()
  assert report["still_requires_vehicle_specific_lab_work"]
  assert report["not_collected"]

  run_dir = tmp_path / "capture"
  run_dir.mkdir()
  (run_dir / "can_capture.jsonl").write_text('{"bus":0}\n', encoding="utf-8")
  archive = _write_package(run_dir, report, {"CarParamsPersistent.bin": b"params"})
  manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
  assert "can_capture.jsonl" in manifest
  assert "report.md" in manifest
  with zipfile.ZipFile(archive) as package:
    assert f"{run_dir.name}/report.json" in package.namelist()
