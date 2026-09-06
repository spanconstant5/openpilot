"""Keep all physical CAN frames delivered by cereal, without a DBC filter."""

from collections import Counter

from .protocol import is_physical_bus


CAPTURE_METADATA = {
  "version": "discovery-v2",
  "policy": "all_physical_can_received",
  "batch_columns": ["bus", "address", "data_hex"],
  "decoding": "none; address and button mapping unconfirmed on target vehicle",
  "timestamp": "mono_time_ns from cereal event; wall_time_ns is local receive time",
}


class DiscoverySession:
  def __init__(self, writer):
    self.writer = writer
    self.batches = 0
    self.physical_frames = 0
    self.nonphysical_frames = 0
    self.invalid_batches = 0
    self.inventory: Counter[tuple[int, int, int]] = Counter()
    self.inventory_overflow_frames = 0
    self.buses: set[int] = set()
    self.last_receive_ns: int | None = None
    self.last_source_ns: int | None = None
    self.max_delivery_age_ns = 0

  def process_message(self, message, receive_mono_ns: int, wall_time_ns: int) -> None:
    source_ns = int(message.logMonoTime)
    valid = bool(message.valid)
    self.batches += 1
    self.invalid_batches += int(not valid)
    self.last_receive_ns = receive_mono_ns
    self.last_source_ns = source_ns
    self.max_delivery_age_ns = max(self.max_delivery_age_ns, max(0, receive_mono_ns - source_ns))
    frames = []
    for frame in message.can:
      bus = int(frame.src)
      if not is_physical_bus(bus):
        self.nonphysical_frames += 1
        continue
      address = int(frame.address)
      data = bytes(frame.dat)
      frames.append([bus, address, data.hex()])
      self.physical_frames += 1
      self.buses.add(bus)
      key = (bus, address, len(data))
      if key in self.inventory or len(self.inventory) < 4096:
        self.inventory[key] += 1
      else:
        self.inventory_overflow_frames += 1  # Cap statistics only; raw recording continues.
    self.writer.write([{
      "type": "can_batch",
      "mono_time_ns": source_ns,
      "received_mono_ns": receive_mono_ns,
      "wall_time_ns": wall_time_ns,
      "source_valid": valid,
      "frames": frames,
    }], receive_mono_ns, wall_time_ns)

  def snapshot(self) -> dict[str, object]:
    return {
      "capture_version": "discovery-v2",
      "batches_received": self.batches,
      "physical_frames": self.physical_frames,
      "ignored_non_physical": self.nonphysical_frames,
      "invalid_batches": self.invalid_batches,
      "discovered_buses": sorted(self.buses),
      "last_receive_mono_ns": self.last_receive_ns,
      "last_source_mono_ns": self.last_source_ns,
      "max_delivery_age_ms": self.max_delivery_age_ns / 1_000_000,
      "inventory": [
        {"bus": bus, "address_hex": f"0x{address:X}", "length": length, "frames": count}
        for (bus, address, length), count in sorted(self.inventory.items())
      ],
      "inventory_overflow_frames": self.inventory_overflow_frames,
    }
