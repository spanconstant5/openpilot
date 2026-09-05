import json
import os
import tempfile
import unittest
from pathlib import Path

from openpilot.system.tss3_cruise_recorder.storage import (
  MARKER_NAME,
  ArchiveWriter,
  StatusStore,
  prepare_log_root,
  prune_completed,
  recover_active_files,
)


class TestStorage(unittest.TestCase):
  def test_writer_finishes_private_jsonl(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "logs"
      writer = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1_000_000_000, min_free_bytes=0)
      writer.write(({"type": "test", "value": 1},), 2, 2_000_000_000, flush=True)
      writer.close(3, 3_000_000_000)

      completed = list(root.glob("*.jsonl"))
      self.assertEqual(len(completed), 1)
      records = [json.loads(line) for line in completed[0].read_text(encoding="utf-8").splitlines()]
      self.assertEqual([record["type"] for record in records], ["session_start", "test", "part_end"])
      if os.name != "nt":
        self.assertEqual(completed[0].stat().st_mode & 0o777, 0o600)

  def test_rotation_uses_unique_names(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "logs"
      first = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1_000_000_000, min_free_bytes=0)
      first.close(2, 2_000_000_000)
      second = ArchiveWriter(root, start_mono_ns=1, start_wall_ns=1_000_000_000, min_free_bytes=0)
      second.close(2, 2_000_000_000)
      self.assertEqual(len({path.name for path in root.glob("*.jsonl")}), 2)

  def test_recovers_abandoned_active_file(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = prepare_log_root(Path(temporary) / "logs")
      active = root / "session-test-part-000.active"
      active.write_text('{"partial":true}\n', encoding="utf-8")
      recovered = recover_active_files(root)
      self.assertEqual(len(recovered), 1)
      self.assertFalse(active.exists())
      self.assertTrue(recovered[0].name.endswith(".recovered.jsonl"))

  def test_retention_removes_only_completed_logs(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = prepare_log_root(Path(temporary) / "logs")
      oldest = root / "a.jsonl"
      newest = root / "b.jsonl"
      active = root / "c.active"
      unrelated = root / "notes.txt"
      for path in (oldest, newest, active, unrelated):
        path.write_bytes(b"x" * 10)
      os.utime(oldest, ns=(1, 1))
      os.utime(newest, ns=(2, 2))

      removed = prune_completed(root, max_archive_bytes=10, min_free_bytes=0)
      self.assertEqual(removed, [oldest])
      self.assertTrue(newest.exists())
      self.assertTrue(active.exists())
      self.assertTrue(unrelated.exists())
      self.assertTrue((root / MARKER_NAME).exists())

  def test_low_disk_prunes_completed_logs(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = prepare_log_root(Path(temporary) / "logs")
      completed = root / "old.jsonl"
      completed.write_bytes(b"x")
      with self.assertRaises(OSError):
        prune_completed(root, max_archive_bytes=100, min_free_bytes=1,
                        free_space=lambda _path: 0)
      self.assertFalse(completed.exists())

  @unittest.skipIf(os.name == "nt", "creating symlinks is not reliably available on Windows")
  def test_symlink_log_root_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      base = Path(temporary)
      real = base / "real"
      real.mkdir()
      link = base / "link"
      link.symlink_to(real, target_is_directory=True)
      with self.assertRaises(RuntimeError):
        prepare_log_root(link)

  def test_status_write_is_atomic_json(self):
    with tempfile.TemporaryDirectory() as temporary:
      path = Path(temporary) / "status.json"
      StatusStore(path).write({"state": "running"})
      self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state": "running"})
      self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
  unittest.main()
