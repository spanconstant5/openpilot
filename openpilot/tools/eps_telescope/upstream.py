"""Load the pinned upstream EPS Telescope submodule and payload."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


UPSTREAM_ROOT = Path(__file__).resolve().parent / "upstream"
PAYLOAD_PATH = UPSTREAM_ROOT / "shellcode" / "build" / "deep_probe.bin"
PAYLOAD_SHA256 = "52a47a3fab27a479b051453c11fdab05a6088c2df7fa8f2d924178e4b31337eb"


def load_probe_modules():
  package_dir = UPSTREAM_ROOT / "eps_probe"
  if not package_dir.is_dir():
    raise RuntimeError(
      "EPS Telescope dependency is missing. Reinstall this fork so Git submodules are initialized."
    )

  upstream_path = str(UPSTREAM_ROOT)
  if upstream_path not in sys.path:
    sys.path.insert(0, upstream_path)

  from eps_probe import deep_probe, report, uds_probe, vehicle_fingerprint
  from eps_probe.transport import DID_APPLICATION, EcuTransport, EnvelopeAuthError, load_openpilot_bindings

  return deep_probe, report, uds_probe, vehicle_fingerprint, DID_APPLICATION, EcuTransport, EnvelopeAuthError, load_openpilot_bindings


def load_payload() -> bytes:
  if not PAYLOAD_PATH.is_file():
    raise RuntimeError(
      "EPS Telescope payload is missing. Reinstall this fork so Git submodules are initialized."
    )
  payload = PAYLOAD_PATH.read_bytes()
  digest = hashlib.sha256(payload).hexdigest()
  if digest != PAYLOAD_SHA256:
    raise RuntimeError(f"EPS Telescope payload verification failed: {digest}")
  return payload
