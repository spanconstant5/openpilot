import unittest
from dataclasses import dataclass

from openpilot.system.tss3_cruise_recorder.protocol import PCM_CRUISE_4_ADDRESS
from openpilot.system.tss3_cruise_recorder.session import PassiveRecorderSession


@dataclass
class FakeFrame:
  address: int
  dat: bytes
  src: int


@dataclass
class FakeMessage:
  can: list[FakeFrame]
  logMonoTime: int = 0


class FakeWriter:
  active_path = None

  def __init__(self):
    self.batches: list[tuple[list[dict[str, object]], bool]] = []

  def write(self, records, _mono_time_ns: int, _wall_time_ns: int, flush: bool = False) -> None:
    self.batches.append((list(records), flush))


class TestPassiveRecorderSession(unittest.TestCase):
  def test_returned_and_rejected_frames_are_ignored(self):
    writer = FakeWriter()
    session = PassiveRecorderSession(writer)
    message = FakeMessage([
      FakeFrame(PCM_CRUISE_4_ADDRESS, b"\x80" + b"\0" * 7, 0x80),
      FakeFrame(PCM_CRUISE_4_ADDRESS, b"\x80" + b"\0" * 7, 0xC2),
    ])
    self.assertFalse(session.process_message(message, 1, 1))
    self.assertEqual(writer.batches, [])
    self.assertEqual(session.stats.ignored_non_physical, 2)

  def test_button_edge_flushes_without_any_transmit_dependency(self):
    writer = FakeWriter()
    session = PassiveRecorderSession(writer)
    session.process_message(FakeMessage([FakeFrame(PCM_CRUISE_4_ADDRESS, b"\0" * 8, 2)]), 1, 1)
    edge = session.process_message(
      FakeMessage([FakeFrame(PCM_CRUISE_4_ADDRESS, b"\x80" + b"\0" * 7, 2)]), 2, 2,
    )
    self.assertTrue(edge)
    self.assertTrue(writer.batches[-1][1])
    self.assertEqual(writer.batches[-1][0][-1]["reason"], "button_press")
    self.assertEqual(writer.batches[-1][0][-1]["pressed_buttons"], ["increase"])
    self.assertEqual(session.stats.button_presses, {"increase": 1})

    session.process_message(FakeMessage([FakeFrame(PCM_CRUISE_4_ADDRESS, b"\0" * 8, 2)]), 3, 3)
    self.assertEqual(session.stats.release_edges, 1)
    self.assertEqual(writer.batches[-1][0][-1]["released_buttons"], ["increase"])

  def test_bad_length_is_ignored(self):
    writer = FakeWriter()
    session = PassiveRecorderSession(writer)
    session.process_message(FakeMessage([FakeFrame(PCM_CRUISE_4_ADDRESS, b"\0" * 7, 1)]), 1, 1)
    self.assertEqual(session.stats.ignored_wrong_length, 1)
    self.assertEqual(writer.batches, [])


if __name__ == "__main__":
  unittest.main()
