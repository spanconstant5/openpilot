#!/usr/bin/env python3
"""Automatic receive-only recorder managed by openpilot's process manager."""

from __future__ import annotations

import os
import signal
import time
from types import FrameType

from openpilot.cereal.messaging import recv_one, sub_sock
from openpilot.common.swaglog import cloudlog

from .session import PassiveRecorderSession, RecorderStats
from .storage import ArchiveWriter, StatusStore, archive_size, default_log_root, utc_text


STATUS_INTERVAL_NS = 5_000_000_000
MAX_BACKOFF_SECONDS = 60.0


class RecorderDaemon:
  def __init__(self):
    self.stop_requested = False
    self.status = StatusStore()
    self.last_status_ns = 0
    self.last_error: str | None = None

  def request_stop(self, _signum: int | None = None, _frame: FrameType | None = None) -> None:
    self.stop_requested = True

  def _status_value(self, state: str, now_mono_ns: int, now_wall_ns: int,
                    session: PassiveRecorderSession | None = None) -> dict[str, object]:
    stats = session.stats if session is not None else RecorderStats()
    active_path = session.writer.active_path if session is not None else None
    return {
      "schema_version": 1,
      "state": state,
      "mode": "receive_only",
      "updated_mono_ns": now_mono_ns,
      "updated_wall_time_ns": now_wall_ns,
      "updated_utc": utc_text(now_wall_ns),
      "log_root": str(default_log_root()),
      "active_file": str(active_path) if active_path is not None else None,
      "archive_bytes": archive_size(default_log_root()),
      "observed_target_frames": stats.observed_frames,
      "selected_frames": stats.selected_frames,
      "ignored_non_physical": stats.ignored_non_physical,
      "ignored_wrong_length": stats.ignored_wrong_length,
      "discovered_buses": sorted(stats.discovered_buses),
      "press_edges": stats.press_edges,
      "release_edges": stats.release_edges,
      "button_presses": dict(sorted(stats.button_presses.items())),
      "last_physical_frame_mono_ns": stats.last_physical_frame_mono_ns,
      "last_physical_frame_wall_time_ns": stats.last_physical_frame_wall_ns,
      "last_error": self.last_error,
    }

  def _write_status(self, state: str, now_mono_ns: int, now_wall_ns: int,
                    session: PassiveRecorderSession | None = None, force: bool = False) -> None:
    if not force and now_mono_ns - self.last_status_ns < STATUS_INTERVAL_NS:
      return
    try:
      self.status.write(self._status_value(state, now_mono_ns, now_wall_ns, session))
      self.last_status_ns = now_mono_ns
    except OSError:
      pass

  def _backoff(self, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not self.stop_requested and time.monotonic() < deadline:
      time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

  def run(self) -> None:
    backoff_seconds = 1.0
    while not self.stop_requested:
      writer: ArchiveWriter | None = None
      session: PassiveRecorderSession | None = None
      try:
        start_mono_ns = time.monotonic_ns()
        start_wall_ns = time.time_ns()
        writer = ArchiveWriter(start_mono_ns=start_mono_ns, start_wall_ns=start_wall_ns)
        session = PassiveRecorderSession(writer)
        can_socket = sub_sock("can", conflate=False, timeout=1000)
        self.last_error = None
        self._write_status("running", start_mono_ns, start_wall_ns, session, force=True)

        while not self.stop_requested:
          message = recv_one(can_socket)
          now_mono_ns = time.monotonic_ns()
          now_wall_ns = time.time_ns()
          edge_seen = session.process_message(message, now_mono_ns, now_wall_ns) if message is not None else False
          if message is not None:
            backoff_seconds = 1.0
          self._write_status("running", now_mono_ns, now_wall_ns, session, force=edge_seen)

      except KeyboardInterrupt:
        self.stop_requested = True
      except Exception as error:
        self.last_error = f"{type(error).__name__}: {error}"
        cloudlog.error("tss3cruiseprobed capture error; retrying")
        now_mono_ns = time.monotonic_ns()
        now_wall_ns = time.time_ns()
        try:
          self._write_status("backoff", now_mono_ns, now_wall_ns, session, force=True)
        except OSError:
          pass
      finally:
        if writer is not None:
          try:
            writer.close(time.monotonic_ns(), time.time_ns(), "shutdown" if self.stop_requested else "retry")
          except OSError:
            writer.abort()

      if not self.stop_requested and self.last_error is not None:
        self._backoff(backoff_seconds)
        backoff_seconds = min(MAX_BACKOFF_SECONDS, backoff_seconds * 2)

    now_mono_ns = time.monotonic_ns()
    now_wall_ns = time.time_ns()
    try:
      self._write_status("stopped", now_mono_ns, now_wall_ns, force=True)
    except OSError:
      pass


def main() -> None:
  os.umask(0o077)
  daemon = RecorderDaemon()
  signal.signal(signal.SIGINT, daemon.request_stop)
  signal.signal(signal.SIGTERM, daemon.request_stop)
  daemon.run()


if __name__ == "__main__":
  main()
