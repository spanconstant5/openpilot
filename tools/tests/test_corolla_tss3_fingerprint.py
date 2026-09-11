import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


NAMESPACE = runpy.run_path(Path(__file__).resolve().parents[1] / "corolla_tss3_fingerprint.py")
MIN_CAPTURE_FRAMES = NAMESPACE["MIN_CAPTURE_FRAMES"]
build_candidate = NAMESPACE["build_candidate"]
render = NAMESPACE["render"]


def event(*messages):
  return SimpleNamespace(which=lambda: "can", can=list(messages))


def message(address, dlc, bus=0):
  return SimpleNamespace(address=address, dat=bytes(dlc), src=bus)


def test_candidate_keeps_all_eligible_addresses_and_reports_convergence():
  first = [event(message(0x25, 32), message(0x7DF, 8), message(0x900, 8))] * MIN_CAPTURE_FRAMES
  second = [event(message(0x25, 32), message(0xAA, 8))] * MIN_CAPTURE_FRAMES
  candidate = build_candidate((first, second), bus=0)

  assert candidate.fingerprint == {0x25: 32, 0xAA: 8}
  assert candidate.new_addresses_last_log == (0xAA,)
  assert "NOT CONVERGED" in render(candidate, bus=0, log_count=2)


def test_candidate_rejects_short_or_changing_dlc_capture():
  with pytest.raises(ValueError, match="too short"):
    build_candidate(([event(message(0x25, 32))],), bus=0)

  unstable = [event(message(0x25, 32), message(0x25, 8))] * MIN_CAPTURE_FRAMES
  with pytest.raises(ValueError, match="DLC changed"):
    build_candidate((unstable,), bus=0)
