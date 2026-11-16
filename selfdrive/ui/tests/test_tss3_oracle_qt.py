from pathlib import Path

from openpilot.selfdrive.car.toyota_tss3_oracle_kit import DEFAULT_ORACLE_TOOL, oracle_kit_compatibility


def test_frogpilot_qt_exposes_bundled_tss3_bringup():
  compatible, detail = oracle_kit_compatibility(DEFAULT_ORACLE_TOOL)
  assert compatible, detail

  source = (Path(__file__).parents[1] / "qt" / "widgets" / "tss3_oracle_control.cc").read_text(encoding="utf-8")
  frogpilot_settings = (Path(__file__).parents[3] / "frogpilot" / "ui" / "qt" / "offroad" / "frogpilot_settings.cc").read_text(encoding="utf-8")
  assert 'tr("TSS3 Oracle Bringup")' in source
  assert '"ui-bringup"' in source
  assert '"tss3-request-signer-ui-status-v1"' in source
  assert '"cancel-requested"' in source
  assert '"CarParamsPersistent", "CarParamsCache", "CarParamsPrevRoute"' in source
  assert 'version.find("8965F1208000")' in source
  assert 'tr("START CAR ONCE")' in source
  assert "list->addItem(new Tss3OracleControl(this))" in frogpilot_settings
  assert frogpilot_settings.index("list->addItem(new Tss3OracleControl(this))") < frogpilot_settings.index("createPanelButtons(list)")


def test_frogpilot_qt_cancel_is_cooperative():
  source = (Path(__file__).parents[1] / "qt" / "widgets" / "tss3_oracle_control.cc").read_text(encoding="utf-8")
  bringup = source[source.index("void Tss3OracleControl::startBringup()"):
                   source.index("void Tss3OracleControl::handleOutput()")]
  assert "cancel-requested" in bringup
  assert "terminate(" not in bringup
  assert "kill(" not in bringup


def test_frogpilot_mici_exposes_bundled_tss3_bringup():
  root = Path(__file__).parents[3]
  source = (root / "frogpilot" / "ui" / "mici" / "tss3_oracle.py").read_text(encoding="utf-8")
  settings = (root / "selfdrive" / "ui" / "mici" / "layouts" / "settings" / "settings.py").read_text(encoding="utf-8")
  assert '"ui-bringup"' in source
  assert '"cancel-requested"' in source
  assert '"tss3-request-signer-ui-status-v1"' in source
  assert 'CAROLLA_EPS_FIRMWARE = b"8965F1208000"' in source
  assert '("CarParamsPersistent", "CarParamsCache", "CarParamsPrevRoute")' in source
  assert "Tss3OracleBigButton()" in settings


def test_frogpilot_developer_panel_is_always_reachable():
  settings = (Path(__file__).parents[1] / "qt" / "offroad" / "settings.cc").read_text(encoding="utf-8")
  update = settings[settings.index("void SettingsWindow::updateDeveloperToggle") :]
  assert "btn->setVisible(true)" in update
  assert "tuningLevel >= 3" not in update
