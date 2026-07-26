from pathlib import Path

from openpilot.tools.telemetry_importer import importer


def test_default_destination_is_cross_platform(monkeypatch, tmp_path):
  monkeypatch.setattr(Path, "home", lambda: tmp_path)
  assert importer.default_destination() == tmp_path / "Documents" / "Comma Telemetry"
