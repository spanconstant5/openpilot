import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from openpilot.system.tss3_cruise_recorder.control import _summarize
from openpilot.system.tss3_cruise_recorder.storage import ArchiveWriter


class TestDaemon(unittest.TestCase):
  def test_source_error_retry_then_clean_shutdown_retains_discovery_statistics(self):
    # Import against subscriber-only substitutes: native cereal is unavailable on this test host.
    messaging = ModuleType("openpilot.cereal.messaging")
    messaging.sub_sock = Mock(return_value=object())
    messaging.recv_one = Mock()
    swaglog = ModuleType("openpilot.common.swaglog")
    swaglog.cloudlog = Mock()
    source = Path(__file__).resolve().parents[1] / "daemon.py"
    spec = importlib.util.spec_from_file_location("openpilot.system.tss3_cruise_recorder._tested_daemon", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {messaging.__name__: messaging, swaglog.__name__: swaglog}):
      spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      status_path = root / "status.json"
      with patch.dict(os.environ, {"TSS3_CRUISE_LOG_ROOT": str(root / "logs"), "TSS3_CRUISE_STATUS_PATH": str(status_path)}):
        daemon = module.RecorderDaemon()
        received = [0]

        def receive(_socket):
          received[0] += 1
          if received[0] == 1:
            raise OSError("simulated receive disconnect")
          daemon.request_stop()
          return SimpleNamespace(logMonoTime=module.time.monotonic_ns(), valid=True,
                                 can=[SimpleNamespace(address=0x123, src=1, dat=b"\x80")])

        messaging.recv_one.side_effect = receive
        with patch.object(daemon, "_backoff") as backoff, patch.object(
          module, "ArchiveWriter", side_effect=lambda **kwargs: ArchiveWriter(min_free_bytes=0, **kwargs),
        ):
          daemon.run()
        backoff.assert_called_once_with(1.0)
        status = json.loads(status_path.read_text())
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(status["capture_version"], "discovery-v2")
        self.assertEqual(status["physical_frames"], 1)
        self.assertEqual(status["discovered_buses"], [1])
        self.assertIsNone(status["active_file"])
        self.assertIsNone(status["last_error"])
        _, _, errors, inventory = _summarize(list((root / "logs").glob("*.jsonl.gz")))
        self.assertEqual(errors, 0)
        self.assertEqual(inventory[(1, 0x123, 1)], 1)
        messaging.sub_sock.assert_called_with("can", conflate=False, timeout=1000)


if __name__ == "__main__":
  unittest.main()
