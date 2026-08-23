from openpilot.tools.telemetry_portal.server import PortalError, _safe_remote_path, resolve_target


def test_resolve_private_ip_and_local_arp_mac():
  assert resolve_target("10.0.0.18") == "10.0.0.18"
  arp = "  10.0.0.18          aa-bb-cc-dd-ee-ff     dynamic\n"
  assert resolve_target("AA:BB:CC:DD:EE:FF", arp) == "10.0.0.18"


def test_rejects_public_targets_and_non_recording_paths():
  try:
    resolve_target("8.8.8.8")
  except PortalError as error:
    assert "private" in str(error)
  else:
    raise AssertionError("public target was accepted")
  assert _safe_remote_path("/data/media/0/realdata/route--0--fcamera.hevc").name == "route--0--fcamera.hevc"
  try:
    _safe_remote_path("/data/media/0/telemetry/private.txt")
  except PortalError as error:
    assert "recording" in str(error)
  else:
    raise AssertionError("non-recording file was accepted")


def test_accepts_eps_telescope_export_bundle():
  path = "/data/media/0/telemetry/eps_telescope_exports/20260819T120000Z.eps-telescope.zip"
  assert str(_safe_remote_path(path)) == path
