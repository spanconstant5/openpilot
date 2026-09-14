import runpy
from pathlib import Path
from types import SimpleNamespace


NAMESPACE = runpy.run_path(
  Path(__file__).resolve().parents[2] / "starpilot/common/manual_fingerprint.py"
)
apply_persisted_manual_fingerprint = NAMESPACE["apply_persisted_manual_fingerprint"]


class PersistedParams:
  def __init__(self, force: bool, model: str):
    self.force = force
    self.model = model

  def get_bool(self, key):
    assert key == "ForceFingerprint"
    return self.force

  def get(self, key):
    assert key == "CarModel"
    return self.model


def normalize(value):
  return value.decode() if isinstance(value, bytes) else value


def test_persisted_corolla_replaces_stale_mock_snapshot():
  toggles = SimpleNamespace(force_fingerprint=False, car_model="MOCK")

  apply_persisted_manual_fingerprint(
    toggles,
    PersistedParams(True, "TOYOTA_COROLLA_TSS3"),
    normalize,
    "MOCK",
  )

  assert toggles.force_fingerprint is True
  assert toggles.car_model == "TOYOTA_COROLLA_TSS3"


def test_default_mock_cannot_be_forced_as_a_supported_vehicle():
  toggles = SimpleNamespace(force_fingerprint=True, car_model="TOYOTA_COROLLA_TSS3")

  apply_persisted_manual_fingerprint(
    toggles,
    PersistedParams(True, b"MOCK"),
    normalize,
    "MOCK",
  )

  assert toggles.force_fingerprint is False
  assert toggles.car_model == "TOYOTA_COROLLA_TSS3"
