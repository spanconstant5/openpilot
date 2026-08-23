import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpilot.tools.eps_telescope.export import create_export_bundle
from openpilot.tools.eps_telescope.runner import MODE_DEEP, MODE_SECURITY, MODE_UDS, ProbeConfig, run_probe, summarize_report
from openpilot.tools.eps_telescope.safety import vehicle_is_safe_for_probe
from openpilot.tools.eps_telescope.upstream import PAYLOAD_SHA256, load_payload
from opendbc.car.structs import car


class FakeUds:
  def __init__(self):
    self.sessions = []

  def read_data_by_identifier(self, _did):
    return b"EPS-F181"

  def diagnostic_session_control(self, session):
    self.sessions.append(session)


class FakeTransport:
  def __init__(self, sa_ok=True):
    self.uds = FakeUds()
    self.panda = object()
    self.bus = 0
    self.sa_ok = sa_ok
    self.security_calls = 0

  def __enter__(self):
    return self

  def __exit__(self, *_args):
    return None

  def security_access(self):
    self.security_calls += 1
    return self.sa_ok, None if self.sa_ok else 0x35


class TestRunner(unittest.TestCase):
  def setUp(self):
    self.transport = FakeTransport()
    self.calls = {"sessions": None, "routines": 0, "download": 0, "deep": 0}
    self.patches = [
      patch("openpilot.tools.eps_telescope.runner.uds_probe.probe_sessions", side_effect=self._sessions),
      patch("openpilot.tools.eps_telescope.runner.uds_probe.probe_dids", return_value=[]),
      patch("openpilot.tools.eps_telescope.runner.uds_probe.probe_routines", side_effect=self._routines),
      patch("openpilot.tools.eps_telescope.runner.uds_probe.probe_download_acceptance", side_effect=self._download),
      patch("openpilot.tools.eps_telescope.runner._run_deep", side_effect=self._deep),
    ]
    for active_patch in self.patches:
      active_patch.start()

  def tearDown(self):
    for active_patch in reversed(self.patches):
      active_patch.stop()

  def _sessions(self, _transport, sessions):
    self.calls["sessions"] = sessions
    return []

  def _routines(self, _transport):
    self.calls["routines"] += 1
    return []

  def _download(self, _transport):
    self.calls["download"] += 1
    return {}

  def _deep(self, _transport, _payload, _scan_egg):
    self.calls["deep"] += 1
    return {
      "envelope_ok": True,
      "classification": {"classification": "verified_variant"},
    }

  def _run(self, mode, tmp_path):
    config = ProbeConfig(mode=mode, fingerprint_vehicle=False, artifacts_dir=str(tmp_path))
    return run_probe(config, payload=b"payload", transport_factory=lambda: self.transport)

  def test_uds_mode_never_enters_protected_layers(self):
    with self.subTest(), __import__("tempfile").TemporaryDirectory() as tmp:
      self._run(MODE_UDS, tmp)
    self.assertEqual(self.calls["sessions"], [1])
    self.assertEqual(self.transport.security_calls, 0)
    self.assertEqual(self.calls["routines"], 0)
    self.assertEqual(self.calls["download"], 0)
    self.assertEqual(self.calls["deep"], 0)

  def test_security_mode_never_enters_programming_or_uploads(self):
    with __import__("tempfile").TemporaryDirectory() as tmp:
      self._run(MODE_SECURITY, tmp)
    self.assertEqual(self.calls["sessions"], [1, 3])
    self.assertEqual(self.transport.security_calls, 1)
    self.assertEqual(self.calls["routines"], 1)
    self.assertEqual(self.calls["download"], 0)
    self.assertEqual(self.calls["deep"], 0)

  def test_deep_mode_is_the_only_mode_that_uploads(self):
    with __import__("tempfile").TemporaryDirectory() as tmp:
      output = self._run(MODE_DEEP, tmp)
      payload = json.loads((output / "probe.json").read_text())
    self.assertEqual(self.calls["sessions"], [1, 3, 2])
    self.assertEqual(self.transport.security_calls, 1)
    self.assertEqual(self.calls["download"], 1)
    self.assertEqual(self.calls["deep"], 1)
    self.assertEqual(payload["classification"]["classification"], "verified_variant")

  def test_every_mode_restores_default_session(self):
    with __import__("tempfile").TemporaryDirectory() as tmp:
      self._run(MODE_SECURITY, tmp)
    self.assertEqual(self.transport.uds.sessions[-1], 1)

  def test_failure_still_restores_default_session(self):
    with patch("openpilot.tools.eps_telescope.runner.uds_probe.probe_dids", side_effect=RuntimeError("timeout")):
      with __import__("tempfile").TemporaryDirectory() as tmp, self.assertRaisesRegex(RuntimeError, "timeout"):
        self._run(MODE_SECURITY, tmp)
    self.assertEqual(self.transport.uds.sessions[-1], 1)

  def test_failed_security_access_blocks_deep_probe(self):
    self.transport.sa_ok = False
    with __import__("tempfile").TemporaryDirectory() as tmp:
      output = self._run(MODE_DEEP, tmp)
      payload = json.loads((output / "probe.json").read_text())
    self.assertEqual(self.calls["deep"], 0)
    self.assertFalse(payload["layer2"]["sa_ok"])
    self.assertIsNone(payload["layer3"])

  def test_summary_recommends_power_cycle_after_deep(self):
    with __import__("tempfile").TemporaryDirectory() as tmp:
      output = self._run(MODE_DEEP, tmp)
      summary = summarize_report(output / "probe.json", MODE_DEEP)
    self.assertTrue(summary["power_cycle_recommended"])
    self.assertEqual(summary["outcome"], "verified_variant")

  def test_pinned_payload_digest(self):
    payload = load_payload()
    self.assertEqual(len(payload), 1964)
    self.assertEqual(hashlib.sha256(payload).hexdigest(), PAYLOAD_SHA256)

  def test_export_bundle_contains_both_reports_and_privacy_manifest(self):
    with __import__("tempfile").TemporaryDirectory() as tmp:
      output = self._run(MODE_UDS, tmp)
      export_root = output.parent / "exports"
      bundle = create_export_bundle(output, export_root)
      self.assertTrue(bundle.name.endswith(".eps-telescope.zip"))
      with ZipFile(bundle) as archive:
        self.assertEqual(set(archive.namelist()), {"probe.json", "probe.md", "export_manifest.json"})
        manifest = json.loads(archive.read("export_manifest.json"))
      self.assertTrue(manifest["contains_vehicle_identifiers"])


