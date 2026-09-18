#!/usr/bin/env python3
from opendbc.can import CANParser
from opendbc.car import Bus
from opendbc.car.structs import RadarData
from opendbc.car.toyota.values import CAR, DBC, TSS2_CAR, ToyotaFlags
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_ACC_TSSP_CAR = {CAR.TOYOTA_CAMRY}
TSSP_CLUSTER_MSGS = list(range(0x680, 0x686))
KPH_TO_MS = 1. / 3.6
TSSP_RADAR_EGO_SPEED_SCALE = 0.922

# TSS3 (CAN FD) front radar: three object banks (0x180-0x182 geometry: DIST/LAT) +
# three matching motion banks (0x183-0x185: VREL, TRACK_STATE/NEW_TRACK/TRACK_ENDED),
# 8 slots each = 24 objects. On panda bus 0 (ADAS). Ported from kaikozlov/opendbc.
TSS3_RADAR_A_MSGS = list(range(0x180, 0x183))   # geometry
TSS3_RADAR_B_MSGS = list(range(0x183, 0x186))   # motion


def _create_radar_can_parser(car_fingerprint):
  if car_fingerprint in TSS2_CAR:
    RADAR_A_MSGS = list(range(0x180, 0x190))
    RADAR_B_MSGS = list(range(0x190, 0x1a0))
  else:
    RADAR_A_MSGS = list(range(0x210, 0x220))
    RADAR_B_MSGS = list(range(0x220, 0x230))

  msg_a_n = len(RADAR_A_MSGS)
  msg_b_n = len(RADAR_B_MSGS)
  messages = list(zip(RADAR_A_MSGS + RADAR_B_MSGS, [20] * (msg_a_n + msg_b_n), strict=True))

  return CANParser(DBC[car_fingerprint][Bus.radar], messages, 1)


def _create_tss3_radar_can_parser(car_fingerprint):
  messages = [(msg, 20) for msg in range(0x180, 0x186)]
  return CANParser(DBC[car_fingerprint][Bus.radar], messages, 0)


def _create_tssp_radar_can_parser(car_fingerprint):
  return CANParser(DBC[car_fingerprint][Bus.radar], [(addr, 10) for addr in TSSP_CLUSTER_MSGS], 1)


