"""Select useful evidence while ignoring rolling counter/authenticator churn."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace

from .protocol import PCM_CRUISE_2_ADDRESS, PCM_CRUISE_4_ADDRESS, decode_cruise_buttons, decode_cruise_set_state


IDLE_SAMPLE_NS = 1_000_000_000
SET_STATE_SAMPLE_NS = 5_000_000_000
PRE_BUTTON_FRAMES = 16


@dataclass(frozen=True)
class SelectedFrame:
  address: int
  bus: int
  data: bytes
  mono_time_ns: int
  wall_time_ns: int
  reason: str
  decoded: dict[str, object]
  previous_buttons: tuple[str, ...] = ()
  hold_ms: float | None = None

  def with_reason(self, reason: str) -> SelectedFrame:
    return replace(self, reason=reason)

  def to_record(self) -> dict[str, object]:
    result: dict[str, object] = {
      "type": "can_frame",
      "reason": self.reason,
      "mono_time_ns": self.mono_time_ns,
      "wall_time_ns": self.wall_time_ns,
      "address": self.address,
      "address_hex": f"0x{self.address:03X}",
      "bus": self.bus,
      "data_hex": self.data.hex(),
      "decoded": self.decoded,
    }
    if self.previous_buttons:
      result["previous_buttons"] = list(self.previous_buttons)
    if self.reason in ("button_press", "button_change", "button_release"):
      current = self.decoded.get("names", [])
      current_names = set(current) if isinstance(current, list) else set()
      previous_names = set(self.previous_buttons)
      result["pressed_buttons"] = sorted(current_names - previous_names)
      result["released_buttons"] = sorted(previous_names - current_names)
    if self.hold_ms is not None:
      result["hold_ms"] = round(self.hold_ms, 3)
    return result


@dataclass
class _ButtonState:
  mask: int
  names: tuple[str, ...]
  last_written_ns: int
  press_started_ns: int | None = None


@dataclass
class _SetState:
  semantic_key: tuple[bool, int, int, int, bool, bool]
  last_written_ns: int


class FrameSelector:
  """Keep button edges/holds plus sparse idle and cruise-state samples."""

  def __init__(self, idle_sample_ns: int = IDLE_SAMPLE_NS, set_state_sample_ns: int = SET_STATE_SAMPLE_NS,
               pre_button_frames: int = PRE_BUTTON_FRAMES):
    self.idle_sample_ns = idle_sample_ns
    self.set_state_sample_ns = set_state_sample_ns
    self._buttons: dict[tuple[int, int], _ButtonState] = {}
    self._set_states: dict[tuple[int, int], _SetState] = {}
    self._pre_button: dict[tuple[int, int], deque[SelectedFrame]] = defaultdict(lambda: deque(maxlen=pre_button_frames))

  @staticmethod
  def _selected(address: int, bus: int, data: bytes, mono_time_ns: int, wall_time_ns: int,
                reason: str, decoded: dict[str, object], previous_buttons: tuple[str, ...] = (),
                hold_ms: float | None = None) -> SelectedFrame:
    return SelectedFrame(address, bus, data, mono_time_ns, wall_time_ns, reason, decoded, previous_buttons, hold_ms)

  def ingest(self, address: int, bus: int, data: bytes, mono_time_ns: int,
             wall_time_ns: int) -> list[SelectedFrame]:
    if address == PCM_CRUISE_4_ADDRESS:
      return self._ingest_buttons(address, bus, data, mono_time_ns, wall_time_ns)
    if address == PCM_CRUISE_2_ADDRESS:
      return self._ingest_set_state(address, bus, data, mono_time_ns, wall_time_ns)
    return []

  def _ingest_buttons(self, address: int, bus: int, data: bytes, mono_time_ns: int,
                      wall_time_ns: int) -> list[SelectedFrame]:
    decoded = decode_cruise_buttons(data)
    decoded_dict = decoded.to_dict()
    key = (bus, address)
    previous = self._buttons.get(key)
    current = self._selected(address, bus, data, mono_time_ns, wall_time_ns, "", decoded_dict)

    if previous is None:
      reason = "initial_pressed" if decoded.mask else "initial"
      press_started = mono_time_ns if decoded.mask else None
      self._buttons[key] = _ButtonState(decoded.mask, decoded.names, mono_time_ns, press_started)
      return [current.with_reason(reason)]

    if decoded.mask != previous.mask:
      if previous.mask == 0 and decoded.mask != 0:
        reason = "button_press"
        press_started_ns = mono_time_ns
        selected = [frame.with_reason("pre_button") for frame in self._pre_button[key]]
        self._pre_button[key].clear()
      elif previous.mask != 0 and decoded.mask == 0:
        reason = "button_release"
        press_started_ns = None
        started = previous.press_started_ns if previous.press_started_ns is not None else mono_time_ns
        hold_ms = max(0, mono_time_ns - started) / 1_000_000
        current = replace(current, hold_ms=hold_ms)
        selected = []
      else:
        reason = "button_change"
        press_started_ns = previous.press_started_ns if previous.press_started_ns is not None else mono_time_ns
        selected = []

      current = replace(current, previous_buttons=previous.names)
      selected.append(current.with_reason(reason))
      self._buttons[key] = _ButtonState(decoded.mask, decoded.names, mono_time_ns, press_started_ns)
      return selected

    if decoded.mask:
      self._buttons[key].last_written_ns = mono_time_ns
      return [current.with_reason("button_held")]

    if mono_time_ns - previous.last_written_ns >= self.idle_sample_ns:
      previous.last_written_ns = mono_time_ns
      return [current.with_reason("idle_sample")]
    self._pre_button[key].append(current)
    return []

  def _ingest_set_state(self, address: int, bus: int, data: bytes, mono_time_ns: int,
                        wall_time_ns: int) -> list[SelectedFrame]:
    decoded = decode_cruise_set_state(data)
    key = (bus, address)
    previous = self._set_states.get(key)

    if previous is None:
      reason = "initial"
    elif decoded.semantic_key != previous.semantic_key:
      reason = "cruise_state_change"
    elif mono_time_ns - previous.last_written_ns >= self.set_state_sample_ns:
      reason = "state_sample"
    else:
      return []

    self._set_states[key] = _SetState(decoded.semantic_key, mono_time_ns)
    return [self._selected(address, bus, data, mono_time_ns, wall_time_ns, reason, decoded.to_dict())]
