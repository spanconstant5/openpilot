from __future__ import annotations

import json
from pathlib import Path

import pytest

from openpilot.selfdrive.car import toyota_tss3_request_signer as signer


def _make_kit(tmp_path: Path, monkeypatch) -> Path:
  tool = tmp_path / "tss3-request-signer"
  tool.write_text("#!/bin/sh\ncase \"$1\" in ui-bringup) exit 0 ;; esac\nexit 0\n", encoding="utf-8")
  tool.chmod(0o755)
  host = tmp_path / "runtime" / "tsk" / "ram_runtime" / "tss3_request_signer.py"
  host.parent.mkdir(parents=True)
  host.write_bytes(b"host")
  (host.parent / "tss3_request_signer_ui_bringup.py").write_bytes(b"ui bringup")
  payload = tmp_path / "bundle" / "payload.bin"
  payload.parent.mkdir()
  payload.write_bytes(b"payload")
  host_hash = signer._sha256(host)
  ui_bringup_hash = signer._sha256(host.parent / "tss3_request_signer_ui_bringup.py")
  launcher_hash = signer._sha256(tool)
  payload_hash = signer._sha256(payload)
  (tmp_path / "bundle" / "request_signer.json").write_text(json.dumps({
    "schema": signer.EXPECTED_KIT_SCHEMA,
    "authenticated_payload": {"sha256": payload_hash},
    "request": {"bus": 0, "can_id": "0x00000777", "codec": "four-frame", "carrier": "functional-nibble4"},
    "response": {"bus": 0, "can_id": "0x000007A9"},
    "target": {"name": signer.EXPECTED_TARGET, "application_f181_hex": signer.EXPECTED_APPLICATION_F181},
  }), encoding="utf-8")
  monkeypatch.setattr(signer, "EXPECTED_HOST_SHA256", host_hash)
  monkeypatch.setattr(signer, "EXPECTED_UI_BRINGUP_SHA256", ui_bringup_hash)
  monkeypatch.setattr(signer, "EXPECTED_LAUNCHER_SHA256", launcher_hash)
  monkeypatch.setattr(signer, "EXPECTED_RUNTIME_SOURCE_SHA256", signer._runtime_source_sha256(tmp_path / "runtime"))
  monkeypatch.setattr(signer, "EXPECTED_PAYLOAD_SHA256", payload_hash)
  return tool


@pytest.mark.parametrize("fingerprint,can_valid,onroad,expected", [
  (signer.COROLLA_TSS3_MODEL, False, False, False),
  (signer.COROLLA_TSS3_MODEL, True, False, False),
  (signer.COROLLA_TSS3_MODEL, False, True, False),
  (signer.COROLLA_TSS3_MODEL, True, True, True),
  ("MOCK", False, False, True),
])
def test_startup_bridge_release_requires_live_onroad_corolla(fingerprint, can_valid, onroad, expected):
  assert signer.tss3_startup_bridge_release_ready(fingerprint, can_valid, onroad) is expected


def test_startup_bridge_file_is_token_validated(tmp_path, monkeypatch):
  request_path = tmp_path / "request"
  ready_path = tmp_path / "ready"
  monkeypatch.setattr(signer, "TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH", request_path)
  monkeypatch.setattr(signer, "TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH", ready_path)

  assert not signer.tss3_startup_bridge_active()
  request_path.write_text("old-token\n", encoding="utf-8")
  ready_path.write_text("old-token\n", encoding="utf-8")
  assert signer.tss3_startup_bridge_active()
  assert signer.tss3_startup_bridge_token() == "old-token"

  signer.release_tss3_startup_bridge("new-token")
  assert request_path.exists()
  assert ready_path.exists()

  signer.release_tss3_startup_bridge("old-token")
  assert not request_path.exists()
  assert not ready_path.exists()


def test_compatibility_accepts_exact_corolla_kit(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)
  assert signer.request_signer_kit_compatibility(tool).compatible


