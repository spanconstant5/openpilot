import unittest

from openpilot.system.tss3_cruise_recorder.protocol import PCM_CRUISE_2_ADDRESS, PCM_CRUISE_4_ADDRESS, toyota_checksum
from openpilot.system.tss3_cruise_recorder.selector import FrameSelector


def cruise_4(button_byte: int = 0, counter: int = 0, authenticator: int = 0) -> bytes:
  return bytes((button_byte, 0, 0, counter & 0x0F, (authenticator >> 24) & 0x0F,
                (authenticator >> 16) & 0xFF, (authenticator >> 8) & 0xFF, authenticator & 0xFF))


def cruise_2(main_and_lockout: int, speed: int, filler: int = 0) -> bytes:
  first = bytes((0, main_and_lockout, speed, filler, 0, 0, 0))
  return first + bytes((toyota_checksum(PCM_CRUISE_2_ADDRESS, first),))


class TestFrameSelector(unittest.TestCase):
  def test_rolling_counter_and_authenticator_do_not_create_idle_events(self):
    selector = FrameSelector(idle_sample_ns=1_000_000_000)
    initial = selector.ingest(PCM_CRUISE_4_ADDRESS, 2, cruise_4(), 0, 0)
    rolling = selector.ingest(PCM_CRUISE_4_ADDRESS, 2, cruise_4(0, 1, 0x1234567), 20_000_000, 20_000_000)
    self.assertEqual([item.reason for item in initial], ["initial"])
    self.assertEqual(rolling, [])

  def test_press_hold_release_records_edges_and_context(self):
    selector = FrameSelector(pre_button_frames=4)
    selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(), 0, 0)
    selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(counter=1), 10_000_000, 10_000_000)
    selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(counter=2), 20_000_000, 20_000_000)

    pressed = selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(0x80, 3), 30_000_000, 30_000_000)
    held = selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(0x80, 4), 40_000_000, 40_000_000)
    released = selector.ingest(PCM_CRUISE_4_ADDRESS, 1, cruise_4(0, 5), 80_000_000, 80_000_000)

    self.assertEqual([item.reason for item in pressed], ["pre_button", "pre_button", "button_press"])
    self.assertEqual(pressed[-1].decoded["names"], ["increase"])
    self.assertEqual([item.reason for item in held], ["button_held"])
    self.assertEqual([item.reason for item in released], ["button_release"])
    self.assertEqual(released[0].hold_ms, 50.0)

  def test_buses_are_tracked_independently(self):
    selector = FrameSelector()
    selector.ingest(PCM_CRUISE_4_ADDRESS, 0, cruise_4(), 0, 0)
    on_other_bus = selector.ingest(PCM_CRUISE_4_ADDRESS, 2, cruise_4(0x20), 1, 1)
    self.assertEqual(on_other_bus[0].reason, "initial_pressed")

  def test_cruise_set_state_changes_ignore_other_payload_churn(self):
    selector = FrameSelector(set_state_sample_ns=5_000_000_000)
    initial = selector.ingest(PCM_CRUISE_2_ADDRESS, 3, cruise_2(0xC0, 100), 0, 0)
    same = selector.ingest(PCM_CRUISE_2_ADDRESS, 3, cruise_2(0xC0, 100, filler=7), 1, 1)
    changed = selector.ingest(PCM_CRUISE_2_ADDRESS, 3, cruise_2(0xC0, 101), 2, 2)
    self.assertEqual(initial[0].reason, "initial")
    self.assertEqual(same, [])
    self.assertEqual(changed[0].reason, "cruise_state_change")

  def test_long_idle_capture_stays_sparse(self):
    selector = FrameSelector(idle_sample_ns=1_000_000_000)
    selected = 0
    for frame_index in range(5_000):
      mono_time_ns = frame_index * 20_000_000
      data = cruise_4(counter=frame_index, authenticator=frame_index)
      selected += len(selector.ingest(PCM_CRUISE_4_ADDRESS, 0, data, mono_time_ns, mono_time_ns))
    self.assertLessEqual(selected, 100)


if __name__ == "__main__":
  unittest.main()
