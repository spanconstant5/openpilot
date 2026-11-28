#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import iqpilot.selfdrive.pandad.pandad as pandad


class FakePanda:
  reset_count = 0
  SUPPORTED_DEVICES = {1}
  HW_TYPE_UNKNOWN = 0

  @staticmethod
  def list():
    return ["fake"]

  @staticmethod
  def wait_for_panda(serial=None, timeout=None):
    return True

  def __init__(self, *args, **kwargs):
    self.serial = args[0] if args else "fake"

  def __enter__(self):
    return self

  def __exit__(self, *args):
    return False

  bootstub = False

  def up_to_date(self):
    return True

  def health(self):
    return {"heartbeat_lost": False, "som_reset_triggered": False}

  def is_internal(self):
    return True

  def get_type(self):
    return 1

  def get_usb_serial(self):
    return self.serial

  def get_signature(self):
    return b"test-signature"

  def reset(self, reconnect=True):
    type(self).reset_count += 1

  def close(self):
    pass


class FakePandaDFU:
  @staticmethod
  def list():
    return []


class FakeHardware:
  def __init__(self):
    self.reset_count = 0
    self.recover_count = 0

  def reset_internal_panda(self):
    self.reset_count += 1

  def recover_internal_panda(self):
    self.recover_count += 1

  def has_internal_panda(self):
    return True


class FakeParams:
  def remove(self, key):
    pass

  def put(self, key, value):
    pass

  def put_bool(self, key, value):
    pass


class FakeCloudlog:
  def __getattr__(self, name):
    if name == "exception":
      def raise_current(*args, **kwargs):
        raise
      return raise_current
    return lambda *args, **kwargs: None


def _run_main_with_processes(process_factory, lease: Path, ready: Path):
  handlers = {}
  hardware = FakeHardware()

  def fake_signal(sig, handler):
    handlers[sig] = handler

  with (
    mock.patch.object(pandad, "Panda", FakePanda),
    mock.patch.object(pandad, "PandaDFU", FakePandaDFU),
    mock.patch.object(pandad, "HARDWARE", hardware),
    mock.patch.object(pandad, "Params", FakeParams),
    mock.patch.object(pandad, "cloudlog", FakeCloudlog()),
    mock.patch.object(pandad, "flash_panda", lambda serial: FakePanda(serial)),
    mock.patch.object(pandad.subprocess, "Popen", process_factory(handlers)),
    mock.patch.object(pandad.signal, "signal", fake_signal),
    mock.patch.object(pandad, "DIRECT_PANDA_LEASE_PATH", lease),
    mock.patch.object(pandad, "DIRECT_PANDA_LEASE_READY_PATH", ready),
  ):
    pandad.main()
  return hardware


class TestDirectPandaLease(unittest.TestCase):
  def test_intentional_direct_panda_lease_skips_recovery(self):
    with tempfile.TemporaryDirectory() as td:
      lease = Path(td) / "lease"
      ready = Path(td) / "ready"
      launches = []
      ready_observed = []

      def factory(handlers):
        class Process:
          def __init__(self, index):
            self.index = index
            self.signals = []
            self.exited = False

          def poll(self):
            return 0 if self.exited else None

          def send_signal(self, sig):
            self.signals.append(sig)
            if sig == signal.SIGINT:
              self.exited = True

          def wait(self):
            if self.index == 0:
              ident = f"{os.getpid()} direct-lease-test"
              lease.write_text(ident + "\n", encoding="utf-8")

              def release_when_ready():
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                  if ready.exists():
                    ready_observed.append(True)
                    break
                  time.sleep(0.005)
                else:
                  ready_observed.append(False)
                lease.unlink(missing_ok=True)

              threading.Thread(target=release_when_ready, daemon=True).start()
              handlers[signal.SIGWINCH](signal.SIGWINCH, None)
              self.exited = True
              return 0

            handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.exited = True
            return 0

        def popen(*args, **kwargs):
          process = Process(len(launches))
          launches.append(process)
          return process

        return popen

      hardware = _run_main_with_processes(factory, lease, ready)
      assert hardware.reset_count == 0
      assert hardware.recover_count == 0
      assert len(launches) == 2
      assert signal.SIGINT in launches[0].signals
      assert ready_observed == [True]
      assert not ready.exists()


class TestNativeOracleHandoff(unittest.TestCase):
  def test_native_oracle_handoff_waits_for_lease_without_recovery(self):
    with tempfile.TemporaryDirectory() as td:
      lease = Path(td) / "lease"
      ready = Path(td) / "ready"
      launches = []
      ready_observed = []

      def factory(handlers):
        class Process:
          def __init__(self, index):
            self.index = index
            self.exited = False

          def poll(self):
            return 0 if self.exited else None

          def send_signal(self, sig):
            self.exited = True

          def wait(self):
            if self.index == 0:
              ident = f"{os.getpid()} oracle-handoff-test"

              def request_and_release_lease():
                time.sleep(0.02)
                lease.write_text(ident + "\n", encoding="utf-8")
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                  if ready.exists():
                    ready_observed.append(True)
                    break
                  time.sleep(0.005)
                else:
                  ready_observed.append(False)
                lease.unlink(missing_ok=True)

              threading.Thread(target=request_and_release_lease, daemon=True).start()
              self.exited = True
              return pandad.TSS3_ORACLE_HANDOFF_EXIT_CODE

            handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.exited = True
            return 0

        def popen(*args, **kwargs):
          process = Process(len(launches))
          launches.append(process)
          return process

        return popen

      hardware = _run_main_with_processes(factory, lease, ready)
      assert hardware.reset_count == 0
      assert hardware.recover_count == 0
      assert len(launches) == 2
      assert ready_observed == [True]
      assert not ready.exists()


class TestUnrequestedPandadExit(unittest.TestCase):
  def test_unrequested_native_pandad_exit_keeps_recovery_path(self):
    with tempfile.TemporaryDirectory() as td:
      lease = Path(td) / "lease"
      ready = Path(td) / "ready"
      launches = []

      def factory(handlers):
        class Process:
          def __init__(self, index):
            self.index = index
            self.exited = False

          def poll(self):
            return 0 if self.exited else None

          def send_signal(self, sig):
            self.exited = True

          def wait(self):
            if self.index == 0:
              self.exited = True
              return 1
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.exited = True
            return 0

        def popen(*args, **kwargs):
          process = Process(len(launches))
          launches.append(process)
          return process

        return popen

      hardware = _run_main_with_processes(factory, lease, ready)
      assert hardware.reset_count == 0
      assert hardware.recover_count == 0
      assert len(launches) == 2


if __name__ == "__main__":
  unittest.main()
