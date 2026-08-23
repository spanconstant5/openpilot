#!/usr/bin/env python3
import datetime
import os
import signal
import sys
import time
import traceback

from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
import openpilot.system.sentry as sentry
from openpilot.common.utils import atomic_write
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.text_window import TextWindow
from openpilot.common.hardware import HARDWARE
from openpilot.system.manager.helpers import unblock_stdout, save_bootlog
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes
from openpilot.system.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.common.version import get_build_metadata
from openpilot.common.hardware.hw import Paths
from openpilot.tools.eps_telescope.safety import vehicle_is_safe_for_probe


def manager_init() -> None:
  save_bootlog()

  build_metadata = get_build_metadata()

  params = Params()
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)
  if build_metadata.release_channel:
    params.clear_all(ParamKeyFlag.DEVELOPMENT_ONLY)

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True, block=True)

  # set unset params to their default value
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None and params.get(k) is None:
      params.put(k, default_value, block=True)

  # Create folders needed for msgq
  try:
    os.mkdir(Paths.shm_path())
  except FileExistsError:
    pass
  except PermissionError:
    print(f"WARNING: failed to make {Paths.shm_path()}")

  # set params
  serial = HARDWARE.get_serial()
  params.put("Version", build_metadata.openpilot.version, block=True)
  params.put("GitCommit", build_metadata.openpilot.git_commit, block=True)
  params.put("GitCommitDate", build_metadata.openpilot.git_commit_date, block=True)
  params.put("GitBranch", build_metadata.channel, block=True)
  params.put("GitRemote", build_metadata.openpilot.git_origin, block=True)
  params.put_bool("IsTestedBranch", build_metadata.tested_channel, block=True)
  params.put_bool("IsReleaseBranch", build_metadata.release_channel, block=True)
  params.put("HardwareSerial", serial, block=True)

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog
  os.environ['GIT_ORIGIN'] = build_metadata.openpilot.git_normalized_origin # Needed for swaglog
  os.environ['GIT_BRANCH'] = build_metadata.channel # Needed for swaglog
  os.environ['GIT_COMMIT'] = build_metadata.openpilot.git_commit # Needed for swaglog

  if not build_metadata.openpilot.is_dirty:
    os.environ['CLEAN'] = '1'

  # init logging
  sentry.init(sentry.SentryProject.SELFDRIVE)
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=build_metadata.openpilot.version,
                       origin=build_metadata.openpilot.git_normalized_origin,
                       branch=build_metadata.channel,
                       commit=build_metadata.openpilot.git_commit,
                       dirty=build_metadata.openpilot.is_dirty,
                       device=HARDWARE.get_device_type())

def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")


def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: list[str] = []
  if params.get("DongleId") in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  sm = messaging.SubMaster(['deviceState', 'carParams', 'pandaStates', 'carState', 'selfdriveState'], poll='deviceState')
  pm = messaging.PubMaster(['managerState'])

  params.put_bool("IsOffroad", True, block=True)
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  started_prev = False
  ignition_prev = False
  eps_telescope_active = False

  while True:
    sm.update(1000)

    started = sm['deviceState'].started

    eps_telescope_requested = params.get_bool("EpsTelescopeRequested")
    if eps_telescope_requested and not eps_telescope_active:
      safe, reason = vehicle_is_safe_for_probe(
        started,
        sm['carState'],
        sm['selfdriveState'],
        data_valid=sm.all_checks(['carState', 'selfdriveState']),
      )
      if safe:
        eps_telescope_active = True
        cloudlog.warning("EPS Telescope requested; pausing onroad services and pandad")
      else:
        params.put("EpsTelescopeStatus", {
          "state": "blocked",
          "message": reason,
          "progress": 0.0,
        }, block=True)
        params.put_bool("EpsTelescopeRequested", False, block=True)
        eps_telescope_requested = False
    elif not eps_telescope_requested and eps_telescope_active:
      # Keep pandad stopped until the worker has actually released the Panda.
      # ensure_running sends the worker SIGINT below; restoration happens on a
      # later manager tick after the process exits.
      eps_process = managed_processes["eps_telescope"].proc
      if eps_process is None or not eps_process.is_alive():
        eps_telescope_active = False
        cloudlog.warning("EPS Telescope finished; restoring normal services")

    if started and not started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
    elif not started and started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)

    ignition = any(ps.ignitionLine or ps.ignitionCan for ps in sm['pandaStates'] if ps.pandaType != log.PandaState.PandaType.unknown)
    if ignition and not ignition_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)

    # update offroad state for services that don't subscribe to deviceState
    if started != started_prev:
      params.put_bool("IsOffroad", not started, block=True)

    started_prev = started
    ignition_prev = ignition

    effective_started = started and not eps_telescope_active
    dynamic_ignore = ignore + (["pandad"] if eps_telescope_active else [])
    ensure_running(managed_processes.values(), effective_started, params=params, CP=sm['carParams'], not_run=dynamic_ignore)

    running = ' '.join("{}{}\u001b[0m".format("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState', valid=True)
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # kick AGNOS power monitoring watchdog
    try:
      if sm.all_checks(['deviceState']):
        with atomic_write("/var/tmp/power_watchdog", "w", overwrite=True) as f:
          f.write(str(time.monotonic()))
    except Exception:
      pass

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot"):
      if params.get_bool(param):
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}", block=True)
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break


def main() -> None:
  manager_init()
  if os.getenv("PREPAREONLY") is not None:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    sentry.capture_exception()
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except KeyboardInterrupt:
    print("got CTRL-C, exiting")
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)
