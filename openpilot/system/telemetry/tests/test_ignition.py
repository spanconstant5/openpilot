from types import SimpleNamespace

from openpilot.system.telemetry.ignition import ignition_state


def panda(panda_type="tres", line=False, can=False):
  return SimpleNamespace(pandaType=panda_type, ignitionLine=line, ignitionCan=can)


def test_ignition_state_ignores_unknown_or_missing_pandas():
  assert ignition_state([]) is None
  assert ignition_state([panda("unknown", line=True)]) is None


def test_ignition_state_accepts_either_hardware_source():
  assert ignition_state([panda(line=True)]) is True
  assert ignition_state([panda(can=True)]) is True
  assert ignition_state([panda()]) is False
