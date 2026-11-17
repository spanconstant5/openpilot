import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opendbc.car.toyota.values import CAR

from openpilot.selfdrive.car.toyota_tss3_oracle_kit import (
  DEFAULT_ORACLE_TOOL,
  oracle_kit_compatibility,
  oracle_ui_state,
  tss3_fingerprints,
)
from openpilot.selfdrive.ui.tss3_oracle_runner import TOOL_PATH as UI_TOOL_PATH


class TestToyotaTss3OracleKit(unittest.TestCase):
  @staticmethod
  def make_tool(root: Path, target: str) -> Path:
    tool = root / "tss3-request-signer"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    bundle = root / "bundle"
    bundle.mkdir()
    (bundle / "request_signer.json").write_text(json.dumps({"target": {"name": target}}), encoding="utf-8")
    return tool

  def test_default_kit_is_self_contained_in_checkout(self):
    compatible, detail = oracle_kit_compatibility(DEFAULT_ORACLE_TOOL)
    self.assertTrue(compatible, detail)
    payload = (DEFAULT_ORACLE_TOOL.parent / "bundle/payload.bin").read_bytes()
    self.assertEqual(len(payload), 0x1000)
    self.assertEqual(hashlib.sha256(payload).hexdigest(),
                     "6234bb5bd496a82fabb32c27b56b3db0f1907b5bf6482e4c19f8835153ff69fc")
    self.assertEqual(UI_TOOL_PATH, DEFAULT_ORACLE_TOOL)

  def test_accepts_structurally_valid_target_kit(self):
    with tempfile.TemporaryDirectory() as td:
      tool = self.make_tool(Path(td), "corolla-8965F1208000")
      self.assertEqual(oracle_kit_compatibility(tool), (True, ""))

  def test_rejects_missing_or_invalid_metadata(self):
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      tool = self.make_tool(root, "corolla-8965F1208000")
      (root / "bundle/request_signer.json").write_bytes(b"{")
      compatible, detail = oracle_kit_compatibility(tool)
      self.assertFalse(compatible)
      self.assertTrue(detail.startswith("oracle kit metadata invalid:"))

  def test_rejects_unavailable_tool(self):
    with tempfile.TemporaryDirectory() as td:
      compatible, detail = oracle_kit_compatibility(Path(td) / "tss3-request-signer")
      self.assertFalse(compatible)
      self.assertTrue(detail.startswith("oracle tool unavailable:"))

  def test_tss3_fingerprints_follow_platform_flags(self):
    fingerprints = tss3_fingerprints()
    self.assertIn(CAR.TOYOTA_COROLLA_TSS3, fingerprints)
    self.assertNotIn(CAR.TOYOTA_COROLLA_TSS2, fingerprints)

  def test_developer_diagnostic_is_always_visible_but_fails_closed(self):
    for is_release in (False, True):
      self.assertEqual(oracle_ui_state("MOCK", is_release=is_release, tool_available=True),
                       (True, False, "CHECK HARNESS"))
      self.assertEqual(oracle_ui_state("MOCK", is_release=is_release, tool_available=False),
                       (True, False, "CHECK HARNESS"))

  def test_only_live_tss3_fingerprint_can_arm(self):
    fingerprint = next(iter(tss3_fingerprints()))
    self.assertEqual(oracle_ui_state(fingerprint, is_release=False, tool_available=True),
                     (True, True, "ARM"))
    self.assertEqual(oracle_ui_state(fingerprint, is_release=False, tool_available=False),
                     (True, True, "KIT MISSING"))


if __name__ == "__main__":
  unittest.main()