class TestSafetyGate(unittest.TestCase):
  def setUp(self):
    self.car_state = SimpleNamespace(
      vEgo=0.0,
      standstill=True,
      gearShifter=car.CarState.GearShifter.park,
    )
    self.selfdrive_state = SimpleNamespace(enabled=False)

  def test_allows_stationary_parked_disengaged_vehicle(self):
    safe, reason = vehicle_is_safe_for_probe(True, self.car_state, self.selfdrive_state)
    self.assertTrue(safe)
    self.assertEqual(reason, "")

  def test_rejects_moving_vehicle(self):
    self.car_state.vEgo = 1.0
    self.car_state.standstill = False
    safe, _ = vehicle_is_safe_for_probe(True, self.car_state, self.selfdrive_state)
    self.assertFalse(safe)

  def test_rejects_non_park_gear(self):
    self.car_state.gearShifter = car.CarState.GearShifter.drive
    safe, _ = vehicle_is_safe_for_probe(True, self.car_state, self.selfdrive_state)
    self.assertFalse(safe)

  def test_rejects_engaged_openpilot(self):
    self.selfdrive_state.enabled = True
    safe, _ = vehicle_is_safe_for_probe(True, self.car_state, self.selfdrive_state)
    self.assertFalse(safe)

  def test_rejects_stale_or_missing_state(self):
    safe, _ = vehicle_is_safe_for_probe(True, self.car_state, self.selfdrive_state, data_valid=False)
    self.assertFalse(safe)
