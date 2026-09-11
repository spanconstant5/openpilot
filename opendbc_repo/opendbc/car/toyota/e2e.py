"""AUTOSAR E2E CRC used by the TSS 3.0 camera request at address 0x160."""

E2E_160_DATA_ID = 0x444A


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
