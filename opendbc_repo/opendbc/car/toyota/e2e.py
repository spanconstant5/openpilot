"""AUTOSAR E2E CRC used by the TSS 3.0 camera requests.

0x160 ADAS_ACC_REQUEST (32B, DataID 0x444A) carries longitudinal.
0x1A0 ADAS_STEER_COMMAND (48B, DataID 0xBEA8) carries lateral.
Both are keyless AUTOSAR E2E (CRC-16/CCITT over BYTE02..end + DataID LE, stored LE in
bytes 0-1) — no SecOC MAC. The EPS is patched to ignore SecOC, so a recomputed E2E CRC
is sufficient for the car to accept a modify-and-forward frame.
"""

E2E_160_DATA_ID = 0x444A
E2E_1A0_DATA_ID = 0xBEA8


def _crc16_ccitt(data: bytes) -> int:
  reg = 0
  for byte in data:
    reg ^= byte << 8
    for _ in range(8):
      reg = ((reg << 1) ^ 0x1021) & 0xFFFF if reg & 0x8000 else (reg << 1) & 0xFFFF
  return reg


def e2e_160_checksum(payload: bytes, data_id: int = E2E_160_DATA_ID) -> int:
  if len(payload) != 32:
    raise ValueError(f"0x160 payload must be 32 bytes, got {len(payload)}")
  return _crc16_ccitt(payload[2:] + data_id.to_bytes(2, "little"))


def apply_e2e_160(payload: bytes, counter: int | None = None) -> bytes:
  if len(payload) != 32:
    raise ValueError(f"0x160 payload must be 32 bytes, got {len(payload)}")
  buf = bytearray(payload)
  if counter is not None:
    buf[2] = counter & 0xFF
  crc = e2e_160_checksum(buf)
  buf[0:2] = crc.to_bytes(2, "little")
  return bytes(buf)


def e2e_160_valid(payload: bytes) -> bool:
  return len(payload) == 32 and int.from_bytes(payload[0:2], "little") == e2e_160_checksum(payload)


def e2e_1a0_checksum(payload: bytes, data_id: int = E2E_1A0_DATA_ID) -> int:
  if len(payload) != 48:
    raise ValueError(f"0x1A0 payload must be 48 bytes, got {len(payload)}")
  return _crc16_ccitt(payload[2:] + data_id.to_bytes(2, "little"))


def apply_e2e_1a0(payload: bytes, counter: int | None = None) -> bytes:
  if len(payload) != 48:
    raise ValueError(f"0x1A0 payload must be 48 bytes, got {len(payload)}")
  buf = bytearray(payload)
  if counter is not None:
    buf[2] = counter & 0xFF
  crc = e2e_1a0_checksum(buf)
  buf[0:2] = crc.to_bytes(2, "little")
  return bytes(buf)


def e2e_1a0_valid(payload: bytes) -> bool:
  return len(payload) == 48 and int.from_bytes(payload[0:2], "little") == e2e_1a0_checksum(payload)
