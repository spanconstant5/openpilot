from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKU_PATH = Path(__file__).resolve().parents[2] / "sku" / "active.json"


@dataclass(frozen=True)
class TskSkuProfile:
  profile_id: str
  vehicle: str
  model_years: str
  harness_variant: str
  status: str
  passive_only: bool
  read_only_dbc: str | None = None
  read_only_bus: int | None = None
  pin_map_status: str = "not_applicable"

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> TskSkuProfile:
    profile = cls(
      profile_id=str(data["profile_id"]),
      vehicle=str(data["vehicle"]),
      model_years=str(data["model_years"]),
      harness_variant=str(data["harness_variant"]),
      status=str(data["status"]),
      passive_only=bool(data["passive_only"]),
      read_only_dbc=data.get("read_only_dbc"),
      read_only_bus=int(data["read_only_bus"]) if data.get("read_only_bus") is not None else None,
      pin_map_status=str(data.get("pin_map_status", "not_applicable")),
    )
    if profile.harness_variant not in {"stock", "pinswap"}:
      raise ValueError(f"unsupported harness variant: {profile.harness_variant}")
    if not profile.passive_only:
      raise ValueError("TSK SKU profiles must remain passive-only until vehicle and panda safety review is complete")
    if profile.harness_variant == "pinswap" and profile.pin_map_status != "verified":
      # An unverified pinswap profile may exist for research/documentation, but it
      # must never select a CAN decoder or imply an installable wiring map.
      if profile.read_only_dbc is not None or profile.read_only_bus is not None:
        raise ValueError("unverified pinswap profile cannot select a CAN decoder")
    return profile


def load_tsk_sku(path: Path = SKU_PATH) -> TskSkuProfile | None:
  if not path.is_file():
    return None
  data = json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(data, dict):
    raise ValueError("TSK SKU profile must be a JSON object")
  return TskSkuProfile.from_dict(data)
