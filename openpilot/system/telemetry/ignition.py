from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def ignition_state(panda_states: Iterable[Any]) -> bool | None:
  """Return ignition for known pandas, or None until a real panda state is available."""
  known = [state for state in panda_states if str(state.pandaType).rsplit(".", 1)[-1] != "unknown"]
  if not known:
    return None
  return any(bool(state.ignitionLine or state.ignitionCan) for state in known)
