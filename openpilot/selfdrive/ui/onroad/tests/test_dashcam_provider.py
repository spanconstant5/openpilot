from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.dashcam_provider import GenericSignalProvider, ToyotaSignalProvider, signal_provider_for_brand
from openpilot.system.telemetry.toyota_decoder import ToyotaExtras


def car_state(gas=0.0, brake=0.0, rpm=0.0, gas_pressed=False, brake_pressed=False,
              stock_aeb=False, cruise_available=True, cruise_enabled=False, stock_lkas=False):
  return SimpleNamespace(
    deprecated=SimpleNamespace(gas=gas, brake=brake, engineRpm=rpm),
    gasPressed=gas_pressed,
    brakePressed=brake_pressed,
    stockAeb=stock_aeb,
    stockLkas=stock_lkas,
    cruiseState=SimpleNamespace(available=cruise_available, enabled=cruise_enabled),
    vEgo=12.0,
    vEgoCluster=12.2,
    steeringAngleDeg=-3.0,
  )


def test_generic_bars_use_pressed_state_until_analog_is_observed():
  provider = GenericSignalProvider()
  throttle, brake = provider.throttle_brake_states(car_state(gas_pressed=True))
  assert throttle.value == 1.0
  assert throttle.driver_override
  assert not throttle.analog
  assert brake.value == 0.0

  throttle, _ = provider.throttle_brake_states(car_state(gas=0.42))
  assert throttle.value == 0.42
  assert throttle.analog


def test_toyota_provider_distinguishes_tss_from_driver_override():
  provider = ToyotaSignalProvider()
  _, brake = provider.throttle_brake_states(car_state(stock_aeb=True))
  assert brake.automation_active
  assert not brake.driver_override
  assert brake.source_label == "TSS AEB"
  assert provider.stock_assistance_state(car_state(cruise_enabled=True)) == "TSS RADAR CRUISE ACTIVE"
  provider.raw = ToyotaExtras(lta_active=True)
  assert provider.stock_assistance_state(car_state()) == "TSS LTA ACTIVE"
  assert provider.stock_assistance_state(car_state(cruise_enabled=True)) == "TSS ACTIVE / RADAR + LTA"
  provider.raw = ToyotaExtras()
  assert provider.stock_assistance_state(car_state()) == "TSS READY"
  assert provider.stock_assistance_state(car_state(stock_aeb=True)) == "TSS AEB"


def test_optional_rpm_and_brand_factory():
  provider = GenericSignalProvider()
  assert provider.engine_rpm(car_state()) is None
  assert provider.engine_rpm(car_state(rpm=1750)) == 1750
  assert isinstance(signal_provider_for_brand("toyota"), ToyotaSignalProvider)
  assert isinstance(signal_provider_for_brand("honda"), GenericSignalProvider)


def test_toyota_raw_fallback_supplies_unsupported_car_telemetry():
  provider = ToyotaSignalProvider(raw_fallback=True)
  provider.raw = ToyotaExtras(
    speed_mps=18.5,
    steering_angle_deg=7.25,
    throttle=0.36,
    brake_pressed=False,
    radar_cruise_active=True,
    engine_rpm=1420.0,
    lta_active=True,
  )
  state = car_state()
  assert provider.vehicle_speed_mps(state) == 18.5
  assert provider.steering_angle_deg(state) == 7.25
  throttle, brake = provider.throttle_brake_states(state)
  assert throttle.value == 0.36
  assert throttle.analog
  assert not brake.driver_override
  assert provider.engine_rpm(state) == 1420.0
  assert provider.stock_assistance_state(state) == "TSS ACTIVE / RADAR + LTA"


def test_raw_toyota_factory_is_opt_in_for_dashcam_only_mode():
  provider = signal_provider_for_brand("mock", toyota_raw_fallback=True)
  assert isinstance(provider, ToyotaSignalProvider)
  assert provider.raw_fallback
