#!/usr/bin/env python3
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.toyota.values import ToyotaSafetyFlags
from opendbc.safety.tests.libsafety import libsafety_py


class TestToyotaTSS3(unittest.TestCase):
  def setUp(self):
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, 73 | ToyotaSafetyFlags.TSS3)
    self.safety.init_tests()

  @staticmethod
  def accel_msg(accel: float, steer: int = 0):
    raw = max(-16384, min(16383, round(accel / 0.001))) & 0x7FFF
    dat = bytearray(32)
    dat[4] = 0x80 | ((raw >> 8) & 0x7F)
    dat[5] = raw & 0xFF
    dat[22:24] = (steer & 0xFFFF).to_bytes(2, "big")
    return libsafety_py.make_CANPacket(0x160, 0, bytes(dat))

  def engage(self):
    dat = bytearray(32)
    dat[7] = 0x47
    self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x8A, 1, bytes(dat)))
    dat[22] = 0x10
    self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x8A, 1, bytes(dat)))
    self.assertTrue(self.safety.get_controls_allowed())

  def test_allowlist_excludes_1a0_and_legacy_160(self):
    self.engage()
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(0.5)))
    self.assertFalse(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(0x160, 1, bytes(8))))
    self.assertFalse(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(0x1A0, 0, bytes(48))))

  def test_accel_bounds_and_disengaged_gate(self):
    self.safety.set_controls_allowed(False)
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(0.0)))
    self.assertFalse(self.safety.safety_tx_hook(self.accel_msg(0.1)))
    self.engage()
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(-3.5)))
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(2.0)))
    self.assertFalse(self.safety.safety_tx_hook(self.accel_msg(2.1)))

  def test_steer_rate_and_forwarding(self):
    self.assertEqual(0, self.safety.safety_fwd_hook(2, 0x160))
    self.engage()
    self.assertEqual(-1, self.safety.safety_fwd_hook(2, 0x160))
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(0.0, 20000)))
    self.assertTrue(self.safety.safety_tx_hook(self.accel_msg(0.0, 21500)))
    self.assertFalse(self.safety.safety_tx_hook(self.accel_msg(0.0, 23501)))
    self.assertFalse(self.safety.safety_tx_hook(self.accel_msg(0.0, 23501)))


if __name__ == "__main__":
  unittest.main()
