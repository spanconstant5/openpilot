from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from openpilot.system.telemetry.toyota_decoder import ToyotaExtras
from openpilot.common.tsk_sku import load_tsk_sku


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

  def refresh(self) -> None: ...
  def vehicle_speed_mps(self, car_state) -> float | None: ...
  def steering_angle_deg(self, car_state) -> float | None: ...
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

  def refresh(self) -> None:
    pass

  def vehicle_speed_mps(self, car_state) -> float | None:
    if car_state is None:
      return None
    cluster_speed = float(car_state.vEgoCluster)
    return max(0.0, cluster_speed if cluster_speed != 0.0 else float(car_state.vEgo))

  def steering_angle_deg(self, car_state) -> float | None:
    return float(car_state.steeringAngleDeg) if car_state is not None else None

  def throttle_brake_states(self, car_state) -> tuple[ControlBarState, ControlBarState]:
    if car_state is None:
      return ControlBarState(0.0, False, False), ControlBarState(0.0, False, False)
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
    if car_state is None:
      return None
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

  def __init__(self, raw_fallback: bool = False):
    super().__init__()
    self.raw_fallback = raw_fallback
    self.raw = ToyotaExtras()
    self._raw_decoder = None
    self._can_sock = None
    self._raw_initialization_attempted = False

  def refresh(self) -> None:
    if not self.raw_fallback:
      return
    if not self._raw_initialization_attempted:
      self._raw_initialization_attempted = True
      try:
        from cereal import messaging
        from openpilot.system.telemetry.toyota_decoder import ToyotaExtrasDecoder

        sku_profile = load_tsk_sku()
        dbc_name = sku_profile.read_only_dbc if sku_profile is not None else "toyota_secoc_pt_generated"
        bus = sku_profile.read_only_bus if sku_profile is not None else 0
        if dbc_name is not None:
          self._raw_decoder = ToyotaExtrasDecoder(dbc_name=dbc_name, bus=bus or 0)
          self._can_sock = messaging.sub_sock("can", conflate=False, timeout=0)
      except Exception:
        self._raw_decoder = None
        self._can_sock = None
    if self._raw_decoder is None or self._can_sock is None:
      return
    try:
      from cereal import messaging
      from openpilot.selfdrive.pandad import can_capnp_to_list

      packets = can_capnp_to_list(messaging.drain_sock_raw(self._can_sock, wait_for_one=False))
      self.raw = self._raw_decoder.update(packets, time.monotonic_ns())
    except Exception:
      self.raw = ToyotaExtras()

  def vehicle_speed_mps(self, car_state) -> float | None:
    car_speed = super().vehicle_speed_mps(car_state)
    if self.raw.speed_mps is not None and (self.raw_fallback or car_speed is None or car_speed < 0.1):
      return self.raw.speed_mps
    return car_speed

  def steering_angle_deg(self, car_state) -> float | None:
    car_angle = super().steering_angle_deg(car_state)
    if self.raw.steering_angle_deg is not None and (self.raw_fallback or car_angle is None):
      return self.raw.steering_angle_deg
    return car_angle

  def throttle_brake_states(self, car_state) -> tuple[ControlBarState, ControlBarState]:
    throttle, brake = super().throttle_brake_states(car_state)
    if self.raw.throttle is not None and (self.raw_fallback or not throttle.analog):
      raw_pressed = self.raw.throttle > 0.001
      throttle = ControlBarState(self.raw.throttle, True, raw_pressed)
    if self.raw.brake_pressed is not None and (self.raw_fallback or not brake.analog):
      brake = ControlBarState(float(self.raw.brake_pressed), False, self.raw.brake_pressed)
    if car_state is None:
      return throttle, brake
    stock_aeb = bool(car_state.stockAeb)
    if stock_aeb and not brake.driver_override:
      brake = ControlBarState(max(brake.value, 1.0), brake.analog, False, True, "TSS AEB")
    return throttle, brake

  def stock_assistance_state(self, car_state) -> str | None:
    stock_aeb = bool(car_state.stockAeb) if car_state is not None else False
    if stock_aeb:
      return "TSS AEB"
    radar_active = bool(car_state.cruiseState.enabled) if car_state is not None else False
    if self.raw.radar_cruise_active is not None and self.raw_fallback:
      radar_active = self.raw.radar_cruise_active
    lta_active = bool(self.raw.lta_active)
    if radar_active and lta_active:
      return "TSS ACTIVE / RADAR + LTA"
    if radar_active:
      return "TSS RADAR CRUISE ACTIVE"
    if lta_active:
      return "TSS LTA ACTIVE"
    if car_state is not None and car_state.cruiseState.available:
      return "TSS READY"
    return "TSS OFF"

  def engine_rpm(self, car_state) -> float | None:
    if self.raw.engine_rpm is not None and self.raw_fallback:
      return self.raw.engine_rpm
    return super().engine_rpm(car_state)


def signal_provider_for_brand(brand: str | None, toyota_raw_fallback: bool = False) -> VehicleSignalProvider:
  if brand == "toyota" or toyota_raw_fallback:
    return ToyotaSignalProvider(raw_fallback=toyota_raw_fallback)
  return GenericSignalProvider()
