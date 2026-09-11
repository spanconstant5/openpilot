import runpy
from pathlib import Path


def test_corolla_census_is_complete_evidence_but_not_an_automatic_identity():
  root = Path(__file__).resolve().parents[2]
  toyota_dir = root / "opendbc_repo/opendbc/car/toyota"
  namespace = runpy.run_path(toyota_dir / "tss3_census.py")
  census = namespace["COROLLA_TSS3_CAN_CENSUS"]
  sources = namespace["COROLLA_TSS3_CENSUS_SOURCES"]

  assert len(census) == 152
  assert census[0x025] == 32
  assert census[0x0AA] == 8
  assert census[0x0D7] == 32
  assert census[0x7D8] == 8
  fingerprints_source = (toyota_dir / "fingerprints.py").read_text()
  assert "CAR.TOYOTA_COROLLA_TSS3:" not in fingerprints_source
  assert set(sources) == {
    "segment_0_zst_sha256",
    "segment_10_raw_sha256",
    "segment_10_evidence_zst_sha256",
  }
