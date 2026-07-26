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
from openpilot.system.hardware import PC

from .ignition import ignition_state
from .storage import SegmentClock, TelemetryStorage


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
    car_params = self.params.get("CarParamsPersistent")
    if car_params is not None:
      try:
        CP = messaging.log_from_bytes(car_params, car.CarParams)
        metadata.update({"vehicle_brand": str(CP.brand), "car_fingerprint": str(CP.carFingerprint)})
      except Exception:
        cloudlog.exception("telemetryd could not read CarParamsPersistent")
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
    if self.sm.valid["carState"]:
      car_state = self.sm["carState"]
      legacy = car_state.deprecated
      gas = float(legacy.gas)
      brake = float(legacy.brake)
      engine_rpm = float(legacy.engineRpm)
      sample.update({
        "v_ego_mps": float(car_state.vEgo),
        "a_ego_mps2": float(car_state.aEgo),
        "steering_angle_deg": float(car_state.steeringAngleDeg),
        "steering_torque": float(car_state.steeringTorque),
        "steering_pressed": bool(car_state.steeringPressed),
        "gas": gas if gas > 0 else None,
        "gas_pressed": bool(car_state.gasPressed),
        "brake": brake if brake > 0 else None,
        "brake_pressed": bool(car_state.brakePressed),
        "engine_rpm": engine_rpm if engine_rpm > 0 else None,
        "stock_aeb": bool(car_state.stockAeb),
        "cruise_available": bool(car_state.cruiseState.available),
        "cruise_enabled": bool(car_state.cruiseState.enabled),
      })
      self._record_change(clock, "brake_override", bool(car_state.brakePressed))
      self._record_change(clock, "steering_override", bool(car_state.steeringPressed))

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
