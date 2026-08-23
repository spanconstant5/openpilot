"""Shared stationary/parked gate for starting an EPS Telescope run."""

from __future__ import annotations

from opendbc.car.structs import car


MAX_START_SPEED = 0.05


def vehicle_is_safe_for_probe(started: bool, car_state, selfdrive_state, data_valid: bool = True) -> tuple[bool, str]:
  if not started:
    return False, "Turn the ignition on while remaining in Park."
  if not data_valid:
    return False, "Waiting for current vehicle state."
  if selfdrive_state.enabled:
    return False, "Disengage openpilot before running EPS Telescope."
  if abs(float(car_state.vEgo)) > MAX_START_SPEED or not car_state.standstill:
    return False, "The vehicle must be completely stationary."
  if car_state.gearShifter != car.CarState.GearShifter.park:
    return False, "Shift the vehicle into Park."
  return True, ""
