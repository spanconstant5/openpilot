import json
import unittest

from openpilot.common.tsk_sku import load_tsk_sku


def test_load_verified_passive_profile(tmp_path):
  path = tmp_path / "active.json"
  path.write_text(json.dumps({
    "profile_id": "corolla-stock",
    "vehicle": "Toyota Corolla Hybrid LE",
    "model_years": "2025",
    "harness_variant": "stock",
    "status": "log_verified_read_only",
    "passive_only": True,
    "read_only_dbc": "toyota_secoc_pt_generated",
    "read_only_bus": 1,
  }), encoding="utf-8")

  profile = load_tsk_sku(path)

  assert profile is not None
  assert profile.read_only_bus == 1
  assert profile.passive_only


def test_unverified_pinswap_cannot_select_decoder(tmp_path):
  path = tmp_path / "active.json"
  path.write_text(json.dumps({
    "profile_id": "corolla-pinswap",
    "vehicle": "Toyota Corolla Hybrid LE",
    "model_years": "2025",
    "harness_variant": "pinswap",
    "status": "blocked",
    "passive_only": True,
    "pin_map_status": "unverified",
    "read_only_dbc": "toyota_secoc_pt_generated",
    "read_only_bus": 1,
  }), encoding="utf-8")

  with unittest.TestCase().assertRaisesRegex(ValueError, "cannot select a CAN decoder"):
    load_tsk_sku(path)


def test_active_control_profile_is_rejected(tmp_path):
  path = tmp_path / "active.json"
  path.write_text(json.dumps({
    "profile_id": "unsafe",
    "vehicle": "Toyota",
    "model_years": "2026",
    "harness_variant": "stock",
    "status": "unverified",
    "passive_only": False,
  }), encoding="utf-8")

  with unittest.TestCase().assertRaisesRegex(ValueError, "must remain passive-only"):
    load_tsk_sku(path)
