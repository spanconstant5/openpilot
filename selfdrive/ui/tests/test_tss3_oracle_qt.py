from pathlib import Path

from openpilot.selfdrive.car.toyota_tss3_oracle_kit import DEFAULT_ORACLE_TOOL, oracle_kit_compatibility


def test_frogpilot_qt_exposes_bundled_tss3_bringup():
  compatible, detail = oracle_kit_compatibility(DEFAULT_ORACLE_TOOL)
  assert compatible, detail

  source = (Path(__file__).parents[1] / "qt" / "offroad" / "developer_panel.cc").read_text(encoding="utf-8")
  assert 'tr("TSS3 Oracle Bringup")' in source
  assert '"ui-bringup"' in source
  assert '"tss3-request-signer-ui-status-v1"' in source
  assert '"cancel-requested"' in source
  assert 'CP.getBrand() == "toyota" && (CP.getFlags() & (1U << 12))' in source


def test_frogpilot_qt_cancel_is_cooperative():
  source = (Path(__file__).parents[1] / "qt" / "offroad" / "developer_panel.cc").read_text(encoding="utf-8")
  bringup = source[source.index("void DeveloperPanel::startTss3OracleBringup()"):
                   source.index("void DeveloperPanel::handleTss3OracleOutput()")]
  assert "cancel-requested" in bringup
  assert "terminate(" not in bringup
  assert "kill(" not in bringup
