"""Small, dependency-free decoders for the CAN frames captured by the recorder."""

from __future__ import annotations

from dataclasses import asdict, dataclass


PCM_CRUISE_2_ADDRESS = 0x1D3
PCM_CRUISE_4_ADDRESS = 0x24D
TARGET_ADDRESSES = frozenset((PCM_CRUISE_2_ADDRESS, PCM_CRUISE_4_ADDRESS))
FRAME_LENGTH = 8
PHYSICAL_BUS_LIMIT = 0x80

BUTTON_BITS = (
  ("distance", 1 << 2),
  ("cancel", 1 << 4),
  ("decrease", 1 << 5),
  ("enable", 1 << 6),
  ("increase", 1 << 7),
)
BUTTON_MASK = sum(bit for _name, bit in BUTTON_BITS)


@dataclass(frozen=True)
class CruiseButtons:
  mask: int
  names: tuple[str, ...]
  counter: int
  reset_flag: int
  message_counter_lower: int
  authenticator: int

  def to_dict(self) -> dict[str, object]:
    result = asdict(self)
    result["names"] = list(self.names)
    result["authenticator_hex"] = f"0x{self.authenticator:07x}"
    return result


@dataclass(frozen=True)
class CruiseSetState:
  brake_pressed: bool
  follow_distance: int
  main_on: bool
  low_speed_lockout: int
  set_speed_kph: int
  acc_faulted: bool
  checksum: int
  expected_checksum: int
  checksum_valid: bool

  @property
  def semantic_key(self) -> tuple[bool, int, int, int, bool, bool]:
    return (self.main_on, self.follow_distance, self.low_speed_lockout, self.set_speed_kph,
            self.acc_faulted, self.checksum_valid)

  def to_dict(self) -> dict[str, object]:
    return asdict(self)


def is_physical_bus(source: int) -> bool:
  """Panda uses 0x80/0xC0 offsets for TX receipts/rejections; exclude both."""
  return 0 <= source < PHYSICAL_BUS_LIMIT


def _require_frame(data: bytes) -> None:
  if len(data) != FRAME_LENGTH:
    raise ValueError(f"expected {FRAME_LENGTH} bytes, got {len(data)}")


def decode_cruise_buttons(data: bytes) -> CruiseButtons:
  _require_frame(data)
  mask = data[0] & BUTTON_MASK
  return CruiseButtons(
    mask=mask,
    names=tuple(name for name, bit in BUTTON_BITS if mask & bit),
    counter=data[3] & 0x0F,
    authenticator=((data[4] & 0x0F) << 24) | (data[5] << 16) | (data[6] << 8) | data[7],
    reset_flag=(data[4] >> 4) & 0x03,
    message_counter_lower=(data[4] >> 6) & 0x03,
  )


def toyota_checksum(address: int, data_without_checksum: bytes, frame_length: int = FRAME_LENGTH) -> int:
  return ((address & 0xFF) + ((address >> 8) & 0xFF) + frame_length + sum(data_without_checksum)) & 0xFF


def decode_cruise_set_state(data: bytes) -> CruiseSetState:
  _require_frame(data)
  expected = toyota_checksum(PCM_CRUISE_2_ADDRESS, data[:-1])
  return CruiseSetState(
    brake_pressed=bool(data[0] & 0x08),
    follow_distance=(data[1] >> 3) & 0x03,
    main_on=bool(data[1] & 0x80),
    low_speed_lockout=(data[1] >> 5) & 0x03,
    set_speed_kph=data[2],
    acc_faulted=bool(data[5] & 0x80),
    checksum=data[7],
    expected_checksum=expected,
    checksum_valid=data[7] == expected,
  )
