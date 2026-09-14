"""Startup-safe helpers for StarPilot's persisted vehicle override."""

from __future__ import annotations

from collections.abc import Callable


def apply_persisted_manual_fingerprint(toggles, params, normalize: Callable[[object], str | None], mock_model: str) -> None:
  """Refresh the manual platform choice before the vehicle interface is selected."""
  persisted_car_model = normalize(params.get("CarModel"))
  toggles.force_fingerprint = bool(
    params.get_bool("ForceFingerprint") and
    persisted_car_model and persisted_car_model != mock_model
  )
  if toggles.force_fingerprint:
    toggles.car_model = persisted_car_model
