import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from openpilot.selfdrive.car.toyota_tss3_oracle_status import STATUS_SCHEMA, OracleStatus
from openpilot.selfdrive.ui.tss3_oracle_runner import CANCEL_FILENAME, Tss3OracleRunner, request_cooperative_cancel


def status_row(**overrides):
  return {
    "schema": STATUS_SCHEMA, "stage": "done", "title": "Bringup complete",
    "detail": "All checks passed.", "progress": 100, "done": True, "error": False,
    **overrides,
  }


class TestOracleStatus(unittest.TestCase):
  def test_completion_requires_zero_exit(self):
    for returncode in (0, 2):
      with self.subTest(returncode=returncode):
        report = OracleStatus()
        report.feed(json.dumps(status_row()))
        result = report.finish(returncode)
        self.assertIs(result["done"], returncode == 0)
        self.assertIs(result["error"], returncode != 0)

  def test_exit_without_completion_is_not_success(self):
    report = OracleStatus()
    result = report.finish(0)
    self.assertIs(result["error"], True)
    self.assertIs(result["done"], False)

  def test_first_error_wins(self):
    error = status_row(stage="error", done=False, error=True, detail="Original failure.", progress=0)
    report = OracleStatus()
    self.assertEqual(report.feed(json.dumps(error)), error)
    self.assertIsNone(report.feed(json.dumps(status_row())))
    self.assertEqual(report.finish(0), error)

  def test_malformed_status_cannot_report_success(self):
    report = OracleStatus()
    self.assertIsNone(report.feed(json.dumps(status_row(progress=True))))
    self.assertIs(report.finish(0)["error"], True)

  def test_completion_is_not_displayed_before_process_exit(self):
    runner = Tss3OracleRunner(start=False)

    def wait_for_exit():
      self.assertEqual(runner.snapshot()["stage"], "finishing")
      self.assertIs(runner.snapshot()["done"], False)
      return 0

    runner._proc = Mock(stdout=io.StringIO(json.dumps(status_row()) + "\n"), wait=wait_for_exit)
    runner._reader()
    self.assertIs(runner.snapshot()["done"], True)

  def test_cancel_is_a_cooperative_file_request(self):
    with tempfile.TemporaryDirectory() as td:
      run_dir = Path(td) / "run"
      request_cooperative_cancel(run_dir)
      self.assertEqual((run_dir / CANCEL_FILENAME).read_text(encoding="utf-8"), "cancel\n")


if __name__ == "__main__":
  unittest.main()
