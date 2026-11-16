from pathlib import Path

from openpilot.selfdrive.car.toyota_tss3_oracle_kit import DEFAULT_ORACLE_TOOL, oracle_kit_compatibility


def test_frogpilot_qt_exposes_bundled_tss3_bringup():
  compatible, detail = oracle_kit_compatibility(DEFAULT_ORACLE_TOOL)
  assert compatible, detail

  source = (Path(__file__).parents[1] / "qt" / "widgets" / "tss3_oracle_control.cc").read_text(encoding="utf-8")
  utilities = (Path(__file__).parents[3] / "frogpilot" / "ui" / "qt" / "offroad" / "utilities.cc").read_text(encoding="utf-8")
  assert 'tr("TSS3 Oracle Bringup")' in source
  assert '"ui-bringup"' in source
  assert '"tss3-request-signer-ui-status-v1"' in source
  assert '"cancel-requested"' in source
  assert 'CP.getBrand() == "toyota" && (CP.getFlags() & (1U << 12))' in source
  assert "addItem(new Tss3OracleControl(this))" in utilities


def test_frogpilot_qt_cancel_is_cooperative():
  source = (Path(__file__).parents[1] / "qt" / "widgets" / "tss3_oracle_control.cc").read_text(encoding="utf-8")
  bringup = source[source.index("void Tss3OracleControl::startBringup()"):
                   source.index("void Tss3OracleControl::handleOutput()")]
  assert "cancel-requested" in bringup
  assert "terminate(" not in bringup
  assert "kill(" not in bringup
