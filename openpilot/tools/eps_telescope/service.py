"""Manager-owned EPS Telescope worker for comma touchscreen runs."""

from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.tools.eps_telescope.export import create_export_bundle
from openpilot.tools.eps_telescope.runner import MODE_DEEP, ProbeConfig, run_probe, summarize_report
from openpilot.tools.eps_telescope.upstream import load_payload


PANDA_RELEASE_TIMEOUT = 20.0


class ProbeCancelled(Exception):
  pass


def _process_alive(argv: list[str]) -> bool:
  try:
    result = subprocess.run(argv, capture_output=True, timeout=2)
  except (FileNotFoundError, subprocess.TimeoutExpired):
    return False
  return result.returncode == 0 and bool(result.stdout.strip())


def panda_service_running() -> bool:
  return (
    _process_alive(["pgrep", "-f", r"openpilot\.selfdrive\.pandad\.pandad"])
    or _process_alive(["pidof", "pandad"])
    or _process_alive(["pidof", "boardd"])
  )


def wait_for_exclusive_panda(params: Params, timeout: float = PANDA_RELEASE_TIMEOUT) -> None:
  deadline = time.monotonic() + timeout
  while panda_service_running():
    if not params.get_bool("EpsTelescopeRequested"):
      raise ProbeCancelled("run canceled")
    if time.monotonic() >= deadline:
      raise RuntimeError("openpilot did not release the Panda; normal services will be restored")
    time.sleep(0.1)


def _put_status(params: Params, state: str, message: str, progress: float, **extra) -> None:
  status = {"state": state, "message": message, "progress": progress, **extra}
  params.put("EpsTelescopeStatus", status, block=True)


def _signal_cancel(_signum, _frame):
  raise ProbeCancelled("run canceled")


def main() -> None:
  params = Params()
  signal.signal(signal.SIGINT, _signal_cancel)
  signal.signal(signal.SIGTERM, _signal_cancel)

  mode = params.get("EpsTelescopeMode", return_default=True)
  scan_egg = params.get_bool("EpsTelescopeScanEgg")
  fingerprint_vehicle = params.get_bool("EpsTelescopeFingerprintVehicle")
  export_enabled = params.get_bool("EpsTelescopeExportEnabled")
  artifacts_dir = params.get("EpsTelescopeArtifactsDir", return_default=True)

  try:
    _put_status(params, "preparing", "Pausing normal comma services", 0.01)
    wait_for_exclusive_panda(params)

    config = ProbeConfig(
      mode=mode,
      scan_egg=scan_egg,
      fingerprint_vehicle=fingerprint_vehicle,
      artifacts_dir=artifacts_dir,
    )

    def on_progress(stage: str, message: str, progress: float) -> None:
      if not params.get_bool("EpsTelescopeRequested"):
        raise ProbeCancelled("run canceled")
      _put_status(params, "running", message, progress, stage=stage, mode=mode)

    payload = load_payload() if mode == MODE_DEEP else None
    output_dir = run_probe(config, payload=payload, progress_callback=on_progress)
    report_path = Path(output_dir) / "probe.json"
    summary = summarize_report(report_path, mode)
    if export_enabled:
      _put_status(params, "running", "Preparing the report for PC download", 0.99, stage="export", mode=mode)
      summary["export"] = str(create_export_bundle(Path(output_dir)))
    params.put("EpsTelescopeLastSummary", summary, block=True)
    params.put("EpsTelescopeLastReport", str(Path(output_dir) / "probe.md"), block=True)
    _put_status(params, "complete", "EPS Telescope finished; restoring normal comma services", 1.0,
                mode=mode, summary=summary)
  except ProbeCancelled:
    _put_status(params, "canceled", "Run canceled; restoring normal comma services", 1.0, mode=mode)
  except Exception as exc:
    cloudlog.exception("EPS Telescope run failed")
    _put_status(params, "error", str(exc), 1.0, mode=mode)
  finally:
    params.put_bool("EpsTelescopeRequested", False, block=True)


if __name__ == "__main__":
  main()