def _create_wheel_speed_can_parser(car_fingerprint):
  return CANParser(DBC[car_fingerprint][Bus.pt], [("WHEEL_SPEEDS", 80)], 0)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.track_id = 0
    self.radar_acc_tssp = CP.carFingerprint in RADAR_ACC_TSSP_CAR
    self.tss3 = bool(CP.flags & ToyotaFlags.CAN_FD.value)

    self.pt_cp = None
    if self.tss3:
      # TSS3 CAN FD radar (bus 0). Object banks arrive synchronized; 0x185 is the trigger.
      self.RADAR_A_MSGS = TSS3_RADAR_A_MSGS
      self.RADAR_B_MSGS = TSS3_RADAR_B_MSGS
      self.trigger_msg = 0x185
      self.rcp = None if CP.radarUnavailable else _create_tss3_radar_can_parser(CP.carFingerprint)
      self.tss3_cycle = None
      self.tss3_cycle_time = None
    elif self.radar_acc_tssp:
      self.RADAR_MSGS = TSSP_CLUSTER_MSGS
      self.rcp = None if CP.radarUnavailable else _create_tssp_radar_can_parser(CP.carFingerprint)
      self.pt_cp = None if CP.radarUnavailable else _create_wheel_speed_can_parser(CP.carFingerprint)
      self.trigger_msg = self.RADAR_MSGS[-1]
    else:
      if CP.carFingerprint in TSS2_CAR:
        self.RADAR_A_MSGS = list(range(0x180, 0x190))
        self.RADAR_B_MSGS = list(range(0x190, 0x1a0))
      else:
        self.RADAR_A_MSGS = list(range(0x210, 0x220))
        self.RADAR_B_MSGS = list(range(0x220, 0x230))
      self.valid_cnt = {key: 0 for key in self.RADAR_A_MSGS}
      self.rcp = None if CP.radarUnavailable else _create_radar_can_parser(CP.carFingerprint)
      self.trigger_msg = self.RADAR_B_MSGS[-1]

    self.updated_messages = set()

  def update(self, can_strings):
    if self.rcp is None:
      return super().update(None)

    if self.tss3:
      return self._update_tss3(can_strings)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)
    if self.pt_cp is not None:
      self.pt_cp.update(can_strings)

    if self.trigger_msg not in self.updated_messages:
      return None

    if self.pt_cp is not None and not self.pt_cp.can_valid:
      self.updated_messages.clear()
      ret = RadarData()
      ret.errors.canError = True
      return ret

    rr = self._update(self.updated_messages)
    self.updated_messages.clear()

    return rr

  # ---- TSS3 (CAN FD) radar ----
  def _update_tss3(self, can_packets):
    self.frame += 1
    result = None
    for nanos, packets in can_packets:
      for address, data, bus in packets:
        if bus != self.rcp.bus or address not in self.rcp.addresses or len(data) != 64:
          continue
        updated = self.rcp.update([(nanos, [(address, data, bus)])])
        self.updated_messages.update(updated)
        if len(self.updated_messages) != len(self.rcp.addresses):
          continue
        cycles = {(int(self.rcp.vl[a]["COUNTER"]), int(self.rcp.vl[a]["CYCLE_BYTE"])) for a in self.rcp.addresses}
        if len(cycles) != 1:
          continue
        cycle = next(iter(cycles))
        self.updated_messages.clear()
        if cycle == self.tss3_cycle:
          continue
        gap = self.tss3_cycle is not None and any((new - old) % 256 != 1 for new, old in zip(cycle, self.tss3_cycle, strict=True))
        timeout = self.tss3_cycle_time is not None and any(
          nanos - self.tss3_cycle_time > state.timeout_threshold for state in self.rcp.message_states.values())
        if gap or timeout:
          self.pts.clear()
        self.tss3_cycle = cycle
        self.tss3_cycle_time = nanos
        result = self._update_tss3_points()
      self.rcp.update([(nanos, [])])

    if not self.rcp.can_valid:
      self.pts.clear()
      if self.tss3_cycle_time is not None or self.rcp.bus_timeout:
        self.updated_messages.clear()
      self.tss3_cycle = None
      self.tss3_cycle_time = None
      if result is not None or self.frame % 5 == 0:
        result = RadarData()
        result.errors.canError = True
    return result

  def _update_tss3_points(self):
    for bank, address in enumerate(self.RADAR_A_MSGS):
      geometry, motion = self.rcp.vl[address], self.rcp.vl[address + 3]
      for slot in range(8):
        key = bank * 8 + slot
        if motion[f"TRACK_ENDED_{slot}"] or motion[f"NEW_TRACK_{slot}"]:
          self.pts.pop(key, None)
        if motion[f"TRACK_ENDED_{slot}"] and not motion[f"NEW_TRACK_{slot}"]:
          continue
        distance = geometry[f"DIST_{slot}"]
        if motion[f"TRACK_STATE_{slot}"] == 0 or not 0 < distance < 0xFFF8 * 0.005:
          self.pts.pop(key, None)
          continue
        if key not in self.pts:
          self.pts[key] = RadarData.RadarPoint()
          self.pts[key].trackId = self.track_id
          self.track_id += 1
        self.pts[key].dRel = distance
        self.pts[key].yRel = geometry[f"LAT_{slot}"]
        self.pts[key].vRel = motion[f"VREL_{slot}"]
        self.pts[key].aRel = float('nan')
        self.pts[key].yvRel = float('nan')
        self.pts[key].measured = True
    result = RadarData()
    result.points = list(self.pts.values())
    return result

  # ---- TSSP (Camry cluster) ----
  def _get_v_ego(self):
    ws = self.pt_cp.vl["WHEEL_SPEEDS"]
    wheel_speed = (ws["WHEEL_SPEED_FL"] + ws["WHEEL_SPEED_FR"] +
                   ws["WHEEL_SPEED_RL"] + ws["WHEEL_SPEED_RR"]) / 4.
    return wheel_speed * KPH_TO_MS * self.CP.wheelSpeedFactor

  def _update_tssp(self, updated_messages):
    ret = RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    v_ego = self._get_v_ego()
    updated_ids = set()
    for ii in sorted(updated_messages):
      if ii not in self.RADAR_MSGS:
        continue

      cpt = self.rcp.vl[ii]
      track_id = int(cpt["ID"])
      if track_id == 0x3f or cpt["LONG_DIST"] <= 0:
        continue

      updated_ids.add(track_id)
      if track_id not in self.pts:
        self.pts[track_id] = RadarData.RadarPoint()
        self.pts[track_id].trackId = self.track_id
        self.track_id += 1

      self.pts[track_id].dRel = float(cpt["LONG_DIST"])
      self.pts[track_id].yRel = -float(cpt["LAT_DIST"])
      self.pts[track_id].vRel = float(cpt["SPEED"]) - v_ego * TSSP_RADAR_EGO_SPEED_SCALE
      self.pts[track_id].aRel = float("nan")
      self.pts[track_id].yvRel = float(cpt["LAT_SPEED"])
      self.pts[track_id].measured = True

    for track_id in list(self.pts):
      if track_id not in updated_ids:
        del self.pts[track_id]

    ret.points = list(self.pts.values())
    return ret

  def _update(self, updated_messages):
    if self.radar_acc_tssp:
      return self._update_tssp(updated_messages)

    return self._update_denso(updated_messages)

  def _update_denso(self, updated_messages):
    ret = RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    for ii in sorted(updated_messages):
      if ii in self.RADAR_A_MSGS:
        cpt = self.rcp.vl[ii]

        if cpt['LONG_DIST'] >= 255 or cpt['NEW_TRACK']:
          self.valid_cnt[ii] = 0    # reset counter
        if cpt['VALID'] and cpt['LONG_DIST'] < 255:
          self.valid_cnt[ii] += 1
        else:
          self.valid_cnt[ii] = max(self.valid_cnt[ii] - 1, 0)

        score = self.rcp.vl[ii+16]['SCORE']

        # radar point only valid if it's a valid measurement and score is above 50
        if cpt['VALID'] or (score > 50 and cpt['LONG_DIST'] < 255 and self.valid_cnt[ii] > 0):
          if ii not in self.pts or cpt['NEW_TRACK']:
            self.pts[ii] = RadarData.RadarPoint()
            self.pts[ii].trackId = self.track_id
            self.track_id += 1
          self.pts[ii].dRel = cpt['LONG_DIST']  # from front of car
          self.pts[ii].yRel = -cpt['LAT_DIST']  # in car frame's y axis, left is positive
          self.pts[ii].vRel = cpt['REL_SPEED']
          self.pts[ii].aRel = float('nan')
          self.pts[ii].yvRel = float('nan')
          self.pts[ii].measured = bool(cpt['VALID'])
        else:
          if ii in self.pts:
            del self.pts[ii]

    ret.points = list(self.pts.values())
    return ret
