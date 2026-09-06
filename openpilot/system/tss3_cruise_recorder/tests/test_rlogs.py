import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.system.tss3_cruise_recorder.rlogs import discover_rlogs, latest_routes, scan_can_messages


class FakeMessage:
  def __init__(self, kind, mono_time, frames=()):
    self._kind = kind
    self.logMonoTime = mono_time
    self.can = frames

  def which(self):
    return self._kind


class TestRlogs(unittest.TestCase):
  def test_discovers_and_groups_route_segments(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      root = Path(temporary_directory)
      old_route = root / "dongle_2026-09-05--old--0"
      new_zero = root / "dongle_2026-09-06--new--0"
      new_one = root / "dongle_2026-09-06--new--1"
      malformed = root / "not-a-segment"
      for directory in (old_route, new_zero, new_one, malformed):
        directory.mkdir()
        (directory / "rlog.zst").write_bytes(b"rlog")

      os.utime(old_route / "rlog.zst", ns=(1, 1))
      os.utime(new_zero / "rlog.zst", ns=(2, 2))
      os.utime(new_one / "rlog.zst", ns=(3, 3))

      routes = latest_routes(discover_rlogs(root), 1)
      self.assertEqual(len(routes), 1)
      self.assertEqual(routes[0][0], "dongle_2026-09-06--new")
      self.assertEqual([item.segment for item in routes[0][1]], [0, 1])

  def test_scan_tracks_physical_can_changes_and_ignores_tx_receipts(self):
    frames = [
      SimpleNamespace(src=0, address=0x123, dat=b"\x00\x10"),
      SimpleNamespace(src=0x80, address=0x123, dat=b"\x00\x10"),
    ]
    messages = [
      FakeMessage("carState", 50),
      FakeMessage("can", 100, frames),
      FakeMessage("can", 200, [SimpleNamespace(src=0, address=0x123, dat=b"\x01\x30")]),
    ]

    report = scan_can_messages(messages)
    self.assertEqual(report["physical_frames"], 2)
    self.assertEqual(report["ignored_tx_receipts"], 1)
    self.assertEqual(report["can_events"], 2)
    self.assertEqual(report["streams"], [{
      "bus": 0,
      "address": 0x123,
      "address_hex": "0x123",
      "length": 2,
      "frames": 2,
      "transitions": 1,
      "distinct_payloads": 2,
      "distinct_payloads_capped": False,
      "changed_bits_mask_hex": "0120",
      "first_mono_time_ns": 100,
      "last_mono_time_ns": 200,
    }])

  def test_package_has_no_transmit_api_or_automatic_process(self):
    package = Path(__file__).resolve().parents[1]
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    config = Path(__file__).resolve().parents[4] / "openpilot/system/manager/process_config.py"
    manager_source = config.read_text(encoding="utf-8")

    for banned in ("PubMaster", "sendcan", "can_send", "can_list_to_can_capnp"):
      self.assertNotIn(banned, source)
    self.assertNotIn("tss3cruiseprobed", manager_source)

  def test_rlog_scan_import_is_lazy(self):
    control = Path(__file__).resolve().parents[1] / "control.py"
    lines = control.read_text(encoding="utf-8").splitlines()
    import_line = next(index for index, line in enumerate(lines) if "from openpilot.cereal import log" in line)
    reader_line = next(index for index, line in enumerate(lines) if line.startswith("def _read_rlogs"))
    self.assertGreater(import_line, reader_line)


if __name__ == "__main__":
  unittest.main()
