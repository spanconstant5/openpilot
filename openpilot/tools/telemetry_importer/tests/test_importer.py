from pathlib import Path

from openpilot.tools.telemetry_importer import importer


def test_default_destination_is_cross_platform(monkeypatch, tmp_path):
  monkeypatch.setattr(Path, "home", lambda: tmp_path)
  assert importer.default_destination() == tmp_path / "Documents" / "Comma Telemetry"


def test_connected_device_uses_usb_without_network_fallback(monkeypatch, tmp_path):
  calls = []

  def fake_run_adb(_adb, _serial, arguments, binary=False):
    calls.append(arguments)
    return "List of devices attached\ncomma-usb\tdevice\n"

  monkeypatch.setattr(importer, "run_adb", fake_run_adb)
  assert importer.connected_device(tmp_path / "adb") == "comma-usb"
  assert calls == [["devices"]]


def test_connected_device_falls_back_to_comma_network(monkeypatch, tmp_path):
  device_checks = iter(("List of devices attached\n", "List of devices attached\n192.168.43.1:5555\tdevice\n"))
  calls = []

  def fake_run_adb(_adb, _serial, arguments, binary=False):
    calls.append(arguments)
    return next(device_checks) if arguments == ["devices"] else "connected"

  monkeypatch.setattr(importer, "run_adb", fake_run_adb)
  assert importer.connected_device(tmp_path / "adb") == "192.168.43.1:5555"
  assert calls == [["devices"], ["connect", "192.168.43.1:5555"], ["devices"]]


def test_connected_device_reports_unauthorized_separately(monkeypatch, tmp_path):
  monkeypatch.setattr(importer, "run_adb", lambda *_args, **_kwargs: "List of devices attached\ncomma\tunauthorized\n")
  try:
    importer.connected_device(tmp_path / "adb")
  except importer.ImportFailure as error:
    assert "visible but unauthorized" in str(error)
  else:
    raise AssertionError("unauthorized device was accepted")
