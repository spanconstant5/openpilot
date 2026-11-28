from iqpilot.common.params import Params
from iqpilot.selfdrive.car.toyota_tss3_oracle_kit import oracle_ui_state
from iqpilot.selfdrive.ui.layouts.settings.tss3_oracle import Tss3OracleBringupDialog
from iqpilot.selfdrive.ui.tss3_oracle_runner import tool_available
from iqpilot.selfdrive.ui.widgets.ssh_key import ssh_key_item
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.hardware.tici.usb_storage import apply_usb_storage_state
from iqpilot.system.ui.widgets import Widget
from iqpilot.system.ui.widgets.list_view import button_item, toggle_item
from iqpilot.system.ui.widgets.scroller_tici import Scroller
from iqpilot.system.ui.lib.application import gui_app
from iqpilot.system.ui.lib.multilang import tr, tr_noop

if gui_app.iqpilot_ui():
  from iqpilot.system.ui.iqwidgets.widgets.list_view import toggle_item

# Description constants
DESCRIPTIONS = {
  'enable_adb': tr_noop(
    "ADB (Android Debug Bridge) allows connecting to your device over USB or over the network."
  ),
  'ssh_key': tr_noop(
    "Warning: This grants SSH access to all public keys in your GitHub settings. Never enter a GitHub username " +
    "other than your own. An IQ.Pilot employee will NEVER ask you to add their GitHub username."
  ),
  'usb_storage': tr_noop(
    "Exposes a snapshot of recent dashcam clips and logs as a USB drive when connected to a computer. " +
    "IQ.Pilot keeps running while this is enabled."
  ),
  'long_maneuver': tr_noop(
    "Commands a scripted sequence of acceleration steps to measure longitudinal actuator response. " +
    "Requires IQ.Pilot longitudinal control. Only use on a clear, closed road."
  ),
  'lat_maneuver': tr_noop(
    "Commands a scripted sequence of lateral acceleration steps to measure steering actuator response. " +
    "Only use on a straight, flat, clear road."
  ),
  'tss3_oracle': tr_noop(
    "Install and verify the volatile TSS3 steering signer. Use only while parked and offroad; this does not flash the EPS."
  ),
}


class DeveloperLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = self._params.get_bool("IsReleaseBranch")

    # Build items and keep references for callbacks/state updates
    self._adb_toggle = toggle_item(
      lambda: tr("Enable ADB"),
      description=lambda: tr(DESCRIPTIONS["enable_adb"]),
      initial_state=self._params.get_bool("AdbEnabled"),
      callback=self._on_enable_adb,
      enabled=ui_state.is_offroad,
    )

    self._usb_storage_toggle = toggle_item(
      lambda: tr("USB Storage"),
      description=lambda: tr(DESCRIPTIONS["usb_storage"]),
      initial_state=self._params.get_bool("UsbStorageEnabled"),
      callback=self._on_enable_usb_storage,
      enabled=ui_state.is_offroad,
    )

    # SSH enable toggle + SSH key management
    self._ssh_toggle = toggle_item(
      lambda: tr("Enable SSH"),
      description="",
      initial_state=self._params.get_bool("SshEnabled"),
      callback=self._on_enable_ssh,
    )
    self._ssh_keys = ssh_key_item(lambda: tr("SSH Keys"), description=lambda: tr(DESCRIPTIONS["ssh_key"]))

    self._long_maneuver_toggle = toggle_item(
      lambda: tr("Longitudinal Maneuver Mode"),
      description=lambda: tr(DESCRIPTIONS["long_maneuver"]),
      initial_state=self._params.get_bool("LongitudinalManeuverMode"),
      callback=self._on_long_maneuver_mode,
    )

    self._lat_maneuver_toggle = toggle_item(
      lambda: tr("Lateral Maneuver Mode"),
      description=lambda: tr(DESCRIPTIONS["lat_maneuver"]),
      initial_state=self._params.get_bool("LateralManeuverMode"),
      callback=self._on_lat_maneuver_mode,
    )

    self._tss3_oracle_auto_toggle = toggle_item(
      lambda: tr("Auto-arm TSS3 Oracle"),
      description=lambda: tr("Automatically prepare the RAM-only signer at vehicle startup."),
      initial_state=self._params.get_bool("Tss3OracleAutoArm"),
      callback=lambda state: self._params.put_bool("Tss3OracleAutoArm", state),
      enabled=lambda: ui_state.is_offroad() and not ui_state.engaged and tool_available(),
    )
    self._tss3_oracle_button = button_item(
      lambda: tr("TSS3 Oracle Bringup"),
      lambda: tr(oracle_ui_state(
        ui_state.CP.carFingerprint if ui_state.CP is not None else None,
        is_release=self._is_release,
        tool_available=tool_available(),
      )[2]),
      lambda: tr(DESCRIPTIONS["tss3_oracle"]),
      callback=self._on_tss3_oracle_bringup,
      enabled=lambda: ui_state.is_offroad() and not ui_state.engaged,
    )

    self._on_enable_ui_debug(self._params.get_bool("ShowDebugInfo"))

    self._scroller = Scroller([
      self._adb_toggle,
      self._usb_storage_toggle,
      self._ssh_toggle,
      self._ssh_keys,
      self._long_maneuver_toggle,
      self._lat_maneuver_toggle,
      self._tss3_oracle_auto_toggle,
      self._tss3_oracle_button,
    ], line_separator=True, spacing=0)

    # Toggles should be not available to change in onroad state
    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    for item in (self._long_maneuver_toggle, self._lat_maneuver_toggle):
      item.set_visible(not self._is_release)

    if ui_state.CP is not None:
      self._long_maneuver_toggle.action_item.set_enabled(ui_state.has_longitudinal_control and ui_state.is_offroad())
      self._lat_maneuver_toggle.action_item.set_enabled(ui_state.is_offroad())
    else:
      self._long_maneuver_toggle.action_item.set_enabled(False)
      self._lat_maneuver_toggle.action_item.set_enabled(False)

    fingerprint = ui_state.CP.carFingerprint if ui_state.CP is not None else None
    oracle_visible, tss3, _ = oracle_ui_state(
      fingerprint, is_release=self._is_release, tool_available=tool_available(),
    )
    self._tss3_oracle_auto_toggle.set_visible(oracle_visible)
    self._tss3_oracle_button.set_visible(oracle_visible)
    self._tss3_oracle_button.action_item.set_enabled(
      lambda: tss3 and ui_state.is_offroad() and not ui_state.engaged
    )

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for key, item in (
      ("AdbEnabled", self._adb_toggle),
      ("UsbStorageEnabled", self._usb_storage_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("LateralManeuverMode", self._lat_maneuver_toggle),
      ("Tss3OracleAutoArm", self._tss3_oracle_auto_toggle),
    ):
      item.action_item.set_state(self._params.get_bool(key))

  def _on_tss3_oracle_bringup(self):
    if ui_state.is_offroad():
      gui_app.push_widget(Tss3OracleBringupDialog())

  def _on_enable_ui_debug(self, state: bool):
    self._params.put_bool("ShowDebugInfo", state)
    gui_app.set_show_touches(state)
    gui_app.set_show_fps(state)
    gui_app.set_show_mouse_coords(state)

  def _on_enable_adb(self, state: bool):
    self._params.put_bool("AdbEnabled", state)

  def _on_enable_usb_storage(self, state: bool):
    apply_usb_storage_state(state)

  def _on_enable_ssh(self, state: bool):
    self._params.put_bool("SshEnabled", state)

  def _on_long_maneuver_mode(self, state: bool):
    self._params.put_bool("LongitudinalManeuverMode", state)
    self._params.put_bool("JoystickDebugMode", False)
    self._params.put_bool("LateralManeuverMode", False)
    self._lat_maneuver_toggle.action_item.set_state(False)

  def _on_lat_maneuver_mode(self, state: bool):
    self._params.put_bool("LateralManeuverMode", state)
    self._params.put_bool("JoystickDebugMode", False)
    self._params.put_bool("ExperimentalMode", False)
    self._params.put_bool("LongitudinalManeuverMode", False)
    self._long_maneuver_toggle.action_item.set_state(False)
