import unittest

from openpilot.system.tss3_cruise_recorder.protocol import (
  PCM_CRUISE_2_ADDRESS,
  decode_cruise_buttons,
  decode_cruise_set_state,
  is_physical_bus,
  toyota_checksum,
)


class TestProtocol(unittest.TestCase):
  def test_cruise_button_and_secoc_fields(self):
    decoded = decode_cruise_buttons(bytes.fromhex("900000ba9abcdef0"))
    self.assertEqual(decoded.names, ("cancel", "increase"))
    self.assertEqual(decoded.counter, 0xA)
    self.assertEqual(decoded.reset_flag, 1)
    self.assertEqual(decoded.message_counter_lower, 2)
    self.assertEqual(decoded.authenticator, 0xABCDEF0)

  def test_low_speed_lockout_uses_dbc_bits_6_through_5(self):
    first_seven = bytes.fromhex("00c06400000000")
    checksum = toyota_checksum(PCM_CRUISE_2_ADDRESS, first_seven)
    decoded = decode_cruise_set_state(first_seven + bytes([checksum]))
    self.assertTrue(decoded.main_on)
    self.assertEqual(decoded.follow_distance, 0)
    self.assertEqual(decoded.low_speed_lockout, 2)
    self.assertEqual(decoded.set_speed_kph, 100)
    self.assertFalse(decoded.acc_faulted)
    self.assertTrue(decoded.checksum_valid)

  def test_only_sources_below_returned_offset_are_physical(self):
    self.assertTrue(is_physical_bus(0))
    self.assertTrue(is_physical_bus(127))
    self.assertFalse(is_physical_bus(0x80))
    self.assertFalse(is_physical_bus(0xC1))


if __name__ == "__main__":
  unittest.main()
