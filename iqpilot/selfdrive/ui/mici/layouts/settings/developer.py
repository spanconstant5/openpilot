"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

from iqpilot.common.time_helpers import system_time_valid
from iqpilot.system.hardware.tici.usb_storage import apply_usb_storage_state
from iqpilot.system.ui.widgets.scroller import NavScroller
from iqpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigToggle, BigCircleParamControl, BigParamControl
from iqpilot.selfdrive.ui.mici.widgets.stock_dialog import BigDialog, BigInputDialog
from iqpilot.system.ui.lib.application import gui_app
from iqpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.selfdrive.ui.widgets.ssh_key import SshKeyFetcher
from iqpilot.selfdrive.car.toyota_tss3_oracle_kit import oracle_ui_state
from iqpilot.selfdrive.ui.mici.layouts.settings.tss3_oracle import Tss3OracleBringupPage
from iqpilot.selfdrive.ui.tss3_oracle_runner import tool_available
from iqpilot.system.ui.lib.multilang import tr


class DeveloperLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._ssh_fetcher = SshKeyFetcher(ui_state.params)

    def github_username_callback(username: str):
      if username:
        self._ssh_keys_btn.set_value(tr("Loading..."))
        self._ssh_keys_btn.set_enabled(False)

        def on_response(error):
          self._ssh_keys_btn.set_enabled(True)
          if error is None:
            self._ssh_keys_btn.set_value(username)
          else:
            self._ssh_keys_btn.set_value(tr("Not set"))
            gui_app.push_widget(BigDialog("", error))

        self._ssh_fetcher.fetch(username, on_response)
      else:
        self._ssh_fetcher.clear()
        self._ssh_keys_btn.set_value(tr("Not set"))

    def ssh_keys_callback():
      github_username = ui_state.params.get("GithubUsername") or ""
      dlg = BigInputDialog(tr("enter GitHub username..."), github_username, minimum_length=0, confirm_callback=github_username_callback)
      if not system_time_valid():
        dlg = BigDialog("", tr("Please connect to Wi-Fi to fetch your key."))
        gui_app.push_widget(dlg)
        return
      gui_app.push_widget(dlg)

    txt_ssh = gui_app.texture("icons_mici/settings/developer/ssh.png", 56, 64)
    github_username = ui_state.params.get("GithubUsername") or ""
    self._ssh_keys_btn = BigButton(tr("SSH keys"), tr("Not set") if not github_username else github_username, icon=txt_ssh)
    self._ssh_keys_btn.set_click_callback(ssh_keys_callback)

    self._adb_toggle = BigCircleParamControl(gui_app.texture("icons_mici/adb_short.png", 82, 82), "AdbEnabled", icon_offset=(0, 12))
    self._usb_storage_toggle = BigParamControl(tr("USB Storage"), "UsbStorageEnabled",
                                               toggle_callback=apply_usb_storage_state)
    self._ssh_toggle = BigCircleParamControl(gui_app.texture("icons_mici/ssh_short.png", 82, 82), "SshEnabled", icon_offset=(0, 12))
    self._long_maneuver_toggle = BigToggle(tr("longitudinal maneuver mode"),
                                           initial_state=ui_state.params.get_bool("LongitudinalManeuverMode"),
                                           toggle_callback=self._on_long_maneuver_mode)
    self._lat_maneuver_toggle = BigToggle(tr("lateral maneuver mode"),
                                          initial_state=ui_state.params.get_bool("LateralManeuverMode"),
                                          toggle_callback=self._on_lat_maneuver_mode)
    self._tss3_oracle_auto_toggle = BigParamControl(
      tr("auto-arm TSS3 oracle"), "Tss3OracleAutoArm",
      description=tr("Automatically prepare the RAM-only TSS3 signer at vehicle startup."),
    )
    self._tss3_oracle_button = BigButton(
      tr("TSS3 oracle bringup"), tr("ARM"),
      description=tr("Install and verify the volatile TSS3 steering signer while parked. This does not flash the EPS."),
    )
    self._tss3_oracle_button.set_click_callback(self._on_tss3_oracle_bringup)

    self._scroller.add_widgets([
      self._adb_toggle,
      self._usb_storage_toggle,
      self._ssh_toggle,
      self._ssh_keys_btn,
      self._long_maneuver_toggle,
      self._lat_maneuver_toggle,
      self._tss3_oracle_auto_toggle,
      self._tss3_oracle_button,
    ])

    self._refresh_toggles = (
      ("AdbEnabled", self._adb_toggle),
      ("UsbStorageEnabled", self._usb_storage_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("LateralManeuverMode", self._lat_maneuver_toggle),
      ("Tss3OracleAutoArm", self._tss3_oracle_auto_toggle),
    )
    onroad_blocked_toggles = (self._adb_toggle, self._usb_storage_toggle)
    release_blocked_toggles = (self._long_maneuver_toggle, self._lat_maneuver_toggle)
    engaged_blocked_toggles = (self._long_maneuver_toggle, self._lat_maneuver_toggle)

    for item in release_blocked_toggles:
      item.set_visible(not ui_state.is_release)

    for item in onroad_blocked_toggles:
      item.set_enabled(lambda: ui_state.is_offroad())

    for item in engaged_blocked_toggles:
      item.set_enabled(lambda: not ui_state.engaged)

    self._tss3_oracle_auto_toggle.set_enabled(lambda: ui_state.is_offroad() and not ui_state.engaged and tool_available())
    self._tss3_oracle_button.set_enabled(lambda: ui_state.is_offroad() and not ui_state.engaged)

    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()
    self._ssh_fetcher.update()

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    if ui_state.CP is not None:
      long_man_enabled = ui_state.has_longitudinal_control and ui_state.is_offroad()
      self._long_maneuver_toggle.set_enabled(long_man_enabled)
      self._lat_maneuver_toggle.set_enabled(ui_state.is_offroad())
    else:
      self._long_maneuver_toggle.set_enabled(False)
      self._lat_maneuver_toggle.set_enabled(False)

    fingerprint = ui_state.CP.carFingerprint if ui_state.CP is not None else None
    oracle_visible, tss3, oracle_label = oracle_ui_state(
      fingerprint, is_release=ui_state.is_release, tool_available=tool_available(),
    )
    self._tss3_oracle_auto_toggle.set_visible(oracle_visible)
    self._tss3_oracle_button.set_visible(oracle_visible)
    self._tss3_oracle_button.set_enabled(lambda: tss3 and ui_state.is_offroad() and not ui_state.engaged)
    self._tss3_oracle_button.set_value(oracle_label)

    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))

  def _on_long_maneuver_mode(self, state: bool):
    ui_state.params.put_bool("LongitudinalManeuverMode", state)
    ui_state.params.put_bool("LateralManeuverMode", False)
    self._lat_maneuver_toggle.set_checked(False)
    restart_needed_callback()

  def _on_tss3_oracle_bringup(self):
    if ui_state.is_offroad():
      gui_app.push_widget(Tss3OracleBringupPage())

  def _on_lat_maneuver_mode(self, state: bool):
    ui_state.params.put_bool("LateralManeuverMode", state)
    ui_state.params.put_bool("ExperimentalMode", False)
    ui_state.params.put_bool("LongitudinalManeuverMode", False)
    self._long_maneuver_toggle.set_checked(False)
    restart_needed_callback()
