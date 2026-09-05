"""Pure capture-session logic, kept separate from cereal messaging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .protocol import FRAME_LENGTH, TARGET_ADDRESSES, is_physical_bus
from .selector import FrameSelector, SelectedFrame


EDGE_REASONS = frozenset(("button_press", "button_change", "button_release"))


class RecordWriter(Protocol):
  active_path: object

  def write(self, records, mono_time_ns: int, wall_time_ns: int, flush: bool = False) -> None:
    ...


@dataclass
class RecorderStats:
  observed_frames: int = 0
  selected_frames: int = 0
  ignored_non_physical: int = 0
  ignored_wrong_length: int = 0
  press_edges: int = 0
  release_edges: int = 0
  discovered_buses: set[int] = field(default_factory=set)
  button_presses: dict[str, int] = field(default_factory=dict)
  last_physical_frame_mono_ns: int | None = None
  last_physical_frame_wall_ns: int | None = None

  def update_selected(self, selected: list[SelectedFrame]) -> None:
    self.selected_frames += len(selected)
    for frame in selected:
      if frame.reason in EDGE_REASONS:
        current = frame.decoded.get("names", [])
        current_names = set(current) if isinstance(current, list) else set()
        previous_names = set(frame.previous_buttons)
        pressed = current_names - previous_names
        released = previous_names - current_names
        if pressed:
          self.press_edges += 1
        if released:
          self.release_edges += 1
        for name in pressed:
          if isinstance(name, str):
            self.button_presses[name] = self.button_presses.get(name, 0) + 1


class PassiveRecorderSession:
  """Consume CAN event objects and write only selected physical RX evidence."""

  def __init__(self, writer: RecordWriter, selector: FrameSelector | None = None):
    self.writer = writer
    self.selector = selector or FrameSelector()
    self.stats = RecorderStats()

  def process_message(self, message, fallback_mono_ns: int, wall_time_ns: int) -> bool:
    message_mono_ns = int(message.logMonoTime) or fallback_mono_ns
    selected: list[SelectedFrame] = []
    edge_seen = False
    for frame in message.can:
      address = int(frame.address)
      if address not in TARGET_ADDRESSES:
        continue
      self.stats.observed_frames += 1
      source = int(frame.src)
      if not is_physical_bus(source):
        self.stats.ignored_non_physical += 1
        continue
      data = bytes(frame.dat)
      if len(data) != FRAME_LENGTH:
        self.stats.ignored_wrong_length += 1
        continue

      self.stats.discovered_buses.add(source)
      self.stats.last_physical_frame_mono_ns = message_mono_ns
      self.stats.last_physical_frame_wall_ns = wall_time_ns
      chosen = self.selector.ingest(address, source, data, message_mono_ns, wall_time_ns)
      edge_seen = edge_seen or any(item.reason in EDGE_REASONS for item in chosen)
      selected.extend(chosen)

    if selected:
      self.stats.update_selected(selected)
      self.writer.write((frame.to_record() for frame in selected), message_mono_ns, wall_time_ns, flush=edge_seen)
    return edge_seen
