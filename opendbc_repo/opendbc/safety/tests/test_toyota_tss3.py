#!/usr/bin/env python3
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.toyota.values import CAR, EPS_SCALE, ToyotaSafetyFlags
from opendbc.safety.tests import common
from opendbc.safety.tests.libsafety import libsafety_py


TSS3_DBC = "toyota_tss3_pt_generated"
TSS3_FRC_08A = bytes.fromhex("0000000880002d47f0605ef0607fff007fff000c4000100000000a00fc472d50")
TSS3_CRUISE_BUTTONS = bytes.fromhex("567d393f0000c36200000000000000002640000000ff000000000000d54aaf10")


def fix_toyota_checksum(msg):
  address, data, bus = msg
  payload = bytearray(data)
  payload[-1] = (address + (address >> 8) + len(payload) + sum(payload[:-1])) & 0xFF
  return address, bytes(payload), bus


def tss3_cruise_buttons_msg(data: bytes, bus: int = 2):
  msg = libsafety_py.make_CANPacket(0x0FE, bus, data)
  msg[0].fd = 1
  return msg


class TestToyotaTss3CorollaSafety(common.SafetyTestBase):
  DBC = TSS3_DBC
  SAFETY_MODEL = CarParams.SafetyModel.toyota
  SAFETY_PARAM = (EPS_SCALE[CAR.TOYOTA_COROLLA_TSS3] | ToyotaSafetyFlags.TSS3 |
                  ToyotaSafetyFlags.TSS3_RX_BUS_2 | ToyotaSafetyFlags.STOCK_LONGITUDINAL)

  def _required_rx(self, bus: int):
    return [
      self.packer.make_can_msg_safety("EPS_STATUS", bus, {"STEER_ANGLE_STATUS": 1}),
      self.packer.make_can_msg_safety("WHEEL_SPEEDS", bus, {}),
      self.packer.make_can_msg_safety("GAS_PEDAL", bus, {}),
      self.packer.make_can_msg_safety("BRAKE_MODULE", bus, {}, fix_toyota_checksum),
      libsafety_py.make_CANPacket(0x08A, 2, TSS3_FRC_08A),
      tss3_cruise_buttons_msg(TSS3_CRUISE_BUTTONS, bus),
    ]

  def test_exact_profile_is_live(self):
    self.assertEqual(self.SAFETY_PARAM, 0x7249)
    self.assertTrue(self._rx(libsafety_py.make_CANPacket(0x08A, 2, TSS3_FRC_08A)))
    arm = libsafety_py.make_CANPacket(0x777, 1, bytes((7, 0xC9, 0xA8, 1, 0, 0, 0, 0)))
    self.assertTrue(self._tx(arm))

  def test_required_rx_checks_use_bus_2(self):
    for msg in self._required_rx(2):
      self.assertTrue(self._rx(msg))
    self.assertTrue(self.safety.safety_config_valid())

    self._reset_safety_hooks()
    self.safety.init_tests()
    for msg in self._required_rx(0):
      self._rx(msg)
    self.assertFalse(self.safety.safety_config_valid())

  def test_icbm_clones_only_res_or_set(self):
    self.safety.set_controls_allowed(True)
    self.assertTrue(self._rx(tss3_cruise_buttons_msg(TSS3_CRUISE_BUTTONS)))

    res = bytearray(TSS3_CRUISE_BUTTONS)
    res[3] |= 0x80
    res[6] &= 0x7F
    self.assertTrue(self._tx(tss3_cruise_buttons_msg(bytes(res))))

    set_button = bytearray(TSS3_CRUISE_BUTTONS)
    set_button[4] |= 0x80
    set_button[7] &= 0xBF
    self.assertTrue(self._tx(tss3_cruise_buttons_msg(bytes(set_button))))

    unrelated = bytearray(res)
    unrelated[10] ^= 1
    self.assertFalse(self._tx(tss3_cruise_buttons_msg(bytes(unrelated))))

  def test_icbm_requires_controls_and_recent_neutral_stock(self):
    res = bytearray(TSS3_CRUISE_BUTTONS)
    res[3] |= 0x80
    res[6] &= 0x7F
    msg = tss3_cruise_buttons_msg(bytes(res))

    self.safety.set_controls_allowed(True)
    self.assertFalse(self._tx(msg))
    self.assertTrue(self._rx(tss3_cruise_buttons_msg(TSS3_CRUISE_BUTTONS)))
    self.safety.set_controls_allowed(False)
    self.assertFalse(self._tx(msg))
    self.safety.set_controls_allowed(True)
    self.safety.set_timer(100_001)
    self.assertFalse(self._tx(msg))


if __name__ == "__main__":
  unittest.main()
