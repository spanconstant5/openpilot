from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ControlBarState:
  value: float
  analog: bool
  driver_override: bool
  automation_active: bool = False
  source_label: str | None = None


@dataclass(frozen=True)
class HybridState:
  battery_percent: float | None = None
  power_kw: float | None = None
  ev_mode: bool | None = None
  power_flow: str | None = None


class VehicleSignalProvider(Protocol):
  """Extension point for reviewed, vehicle-specific read-only signals."""

  def throttle_brake_states(self, car_state) -> tuple[ControlBarState, ControlBarState]: ...
  def engine_rpm(self, car_state) -> float | None: ...
  def hybrid_state(self, car_state) -> HybridState | None: ...
  def stock_assistance_state(self, car_state) -> str | None: ...


class GenericSignalProvider:
  """Values available from the generic CarState schema in this checkout."""

  def __init__(self):
    self._gas_analog_seen = False
    self._brake_analog_seen = False
    self._rpm_seen = False

  def throttle_brake_states(self, car_state) -> tuple[ControlBarState, ControlBarState]:
    gas_value = max(0.0, min(1.0, float(car_state.deprecated.gas)))
    brake_value = max(0.0, min(1.0, float(car_state.deprecated.brake)))
    self._gas_analog_seen = self._gas_analog_seen or gas_value > 0.0
    self._brake_analog_seen = self._brake_analog_seen or brake_value > 0.0
    gas_pressed = bool(car_state.gasPressed)
    brake_pressed = bool(car_state.brakePressed)
    throttle = ControlBarState(gas_value if self._gas_analog_seen else float(gas_pressed), self._gas_analog_seen, gas_pressed)
    brake = ControlBarState(brake_value if self._brake_analog_seen else float(brake_pressed), self._brake_analog_seen, brake_pressed)
    return throttle, brake

  def engine_rpm(self, car_state) -> float | None:
    rpm = float(car_state.deprecated.engineRpm)
    self._rpm_seen = self._rpm_seen or rpm > 0.0
    return max(0.0, rpm) if self._rpm_seen else None

  def hybrid_state(self, car_state) -> HybridState | None:
    # TODO: implement only after reviewed Toyota/opendbc signals expose hybrid
    # battery state, EV mode, and power flow with an explicit availability bit.
    return None

  def stock_assistance_state(self, car_state) -> str | None:
    # TODO: implement only after stock TSS state is decoded and reviewed in
    # opendbc. Generic openpilot engagement must not be labeled as stock TSS.
    return None


class ToyotaSignalProvider(GenericSignalProvider):
  """Toyota states already decoded by opendbc; no speculative CAN reads."""

  def throttle_brake_states(self, car_state) -> tuple[ControlBarState, ControlBarState]:
    throttle, brake = super().throttle_brake_states(car_state)
    stock_aeb = bool(car_state.stockAeb)
    if stock_aeb and not brake.driver_override:
      brake = ControlBarState(max(brake.value, 1.0), brake.analog, False, True, "TSS AEB")
    return throttle, brake

  def stock_assistance_state(self, car_state) -> str | None:
    if car_state.stockAeb:
      return "TSS AEB"
    if car_state.cruiseState.enabled:
      return "TSS CRUISE ACTIVE"
    if car_state.cruiseState.available:
      return "TSS READY"
    return "TSS OFF"


def signal_provider_for_brand(brand: str | None) -> VehicleSignalProvider:
  return ToyotaSignalProvider() if brand == "toyota" else GenericSignalProvider()
