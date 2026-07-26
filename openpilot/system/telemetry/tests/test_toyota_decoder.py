from openpilot.system.telemetry.toyota_decoder import derive_ev_mode, tss_status


def test_ev_mode_requires_a_real_engine_signal():
  assert derive_ev_mode(None, None) is None
  assert derive_ev_mode(0.0, None) is True
  assert derive_ev_mode(1500.0, None) is False
  assert derive_ev_mode(1500.0, False) is True


def test_tss_active_only_when_radar_cruise_or_lta_is_engaged():
  assert tss_status(True, False, False) == "TSS READY"
  assert tss_status(False, False, None) == "TSS OFF"
  assert tss_status(True, True, False) == "TSS RADAR CRUISE ACTIVE"
  assert tss_status(True, False, True) == "TSS LTA ACTIVE"
  assert tss_status(True, True, True) == "TSS ACTIVE · RADAR + LTA"
  assert tss_status(True, False, False, stock_aeb=True) == "TSS AEB"
