from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any

from cereal import messaging
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.common.tsk_sku import load_tsk_sku
from openpilot.selfdrive.pandad import can_capnp_to_list
from openpilot.system.hardware import PC

from .storage import SegmentClock, TelemetryStorage
from .ignition import ignition_state
from .toyota_decoder import ToyotaExtras, ToyotaExtrasDecoder, derive_ev_mode, tss_status


SAMPLE_RATE_HZ = 20
MODEL_DECIMATION = 4
SERVICES = (
  "carState", "selfdriveState", "gpsLocationExternal", "gpsLocation",
  "driverMonitoringState", "driverStateV2", "modelV2", "roadEncodeIdx", "pandaStates",
)


def telemetry_root() -> Path:
  configured = os.environ.get("TELEMETRY_ROOT")
  if configured:
    return Path(configured)
  if PC:
    return Path.home() / ".comma" / "media" / "0" / "telemetry"
  return Path("/data/media/0/telemetry")


def _enum_text(value: Any) -> str:
  text = str(value)
  return text.rsplit(".", 1)[-1]


def _list_value(values: Any, index: int) -> float | None:
  return float(values[index]) if len(values) > index else None


class TelemetryRecorder:
  def __init__(self) -> None:
    self.sm = messaging.SubMaster(list(SERVICES))
    self.params = Params()
    metadata: dict[str, Any] = {"sample_rate_hz": SAMPLE_RATE_HZ}
    sku_profile = load_tsk_sku()
    if sku_profile is not None:
      metadata.update({
        "tsk_sku_profile": sku_profile.profile_id,
        "tsk_sku_vehicle": sku_profile.vehicle,
        "tsk_sku_model_years": sku_profile.model_years,
        "tsk_sku_harness_variant": sku_profile.harness_variant,
        "tsk_sku_status": sku_profile.status,
        "tsk_sku_passive_only": sku_profile.passive_only,
        "tsk_sku_pin_map_status": sku_profile.pin_map_status,
      })
    self.toyota_decoder: ToyotaExtrasDecoder | None = None
    self.raw_toyota_fallback = False
    self.toyota_extras = ToyotaExtras()
    self.can_sock = None
    self.vehicle_mass_kg: float | None = None
    car_params = self.params.get("CarParamsPersistent")
    CP = None
    if car_params is not None:
      try:
        CP = messaging.log_from_bytes(car_params, car.CarParams)
        self.vehicle_mass_kg = float(CP.mass) if CP.mass > 0 else None
        metadata.update({
          "vehicle_brand": str(CP.brand),
          "car_fingerprint": str(CP.carFingerprint),
          "vehicle_mass_kg": self.vehicle_mass_kg,
        })
        if str(CP.brand).lower() == "toyota":
          self.toyota_decoder = ToyotaExtrasDecoder(CP)
          self.can_sock = messaging.sub_sock("can", conflate=False, timeout=0)
      except Exception:
        cloudlog.exception("telemetryd could not initialize vehicle telemetry")
    if self.toyota_decoder is None and (CP is None or CP.passive or CP.dashcamOnly):
      try:
        # Late-model Toyota Security Key cars can remain dashcam-only and have
        # no recognized fingerprint. Their read-only powertrain signals still
        # use the reviewed SecOC DBC, so keep recording useful telemetry.
        fallback_dbc = sku_profile.read_only_dbc if sku_profile is not None else "toyota_secoc_pt_generated"
        fallback_bus = sku_profile.read_only_bus if sku_profile is not None else 0
        if fallback_dbc is not None:
          self.toyota_decoder = ToyotaExtrasDecoder(dbc_name=fallback_dbc, bus=fallback_bus or 0)
          self.can_sock = messaging.sub_sock("can", conflate=False, timeout=0)
          self.raw_toyota_fallback = True
          metadata["vehicle_signal_source"] = "toyota_secoc_read_only_fallback"
      except Exception:
        cloudlog.exception("telemetryd could not initialize Toyota read-only fallback")
    start = SegmentClock(time.monotonic_ns(), time.time_ns() // 1_000_000)
    self.storage = TelemetryStorage(telemetry_root(), start=start, metadata=metadata)
    self.running = True
    self.frame = 0
    self.last_event_values: dict[str, Any] = {}
    self.gps: dict[str, Any] = {}
    self.road_segment_num: int | None = None
    self.road_encode_id: int | None = None
    self.ignition_on: bool | None = None

  def stop(self, *_args: Any) -> None:
    self.running = False

  def _update_gps(self) -> None:
    for service in ("gpsLocationExternal", "gpsLocation"):
      if not self.sm.updated[service] or not self.sm.valid[service]:
        continue
      location = self.sm[service]
      if service == "gpsLocation" and self.gps.get("gps_has_fix"):
        continue
      self.gps = {
        "gps_latitude": float(location.latitude),
        "gps_longitude": float(location.longitude),
        "gps_altitude_m": float(location.altitude),
        "gps_speed_mps": float(location.speed),
        "gps_bearing_deg": float(location.bearingDeg),
        "gps_accuracy_m": float(location.horizontalAccuracy),
        "gps_speed_accuracy_mps": float(location.speedAccuracy),
        "gps_has_fix": bool(location.hasFix),
        "gps_unix_time_ms": int(location.unixTimestampMillis),
      }

  def _record_change(self, clock: SegmentClock, kind: str, value: Any,
                     severity: str | None = None, details: dict[str, Any] | None = None) -> None:
    if self.last_event_values.get(kind) == value:
      return
    self.last_event_values[kind] = value
    self.storage.write_event(clock, kind, str(value), severity, details)

  def _update_toyota_extras(self, now_ns: int) -> None:
    if self.toyota_decoder is None or self.can_sock is None:
      return
    try:
      raw_messages = messaging.drain_sock_raw(self.can_sock, wait_for_one=False)
      self.toyota_extras = self.toyota_decoder.update(can_capnp_to_list(raw_messages), now_ns)
    except Exception:
      cloudlog.exception("telemetryd Toyota read-only decoder failed")
      self.toyota_extras = ToyotaExtras()

  def _update_ignition(self, clock: SegmentClock) -> bool:
    if not self.sm.updated["pandaStates"] or not self.sm.valid["pandaStates"]:
      return self.ignition_on is not False
    current = ignition_state(self.sm["pandaStates"])
    if current is None:
      return self.ignition_on is not False
    previous = self.ignition_on
    self.ignition_on = current
    if current and previous is False:
      self.storage.resume(clock)
      self._record_change(clock, "ignition", True)
    elif not current and previous is not False:
      self._record_change(clock, "ignition", False)
      self.storage.finalize_active_segment(clock, "ignition_off")
    return current

  def _extract_sample(self, clock: SegmentClock) -> dict[str, Any]:
    sample: dict[str, Any] = {}
    car_state = self.sm["carState"] if self.sm.valid["carState"] else None
    legacy = car_state.deprecated if car_state is not None else None
    car_speed = float(car_state.vEgo) if car_state is not None else None
    speed_mps = car_speed
    speed_source = "carState" if car_state is not None else None
    if self.toyota_extras.speed_mps is not None and (self.raw_toyota_fallback or speed_mps is None or speed_mps < 0.1):
      speed_mps = self.toyota_extras.speed_mps
      speed_source = "toyota_can"
    gps_speed = float(self.gps.get("gps_speed_mps", 0.0)) if self.gps.get("gps_has_fix") else None
    if (speed_mps is None or speed_mps < 0.1) and gps_speed is not None and gps_speed > 0.5:
      speed_mps = gps_speed
      speed_source = "gps"

    car_angle = float(car_state.steeringAngleDeg) if car_state is not None else None
    steering_angle = self.toyota_extras.steering_angle_deg if self.raw_toyota_fallback else car_angle
    if steering_angle is None:
      steering_angle = car_angle
    gas = float(legacy.gas) if legacy is not None else None
    gas_pressed = bool(car_state.gasPressed) if car_state is not None else False
    if self.toyota_extras.throttle is not None and (self.raw_toyota_fallback or not gas):
      gas = self.toyota_extras.throttle
      gas_pressed = gas > 0.001
    brake = float(legacy.brake) if legacy is not None else None
    brake_pressed = bool(car_state.brakePressed) if car_state is not None else False
    if self.toyota_extras.brake_pressed is not None and (self.raw_toyota_fallback or not brake_pressed):
      brake_pressed = self.toyota_extras.brake_pressed
      brake = max(brake or 0.0, float(brake_pressed))

    legacy_engine_rpm = float(legacy.engineRpm) if legacy is not None else 0.0
    engine_rpm = self.toyota_extras.engine_rpm
    if engine_rpm is None and legacy_engine_rpm > 0:
      engine_rpm = legacy_engine_rpm
    engine_running = self.toyota_extras.engine_running
    ev_mode = derive_ev_mode(engine_rpm, engine_running)
    drive_force = self.toyota_extras.hybrid_drive_force_n
    acceleration = float(car_state.aEgo) if car_state is not None else 0.0
    power_flow_kw: float | None = None
    power_flow_source: str | None = None
    if drive_force is not None and speed_mps is not None:
      power_flow_kw = drive_force * speed_mps / 1000.0
      power_flow_source = "dbc_wheel_force"
    elif self.vehicle_mass_kg is not None and speed_mps is not None and abs(speed_mps) > 0.5:
      power_flow_kw = self.vehicle_mass_kg * acceleration * speed_mps / 1000.0
      power_flow_source = "estimated_traction"

    stock_aeb = bool(car_state.stockAeb) if car_state is not None else False
    cruise_available = bool(car_state.cruiseState.available) if car_state is not None else False
    cruise_enabled = bool(car_state.cruiseState.enabled) if car_state is not None else False
    if self.toyota_extras.radar_cruise_active is not None and self.raw_toyota_fallback:
      cruise_enabled = self.toyota_extras.radar_cruise_active
      cruise_available = True
    lta_active = self.toyota_extras.lta_active
    assist_status = tss_status(cruise_available, cruise_enabled, lta_active, stock_aeb)
    sample.update({
      "v_ego_mps": speed_mps,
      "speed_source": speed_source,
      "a_ego_mps2": acceleration,
      "steering_angle_deg": steering_angle,
      "steering_torque": float(car_state.steeringTorque) if car_state is not None else None,
      "steering_pressed": bool(car_state.steeringPressed) if car_state is not None else False,
      "gas": gas if gas and gas > 0 else None,
      "gas_pressed": gas_pressed,
      "brake": brake if brake and brake > 0 else None,
      "brake_pressed": brake_pressed,
      "engine_rpm": engine_rpm,
      "engine_running": engine_running,
      "hybrid_battery_percent": None,
      "ev_mode": ev_mode,
      "power_flow_kw": power_flow_kw,
      "power_flow_source": power_flow_source,
      "hybrid_drive_force_n": drive_force,
      "stock_aeb": stock_aeb,
      "cruise_available": cruise_available,
      "cruise_enabled": cruise_enabled,
      "lta_active": lta_active,
      "tss_status": assist_status,
    })
    self._record_change(clock, "brake_override", brake_pressed)
    self._record_change(clock, "steering_override", bool(car_state.steeringPressed) if car_state is not None else False)
    self._record_change(clock, "tss_status", assist_status)

    if self.sm.valid["selfdriveState"]:
      selfdrive = self.sm["selfdriveState"]
      state = _enum_text(selfdrive.state)
      alert_status = _enum_text(selfdrive.alertStatus)
      sample.update({
        "selfdrive_state": state,
        "engaged": bool(selfdrive.enabled),
        "active": bool(selfdrive.active),
        "engageable": bool(selfdrive.engageable),
        "alert_type": str(selfdrive.alertType),
        "alert_status": alert_status,
        "alert_text_1": str(selfdrive.alertText1),
        "alert_text_2": str(selfdrive.alertText2),
      })
      self._record_change(clock, "engagement", bool(selfdrive.enabled), alert_status)
      alert_key = (str(selfdrive.alertType), str(selfdrive.alertText1), str(selfdrive.alertText2))
      if any(alert_key):
        self._record_change(clock, "alert", alert_key, alert_status, {
          "type": alert_key[0], "text_1": alert_key[1], "text_2": alert_key[2],
        })

    if self.sm.valid["driverMonitoringState"]:
      monitoring = self.sm["driverMonitoringState"]
      vision = monitoring.visionPolicyState
      sample.update({
        "driver_face_detected": bool(vision.faceDetected),
        "driver_distracted": bool(vision.isDistracted),
        "driver_awareness": float(vision.awarenessPercent) / 100.0,
      })
      self._record_change(clock, "driver_distraction", bool(vision.isDistracted))
      if self.sm.valid["driverStateV2"]:
        driver_state = self.sm["driverStateV2"]
        driver = driver_state.rightDriverData if monitoring.isRHD else driver_state.leftDriverData
        orientation = driver.faceOrientation
        sample.update({
          "driver_face_probability": float(driver.faceProb),
          "driver_face_pitch": _list_value(orientation, 0),
          "driver_face_yaw": _list_value(orientation, 1),
          "driver_face_roll": _list_value(orientation, 2),
        })

    sample.update(self.gps)
    sample["road_segment_num"] = self.road_segment_num
    sample["road_encode_id"] = self.road_encode_id
    return sample

  def _update_video_association(self, clock: SegmentClock) -> None:
    if not self.sm.updated["roadEncodeIdx"] or not self.sm.valid["roadEncodeIdx"]:
      return
    index = self.sm["roadEncodeIdx"]
    self.road_segment_num = int(index.segmentNum)
    self.road_encode_id = int(index.encodeId)
    route = self.params.get("CurrentRoute", encoding="utf-8") or ""
    self.storage.associate_video(clock, route, self.road_segment_num, int(index.timestampEof))

  def _record_model_path(self, clock: SegmentClock) -> None:
    if self.frame % MODEL_DECIMATION or not self.sm.valid["modelV2"]:
      return
    model = self.sm["modelV2"]
    position = model.position
    self.storage.write_model_path(
      clock, int(model.frameId), list(position.x), list(position.y), list(position.z),
    )

  def run(self) -> None:
    ratekeeper = Ratekeeper(SAMPLE_RATE_HZ, print_delay_threshold=None)
    try:
      while self.running:
        self.sm.update(0)
        clock = SegmentClock(time.monotonic_ns(), time.time_ns() // 1_000_000)
        if not self._update_ignition(clock):
          ratekeeper.keep_time()
          continue
        self._update_gps()
        self._update_toyota_extras(clock.mono_ns)
        self._update_video_association(clock)
        self.storage.write_sample(self._extract_sample(clock), clock)
        self._record_model_path(clock)
        self.frame += 1
        ratekeeper.keep_time()
    finally:
      self.storage.close(reason="shutdown")


def main() -> None:
  recorder = TelemetryRecorder()
  signal.signal(signal.SIGINT, recorder.stop)
  signal.signal(signal.SIGTERM, recorder.stop)
  cloudlog.info("telemetryd recording to %s", recorder.storage.drive_directory)
  recorder.run()


if __name__ == "__main__":
  main()
