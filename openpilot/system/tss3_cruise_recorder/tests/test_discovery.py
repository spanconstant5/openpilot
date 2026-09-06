import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.system.tss3_cruise_recorder.control import _summarize
from openpilot.system.tss3_cruise_recorder.discovery import CAPTURE_METADATA, DiscoverySession
from openpilot.system.tss3_cruise_recorder.storage import ArchiveWriter, recover_active_files


class TestDiscovery(unittest.TestCase):
  def test_unknown_addresses_short_and_fd_frames_survive_compressed_rotation(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      writer = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1, min_free_bytes=0,
                             compressed=True, metadata=CAPTURE_METADATA, max_part_bytes=1200)
      session = DiscoverySession(writer)
      original = [
        [0, 0x123, "80"], [2, 0x1D3, "12" * 16], [1, 0x1ABCDEF, "34" * 64], [0, 0x24D, ""],
      ]
      can = [SimpleNamespace(src=bus, address=address, dat=bytes.fromhex(payload)) for bus, address, payload in original]
      can += [SimpleNamespace(src=0x80, address=0x123, dat=b"\xff"), SimpleNamespace(src=0xC0, address=0x123, dat=b"\xff")]
      for stamp in range(2, 12):
        session.process_message(SimpleNamespace(can=can, valid=False, logMonoTime=stamp), stamp + 5, stamp + 10)
      writer.close(20, 30)
      paths = sorted(root.glob("*.jsonl.gz"))
      self.assertGreater(len(paths), 1)
      batches = []
      for path in paths:
        with gzip.open(path, "rt") as stream:
          records = [json.loads(line) for line in stream]
        self.assertEqual(records[0]["capture"], CAPTURE_METADATA)
        self.assertEqual(records[-1]["type"], "part_end")
        batches += [record for record in records if record["type"] == "can_batch"]
      self.assertEqual(len(batches), 10)
      self.assertTrue(all(record["frames"] == original for record in batches))
      self.assertTrue(all(not record["source_valid"] for record in batches))
      self.assertEqual(session.snapshot()["physical_frames"], 40)
      self.assertEqual(session.snapshot()["ignored_non_physical"], 20)
      _, _, errors, inventory = _summarize(paths)
      self.assertEqual(errors, 0)
      self.assertEqual(sum(inventory.values()), 40)

  def test_interrupted_gzip_retains_flushed_records_and_reports_truncation(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      writer = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1, min_free_bytes=0, compressed=True)
      writer.write([{"type": "can_batch", "frames": [[0, 0x123, "80"]]}], 2, 2, flush=True)
      active = writer.active_path
      flushed = active.read_bytes()
      writer.abort()
      # Simulate power loss: only the bytes flushed before the gzip footer survived.
      active.write_bytes(flushed)
      recovered = recover_active_files(root)
      self.assertEqual(len(recovered), 1)
      reasons, _, errors, inventory = _summarize(recovered)
      self.assertEqual(reasons["raw_can_batch"], 1)
      self.assertEqual(errors, 1)
      self.assertEqual(inventory[(0, 0x123, 1)], 1)

  def test_disk_floor_is_checked_before_part_rotation(self):
    with tempfile.TemporaryDirectory() as directory:
      available = [100]
      writer = ArchiveWriter(Path(directory), start_mono_ns=0, start_wall_ns=1, min_free_bytes=50,
                             free_space=lambda _: available[0], compressed=True)
      available[0] = 0
      try:
        with self.assertRaises(OSError):
          writer.maintain(6_000_000_000)
      finally:
        writer.abort()

  def test_gzip_files_count_toward_retention(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      writer = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1, min_free_bytes=0, compressed=True,
                             max_archive_bytes=1)
      writer.close(2, 2)
      self.assertEqual(list(root.glob("*.jsonl.gz")), [])


if __name__ == "__main__":
  unittest.main()
