from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.dashcam_provider import GenericSignalProvider, ToyotaSignalProvider, signal_provider_for_brand


def car_state(gas=0.0, brake=0.0, rpm=0.0, gas_pressed=False, brake_pressed=False,
              stock_aeb=False, cruise_available=True, cruise_enabled=False):
  return SimpleNamespace(
    deprecated=SimpleNamespace(gas=gas, brake=brake, engineRpm=rpm),
    gasPressed=gas_pressed,
    brakePressed=brake_pressed,
    stockAeb=stock_aeb,
    cruiseState=SimpleNamespace(available=cruise_available, enabled=cruise_enabled),
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
  assert provider.stock_assistance_state(car_state(cruise_enabled=True)) == "TSS CRUISE ACTIVE"
  assert provider.stock_assistance_state(car_state(stock_aeb=True)) == "TSS AEB"


def test_optional_rpm_and_brand_factory():
  provider = GenericSignalProvider()
  assert provider.engine_rpm(car_state()) is None
  assert provider.engine_rpm(car_state(rpm=1750)) == 1750
  assert isinstance(signal_provider_for_brand("toyota"), ToyotaSignalProvider)
  assert isinstance(signal_provider_for_brand("honda"), GenericSignalProvider)