def test_compatibility_rejects_revoked_corolla_payload(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)
  meta_path = tmp_path / "bundle" / "request_signer.json"
  meta = json.loads(meta_path.read_text())
  meta["authenticated_payload"]["sha256"] = next(iter(signer.REVOKED_PAYLOAD_SHA256S))
  meta_path.write_text(json.dumps(meta))

  check = signer.request_signer_kit_compatibility(tool)

  assert not check.compatible
  assert "payload revoked" in check.detail
  assert "successor payload" in check.detail


@pytest.mark.parametrize("relative_path,detail", [
  ("tss3-request-signer", "launcher hash mismatch"),
  ("runtime/tsk/ram_runtime/tss3_request_signer_ui_bringup.py", "UI bringup hash mismatch"),
])
def test_compatibility_rejects_modified_entrypoints(tmp_path, monkeypatch, relative_path, detail):
  tool = _make_kit(tmp_path, monkeypatch)
  path = tmp_path / relative_path
  path.write_bytes(path.read_bytes() + b"\n# modified\n")

  check = signer.request_signer_kit_compatibility(tool)

  assert not check.compatible
  assert detail in check.detail


def test_compatibility_rejects_modified_runtime_dependency(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)
  dependency = tmp_path / "runtime" / "tsk" / "common" / "ram_exec.py"
  dependency.parent.mkdir(parents=True)
  dependency.write_text("raise RuntimeError('modified')\n", encoding="utf-8")

  check = signer.request_signer_kit_compatibility(tool)

  assert not check.compatible
  assert "runtime source hash mismatch" in check.detail


def test_compatibility_rejects_camry_target(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)
  meta_path = tmp_path / "bundle" / "request_signer.json"
  meta = json.loads(meta_path.read_text())
  meta["target"]["name"] = "camry-8965F3307000"
  meta_path.write_text(json.dumps(meta))
  check = signer.request_signer_kit_compatibility(tool)
  assert not check.compatible
  assert "Wrong signer target" in check.detail


def test_install_requires_live_probe_verdict(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)

  def fake_run(command, **_kwargs):
    if command[1] == "install":
      Path(command[2]).write_text(json.dumps({
        "schema": "tss3-request-signer-install-v1",
        "verdict": "request_signer_live_probe_failed",
      }))
    return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

  monkeypatch.setattr(signer.subprocess, "run", fake_run)
  result = signer.run_request_signer_install(tool, tmp_path / "runs")
  assert not result.passed
  assert result.title == "RAM signer live probe failed"


def test_install_passes_and_cycles_controls(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)
  requested = []

  def fake_run(command, **_kwargs):
    if command[1] == "install":
      Path(command[2]).write_text(json.dumps({
        "schema": "tss3-request-signer-install-v1",
        "verdict": signer.PASS_VERDICT,
        "signer_probe": {"elapsed_ms": 8.506},
      }))
    return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

  class FakeParams:
    def put_bool(self, key, value):
      requested.append((key, value))

  monkeypatch.setattr(signer.subprocess, "run", fake_run)
  monkeypatch.setattr(signer, "Params", FakeParams)
  result = signer.run_request_signer_install(tool, tmp_path / "runs")
  assert result.passed
  assert "8.51 ms" in result.detail
  assert requested == [("OnroadCycleRequested", True)]


def test_install_fails_safe_when_controls_cycle_cannot_be_requested(tmp_path, monkeypatch):
  tool = _make_kit(tmp_path, monkeypatch)

  def fake_run(command, **_kwargs):
    if command[1] == "install":
      Path(command[2]).write_text(json.dumps({
        "schema": "tss3-request-signer-install-v1",
        "verdict": signer.PASS_VERDICT,
      }))
    return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

  class BrokenParams:
    def put_bool(self, _key, _value):
      raise OSError("params unavailable")

  monkeypatch.setattr(signer.subprocess, "run", fake_run)
  monkeypatch.setattr(signer, "Params", BrokenParams)
  result = signer.run_request_signer_install(tool, tmp_path / "runs")
  assert not result.passed
  assert result.title == "RAM signer live; controls cycle failed"
  assert "Do not drive" in result.detail
