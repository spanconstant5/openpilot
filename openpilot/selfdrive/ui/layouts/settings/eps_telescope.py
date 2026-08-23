import html
import time

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.html_render import HtmlModal
from openpilot.system.ui.widgets.list_view import button_item, multiple_button_item, text_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.tools.eps_telescope.runner import MODE_DEEP, MODE_SECURITY, MODE_UDS
from openpilot.tools.eps_telescope.safety import vehicle_is_safe_for_probe


MODE_ORDER = (MODE_UDS, MODE_SECURITY, MODE_DEEP)
MODE_LABELS = ("UDS", "SECURITY", "DEEP")
RESULT_LABELS = {
  "uds_scan_complete": "UDS scan complete",
  "security_access_passed": "Security Access passed",
  "security_access_blocked": "Security Access blocked",
  "verified_variant": "Verified firmware variant",
  "already_patched": "Firmware appears already patched",
  "egg_variant": "Different firmware variant found",
  "no_egg": "Expected firmware signature not found",
  "sa_blocked": "Security Access blocked",
  "envelope_blocked": "Deep-probe authentication blocked",
  "probe_incomplete": "Probe incomplete",
}


class EpsTelescopeLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._status: dict = {}
    self._last_summary: dict = {}
    self._requested = False
    self._last_refresh = 0.0

    mode = self._params.get("EpsTelescopeMode", return_default=True)
    selected_mode = MODE_ORDER.index(mode) if mode in MODE_ORDER else 0
    self._mode_item = multiple_button_item(
      lambda: tr("Probe Mode"),
      lambda: tr(
        "<b>UDS</b> reads the default diagnostic surface. " +
        "<b>Security</b> also checks protected access. " +
        "<b>Deep</b> enters the programming session and runs the pinned read-only RAM probe."
      ),
      [lambda label=label: tr(label) for label in MODE_LABELS],
      selected_mode,
      button_width=205,
      callback=self._on_mode_selected,
    )
    self._fingerprint_item = toggle_item(
      lambda: tr("Identify Vehicle"),
      lambda: tr("Read identification data from the Toyota ECUs and include it in the report."),
      initial_state=self._params.get_bool("EpsTelescopeFingerprintVehicle"),
      callback=lambda state: self._params.put_bool("EpsTelescopeFingerprintVehicle", state, block=True),
      enabled=lambda: not self._requested,
    )
    self._egg_item = toggle_item(
      lambda: tr("Scan Firmware Signature"),
      lambda: tr("Deep mode only. Scan flash for the known EPS firmware signature without writing flash."),
      initial_state=self._params.get_bool("EpsTelescopeScanEgg"),
      callback=lambda state: self._params.put_bool("EpsTelescopeScanEgg", state, block=True),
      enabled=lambda: not self._requested,
    )
    self._export_item = toggle_item(
      lambda: tr("Prepare PC Download"),
      lambda: tr(
        "Create a portable report bundle for the local Comma File Portal. " +
        "The bundle can contain a VIN and ECU identifiers; share it deliberately."
      ),
      initial_state=self._params.get_bool("EpsTelescopeExportEnabled"),
      callback=lambda state: self._params.put_bool("EpsTelescopeExportEnabled", state, block=True),
      enabled=lambda: not self._requested,
    )
    self._status_item = text_item(
      lambda: tr("Status"),
      self._status_text,
      lambda: tr("Normal openpilot services are restored automatically after completion, cancellation, or failure."),
    )
    self._run_item = button_item(
      lambda: tr("EPS Telescope"),
      lambda: tr("CANCEL") if self._requested else tr("RUN"),
      self._run_description,
      callback=self._on_run_or_cancel,
    )
    self._result_item = button_item(
      lambda: tr("Last Result"),
      lambda: tr("VIEW"),
      callback=self._show_last_result,
    )
    self._result_item.set_visible(False)

    self._scroller = Scroller([
      self._mode_item,
      self._fingerprint_item,
      self._egg_item,
      self._export_item,
      self._status_item,
      self._run_item,
      self._result_item,
    ], line_separator=True, spacing=0)
    self._refresh(force=True)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._refresh(force=True)

  def _render(self, rect):
    self._refresh()
    self._scroller.render(rect)

  def _refresh(self, force: bool = False):
    now = time.monotonic()
    if not force and now - self._last_refresh < 0.25:
      return
    self._last_refresh = now

    self._requested = self._params.get_bool("EpsTelescopeRequested")
    self._status = self._params.get("EpsTelescopeStatus") or {}
    self._last_summary = self._params.get("EpsTelescopeLastSummary") or {}
    mode = self._params.get("EpsTelescopeMode", return_default=True)
    if mode not in MODE_ORDER:
      mode = MODE_UDS

    self._mode_item.action_item.set_selected_button(MODE_ORDER.index(mode))
    self._mode_item.action_item.set_enabled(not self._requested)
    self._fingerprint_item.action_item.set_state(self._params.get_bool("EpsTelescopeFingerprintVehicle"))
    self._egg_item.action_item.set_state(self._params.get_bool("EpsTelescopeScanEgg"))
    self._export_item.action_item.set_state(self._params.get_bool("EpsTelescopeExportEnabled"))
    self._egg_item.set_visible(mode == MODE_DEEP)
    self._run_item.action_item.set_text(lambda: tr("CANCEL") if self._requested else tr("RUN"))
    self._result_item.set_visible(bool(self._last_summary))

  def _status_text(self):
    state = self._status.get("state", "idle")
    if state == "idle" or not self._status:
      return tr("Ready")
    progress = self._status.get("progress")
    message = self._status.get("message") or state.replace("_", " ").title()
    if state in ("preparing", "running") and isinstance(progress, (int, float)):
      return f"{round(progress * 100)}% — {message}"
    return message

  def _run_description(self):
    if self._requested:
      return tr("Cancel the current probe. The Panda and normal comma services will be restored automatically.")
    return tr(
      "Vehicle must be stationary in Park with openpilot disengaged. " +
      "The comma temporarily pauses driving services while the probe has exclusive Panda access."
    )

  def _on_mode_selected(self, index: int):
    if self._requested or not 0 <= index < len(MODE_ORDER):
      return
    self._params.put("EpsTelescopeMode", MODE_ORDER[index], block=True)
    self._refresh(force=True)

  def _on_run_or_cancel(self):
    if self._requested:
      self._params.put_bool("EpsTelescopeRequested", False, block=True)
      return

    data_valid = ui_state.sm.all_checks(["carState", "selfdriveState"])
    safe, reason = vehicle_is_safe_for_probe(
      ui_state.started,
      ui_state.sm["carState"],
      ui_state.sm["selfdriveState"],
      data_valid=data_valid,
    )
    if not safe:
      gui_app.push_widget(alert_dialog(tr(reason)))
      return

    mode = self._params.get("EpsTelescopeMode", return_default=True)
    if mode == MODE_DEEP:
      warning = tr(
        "<h1>Deep EPS Probe</h1>" +
        "<p>The vehicle must remain in Park and must not be driven or steered during this test.</p>" +
        "<p>This pauses openpilot, enters the EPS programming session, checks Security Access, " +
        "and uploads a pinned read-only probe to RAM. It does not write flash.</p>" +
        "<p>When it finishes, power the vehicle fully off and back on before driving.</p>"
      )
      confirm_text = tr("RUN DEEP")
    elif mode == MODE_SECURITY:
      warning = tr(
        "<h1>Security Access Check</h1>" +
        "<p>Keep the vehicle stationary in Park. This pauses openpilot and checks the EPS diagnostic " +
        "surface and Security Access. It does not enter the programming session or upload code.</p>"
      )
      confirm_text = tr("RUN CHECK")
    else:
      warning = tr(
        "<h1>UDS Scan</h1>" +
        "<p>Keep the vehicle stationary in Park. This pauses openpilot and reads the EPS default " +
        "diagnostic surface. It does not request Security Access, enter the programming session, or upload code.</p>"
      )
      confirm_text = tr("RUN SCAN")

    def start_probe(result: DialogResult):
      if result != DialogResult.CONFIRM:
        return
      self._params.put("EpsTelescopeStatus", {
        "state": "queued",
        "message": "Waiting for the comma manager",
        "progress": 0.0,
        "mode": mode,
      }, block=True)
      self._params.put_bool("EpsTelescopeRequested", True, block=True)
      self._refresh(force=True)

    gui_app.push_widget(ConfirmDialog(warning, confirm_text, rich=True, callback=start_probe))

  def _show_last_result(self):
    summary = self._last_summary
    if not summary:
      gui_app.push_widget(alert_dialog(tr("No EPS Telescope report is available yet.")))
      return

    outcome = summary.get("outcome", "probe_incomplete")
    title = RESULT_LABELS.get(outcome, outcome.replace("_", " ").title())
    mode = str(summary.get("mode", "")).upper()
    timestamp = html.escape(str(summary.get("timestamp") or "Unknown"))
    report_path = html.escape(str(summary.get("report") or ""))
    export_path = html.escape(str(summary.get("export") or "Not prepared"))
    power_cycle = ""
    if summary.get("power_cycle_recommended"):
      power_cycle = tr("<h2>Before Driving</h2><p>Power the vehicle fully off and back on.</p>")
    content = "".join((
      f"<h1>{html.escape(title)}</h1>",
      f"<p><b>Mode:</b> {html.escape(mode)}</p>",
      f"<p><b>Completed:</b> {timestamp}</p>",
      power_cycle,
      f"<h2>PC Download Bundle</h2><p>{export_path}</p>",
      f"<h2>Saved Report</h2><p>{report_path}</p>",
    ))
    gui_app.push_widget(HtmlModal(text=content))
