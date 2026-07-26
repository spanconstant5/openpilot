from __future__ import annotations

import math
from dataclasses import dataclass


SIGNAL_TIMEOUT_NS = 2_000_000_000


@dataclass(frozen=True)
class ToyotaExtras:
  engine_rpm: float | None = None
  engine_running: bool | None = None
  hybrid_drive_force_n: float | None = None
  lta_active: bool | None = None


def derive_ev_mode(engine_rpm: float | None, engine_running: bool | None) -> bool | None:
  """Return engine-off EV state only when an engine signal is actually available."""
  if engine_running is not None:
    return not engine_running
  if engine_rpm is not None:
    return engine_rpm < 50.0
  return None


def tss_status(cruise_available: bool, radar_cruise_active: bool, lta_active: bool | None,
               stock_aeb: bool = False) -> str:
  if stock_aeb:
    return "TSS AEB"
  if radar_cruise_active and lta_active:
    return "TSS ACTIVE · RADAR + LTA"
  if radar_cruise_active:
    return "TSS RADAR CRUISE ACTIVE"
  if lta_active:
    return "TSS LTA ACTIVE"
  return "TSS READY" if cruise_available else "TSS OFF"


class ToyotaExtrasDecoder:
  """Read-only decoder for signals already defined in the selected Toyota DBC."""

  def __init__(self, car_params):
    from opendbc.can import CANParser
    from opendbc.can.dbc import DBC as DBCFile
    from opendbc.car import Bus
    from opendbc.car.toyota.values import DBC as TOYOTA_DBC

    dbc_name = TOYOTA_DBC[car_params.carFingerprint][Bus.pt]
    dbc = DBCFile(dbc_name)
    desired_messages = ("ENGINE_RPM", "GEAR_PACKET_HYBRID", "EPS_STATUS")
    messages = [(name, math.nan) for name in desired_messages if name in dbc.name_to_msg]
    if not messages:
      raise RuntimeError(f"Toyota DBC {dbc_name} has no Phase 3 telemetry messages")
    self.parser = CANParser(dbc_name, messages, 0)

  def _fresh_value(self, message: str, signal: str, now_ns: int) -> float | None:
    if message not in self.parser.vl or signal not in self.parser.vl[message]:
      return None
    timestamp = int(self.parser.ts_nanos[message][signal])
    if timestamp <= 0 or now_ns < timestamp or now_ns - timestamp > SIGNAL_TIMEOUT_NS:
      return None
    return float(self.parser.vl[message][signal])

  def update(self, can_packets, now_ns: int) -> ToyotaExtras:
    if can_packets:
      self.parser.update(can_packets)
    rpm = self._fresh_value("ENGINE_RPM", "RPM", now_ns)
    engine_running_raw = self._fresh_value("ENGINE_RPM", "ENGINE_RUNNING", now_ns)
    drive_force = self._fresh_value("GEAR_PACKET_HYBRID", "FDRVREAL", now_ns)
    lta_state = self._fresh_value("EPS_STATUS", "LTA_STATE", now_ns)
    return ToyotaExtras(
      engine_rpm=max(0.0, rpm) if rpm is not None else None,
      engine_running=bool(engine_running_raw) if engine_running_raw is not None else None,
      hybrid_drive_force_n=drive_force,
      lta_active=lta_state == 5.0 if lta_state is not None else None,
    )
