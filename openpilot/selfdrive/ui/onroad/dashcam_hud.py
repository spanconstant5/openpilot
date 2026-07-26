from __future__ import annotations

import math
import time
from datetime import datetime

import pyray as rl

from openpilot.common.constants import CV
from openpilot.selfdrive.ui.onroad.dashcam_provider import (ControlBarState, GenericSignalProvider, HybridState,
                                                           VehicleSignalProvider, signal_provider_for_brand)
from openpilot.selfdrive.ui.ui_state import UIStatus, ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


GREEN = rl.Color(112, 207, 78, 255)
BLUE = rl.Color(31, 137, 229, 255)
ORANGE = rl.Color(255, 145, 35, 255)
RED = rl.Color(231, 65, 65, 255)
WHITE = rl.Color(255, 255, 255, 245)
MUTED = rl.Color(220, 224, 228, 205)
PANEL = rl.Color(7, 10, 13, 185)
BORDER = rl.Color(255, 255, 255, 58)
EMPTY = rl.Color(30, 34, 38, 220)


def _centered_text(font: rl.Font, text: str, center_x: float, y: float, size: int, color: rl.Color) -> None:
  width = measure_text_cached(font, text, size).x
  rl.draw_text_ex(font, text, rl.Vector2(center_x - width / 2, y), size, 0, color)


def _panel(rect: rl.Rectangle, radius: float = 0.12) -> None:
  rl.draw_rectangle_rounded(rect, radius, 8, PANEL)
  rl.draw_rectangle_rounded_lines_ex(rect, radius, 8, 2, BORDER)


class DashcamHudLayer(Widget):
  """Read-only dashcam overlay shared by the big and comma four UIs."""

  def __init__(self, compact: bool = False, vehicle_provider: VehicleSignalProvider | None = None):
    super().__init__()
    self.compact = compact
    self.provider = vehicle_provider or GenericSignalProvider()
    self._provider_is_explicit = vehicle_provider is not None
    self._provider_brand: str | None = None
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self.speed = 0.0
    self.steering_angle = 0.0
    self.steering_pressed = False
    self.throttle = ControlBarState(0.0, False, False)
    self.brake = ControlBarState(0.0, False, False)
    self.rpm: float | None = None
    self.hybrid: HybridState | None = None
    self.assist_state = "STANDBY"
    self.assist_color = MUTED
    self.driver_override = False
    self.driver_status: str | None = None
    self.driver_color = MUTED
    self.gps_text: str | None = None
    self.clock_text = ""
    self.date_text = ""
    self.duration_text = "00:00:00"
    self._clock_second = -1
    self._v_ego_cluster_seen = False

  def _update_state(self) -> None:
    sm = ui_state.sm
    brand = str(ui_state.CP.brand) if ui_state.CP is not None else None
    if not self._provider_is_explicit and brand != self._provider_brand:
      self.provider = signal_provider_for_brand(brand)
      self._provider_brand = brand
    if sm.recv_frame["carState"] >= ui_state.started_frame:
      car_state = sm["carState"]
      v_cluster = float(car_state.vEgoCluster)
      self._v_ego_cluster_seen = self._v_ego_cluster_seen or v_cluster != 0.0
      v_ego = v_cluster if self._v_ego_cluster_seen else float(car_state.vEgo)
      self.speed = max(0.0, v_ego * (CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH))
      self.steering_angle = float(car_state.steeringAngleDeg)
      self.steering_pressed = bool(car_state.steeringPressed)
      self.driver_override = bool(car_state.steeringPressed or car_state.gasPressed or car_state.brakePressed)
      self.throttle, self.brake = self.provider.throttle_brake_states(car_state)
      self.rpm = self.provider.engine_rpm(car_state)
      self.hybrid = self.provider.hybrid_state(car_state)
      stock_state = self.provider.stock_assistance_state(car_state)
    else:
      stock_state = None

    if stock_state:
      self.assist_state = stock_state.upper()
      self.assist_color = GREEN if "ACTIVE" in self.assist_state or "AEB" in self.assist_state else MUTED
    elif ui_state.status == UIStatus.ENGAGED:
      self.assist_state = "ENGAGED"
      self.assist_color = GREEN
    elif ui_state.status == UIStatus.OVERRIDE:
      self.assist_state = "DRIVER OVERRIDE"
      self.assist_color = ORANGE
    elif sm["selfdriveState"].engageable:
      self.assist_state = "READY"
      self.assist_color = MUTED
    else:
      self.assist_state = "STANDBY"
      self.assist_color = MUTED

    if sm.recv_frame["driverMonitoringState"] >= ui_state.started_frame:
      vision = sm["driverMonitoringState"].visionPolicyState
      if vision.isDistracted:
        self.driver_status, self.driver_color = "DISTRACTED", ORANGE
      elif vision.faceDetected:
        self.driver_status, self.driver_color = "ATTENTIVE", GREEN
      else:
        self.driver_status, self.driver_color = "FACE NOT FOUND", MUTED

    gps = sm["gpsLocationExternal"]
    self.gps_text = f"{gps.latitude:.5f}, {gps.longitude:.5f}" if gps.hasFix else None

    current_second = int(time.monotonic())
    if current_second != self._clock_second:
      self._clock_second = current_second
      now = datetime.now().astimezone()
      self.clock_text = now.strftime("%I:%M:%S %p").lstrip("0")
      self.date_text = now.strftime("%b %d, %Y")
      elapsed = max(0, int(time.monotonic() - ui_state.started_time))
      self.duration_text = f"{elapsed // 3600:02d}:{(elapsed // 60) % 60:02d}:{elapsed % 60:02d}"

  def _render(self, rect: rl.Rectangle) -> None:
    if self.compact:
      self._render_compact(rect)
    else:
      self._render_big(rect)

  def _render_big(self, rect: rl.Rectangle) -> None:
    footer_y = rect.y + rect.height - 74
    rl.draw_rectangle_gradient_v(int(rect.x), int(footer_y - 280), int(rect.width), 354, rl.BLANK, rl.Color(0, 0, 0, 205))
    self._draw_speed(rect.x + rect.width / 2, footer_y - 222, 126, 38)
    self._draw_throttle_brake(rect.x + 35, footer_y - 126, 390, 36, 10)
    self._draw_steering(rect.x + rect.width - 650, footer_y - 126, 585, 10)
    self._draw_assist_big(rect)
    self._draw_driver_status_big(rect)
    self._draw_footer_big(rect, footer_y)

  def _draw_speed(self, center_x: float, top: float, speed_size: int, unit_size: int) -> None:
    _centered_text(self._font_bold, str(round(self.speed)), center_x, top, speed_size, WHITE)
    unit = "km/h" if ui_state.is_metric else "mph"
    _centered_text(self._font_medium, unit, center_x, top + speed_size - 3, unit_size, MUTED)

  def _draw_throttle_brake(self, x: float, y: float, width: float, row_height: float, segments: int) -> None:
    label_width = 92 if not self.compact else 30
    value_width = 58 if not self.compact else 0
    bar_x = x + label_width
    bar_width = width - label_width - value_width
    self._draw_control_row("Throttle", self.throttle, GREEN, x, y, bar_x, bar_width, row_height, segments)
    self._draw_control_row("Brake", self.brake, RED, x, y + row_height + (8 if not self.compact else 2),
                           bar_x, bar_width, row_height, segments)

  def _draw_control_row(self, label: str, state: ControlBarState, color: rl.Color, label_x: float, y: float,
                        bar_x: float, bar_width: float, height: float, segments: int) -> None:
    font_size = 25 if not self.compact else 6
    rl.draw_text_ex(self._font_medium, label, rl.Vector2(label_x, y + 2), font_size, 0, WHITE)
    gap = 5 if not self.compact else 1
    segment_width = (bar_width - gap * (segments - 1)) / segments
    filled = math.ceil(max(0.0, min(1.0, state.value)) * segments)
    for index in range(segments):
      cell = rl.Rectangle(bar_x + index * (segment_width + gap), y, segment_width, height)
      active_color = ORANGE if state.driver_override else color
      rl.draw_rectangle_rounded(cell, 0.14, 4, active_color if index < filled else EMPTY)
      rl.draw_rectangle_rounded_lines_ex(cell, 0.14, 4, 1, BORDER)
    if not self.compact:
      value = f"{round(state.value * 100):d}%" if state.analog else ("ON" if state.value > 0 else "OFF")
      rl.draw_text_ex(self._font_medium, value, rl.Vector2(bar_x + bar_width + 12, y + 2), 25, 0, WHITE)
      if state.driver_override:
        rl.draw_text_ex(self._font_bold, "! DRIVER", rl.Vector2(bar_x + bar_width + 70, y + 7), 16, 0, ORANGE)
      elif state.source_label:
        rl.draw_text_ex(self._font_bold, state.source_label, rl.Vector2(bar_x + bar_width + 70, y + 7), 16, 0, color)

  def _draw_steering(self, x: float, y: float, width: float, tick_count: int) -> None:
    label_size = 25 if not self.compact else 8
    line_y = y + (42 if not self.compact else 9)
    if not self.compact:
      _centered_text(self._font_medium, "Steering Angle", x + width / 2, y, label_size, WHITE)
    rl.draw_line_ex(rl.Vector2(x, line_y), rl.Vector2(x + width, line_y), 2 if not self.compact else 1, MUTED)
    for index in range(tick_count + 1):
      tick_x = x + width * index / tick_count
      tick_height = 15 if index in (0, tick_count // 2, tick_count) else 8
      rl.draw_line_ex(rl.Vector2(tick_x, line_y - tick_height / 2), rl.Vector2(tick_x, line_y + tick_height / 2), 2, MUTED)
    clamped = max(-45.0, min(45.0, self.steering_angle))
    marker_x = x + (clamped + 45.0) / 90.0 * width
    marker_color = ORANGE if self.steering_pressed else BLUE
    rl.draw_line_ex(rl.Vector2(marker_x, line_y - (17 if not self.compact else 6)),
                    rl.Vector2(marker_x, line_y + (17 if not self.compact else 6)), 6 if not self.compact else 2, marker_color)
    if not self.compact:
      rl.draw_text_ex(self._font_regular, "-45°", rl.Vector2(x - 4, line_y + 15), 20, 0, MUTED)
      _centered_text(self._font_bold, f"{round(self.steering_angle):d}°", x + width / 2, line_y + 12, 27, WHITE)
      rl.draw_text_ex(self._font_regular, "45°", rl.Vector2(x + width - 38, line_y + 15), 20, 0, MUTED)

  def _draw_assist_big(self, rect: rl.Rectangle) -> None:
    box = rl.Rectangle(rect.x + rect.width - 530, rect.y + 38, 260, 112)
    _panel(box)
    rl.draw_text_ex(self._font_bold, "ASSIST", rl.Vector2(box.x + 22, box.y + 15), 30, 0, WHITE)
    rl.draw_text_ex(self._font_medium, self.assist_state, rl.Vector2(box.x + 22, box.y + 57), 28, 0, self.assist_color)
    if self.driver_override:
      rl.draw_text_ex(self._font_bold, "! DRIVER OVERRIDE", rl.Vector2(box.x + box.width + 12, box.y + 65), 16, 0, ORANGE)
    if self.rpm is not None:
      rl.draw_text_ex(self._font_medium, f"{round(self.rpm):d} rpm", rl.Vector2(box.x + 22, box.y + box.height + 16), 26, 0, WHITE)
    if self.hybrid is not None:
      self._draw_hybrid_big(rl.Rectangle(box.x - 90, box.y + box.height + 62, 350, 170), self.hybrid)

  def _draw_hybrid_big(self, box: rl.Rectangle, hybrid: HybridState) -> None:
    _panel(box)
    rl.draw_text_ex(self._font_bold, "Hybrid System", rl.Vector2(box.x + 20, box.y + 16), 27, 0, WHITE)
    y = box.y + 58
    if hybrid.battery_percent is not None:
      rl.draw_text_ex(self._font_medium, f"Battery  {hybrid.battery_percent:.0f}%", rl.Vector2(box.x + 20, y), 24, 0, WHITE)
      y += 34
    if hybrid.power_kw is not None:
      rl.draw_text_ex(self._font_medium, f"Power  {hybrid.power_kw:.1f} kW", rl.Vector2(box.x + 20, y), 24, 0, WHITE)
      y += 34
    if hybrid.ev_mode is not None:
      rl.draw_text_ex(self._font_medium, f"EV mode  {'ON' if hybrid.ev_mode else 'OFF'}", rl.Vector2(box.x + 20, y), 24, 0,
                      GREEN if hybrid.ev_mode else MUTED)

  def _draw_driver_status_big(self, rect: rl.Rectangle) -> None:
    if self.driver_status is None:
      return
    box = rl.Rectangle(rect.x + 34, rect.y + rect.height * 0.58, 250, 66)
    _panel(box)
    rl.draw_circle(int(box.x + 28), int(box.y + box.height / 2), 7, self.driver_color)
    rl.draw_text_ex(self._font_medium, self.driver_status, rl.Vector2(box.x + 48, box.y + 19), 25, 0, self.driver_color)

  def _draw_footer_big(self, rect: rl.Rectangle, footer_y: float) -> None:
    footer = rl.Rectangle(rect.x + 18, footer_y, rect.width - 36, 58)
    _panel(footer, 0.25)
    rl.draw_text_ex(self._font_medium, self.clock_text, rl.Vector2(footer.x + 32, footer.y + 16), 24, 0, MUTED)
    rl.draw_text_ex(self._font_medium, self.date_text, rl.Vector2(footer.x + footer.width * 0.31, footer.y + 16), 24, 0, MUTED)
    rl.draw_text_ex(self._font_medium, self.duration_text, rl.Vector2(footer.x + footer.width * 0.57, footer.y + 16), 24, 0, MUTED)
    gps = self.gps_text or "GPS unavailable"
    size = measure_text_cached(self._font_medium, gps, 22)
    rl.draw_text_ex(self._font_medium, gps, rl.Vector2(footer.x + footer.width - size.x - 30, footer.y + 17), 22, 0,
                    GREEN if self.gps_text else MUTED)

  def _render_compact(self, rect: rl.Rectangle) -> None:
    footer_y = rect.y + rect.height - 16
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y + rect.height - 76), int(rect.width), 76, rl.BLANK, rl.Color(0, 0, 0, 210))
    self._draw_speed(rect.x + rect.width / 2, rect.y + 86, 48, 12)
    self._draw_throttle_brake(rect.x + 5, rect.y + 132, 91, 5, 5)
    self._draw_steering(rect.x + rect.width - 92, rect.y + 132, 84, 6)

    status = "OVERRIDE" if ui_state.status == UIStatus.OVERRIDE else self.assist_state
    status_color = ORANGE if ui_state.status == UIStatus.OVERRIDE else self.assist_color
    size = measure_text_cached(self._font_bold, status, 11)
    rl.draw_text_ex(self._font_bold, status, rl.Vector2(rect.x + rect.width - size.x - 5, rect.y + 5), 11, 0, status_color)
    if self.driver_override:
      rl.draw_text_ex(self._font_bold, "! DRIVER", rl.Vector2(rect.x + rect.width - 44, rect.y + 18), 7, 0, ORANGE)
    if self.rpm is not None:
      rpm = f"{round(self.rpm):d} rpm"
      rpm_size = measure_text_cached(self._font_medium, rpm, 10)
      rl.draw_text_ex(self._font_medium, rpm, rl.Vector2(rect.x + rect.width - rpm_size.x - 5, rect.y + 22), 10, 0, WHITE)

    rl.draw_rectangle(int(rect.x), int(footer_y), int(rect.width), 16, rl.Color(0, 0, 0, 220))
    compact_date = datetime.now().strftime("%m/%d")
    rl.draw_text_ex(self._font_regular, f"{compact_date} {self.clock_text}", rl.Vector2(rect.x + 4, footer_y + 3), 9, 0, MUTED)
    _centered_text(self._font_regular, self.duration_text, rect.x + rect.width / 2, footer_y + 3, 9, MUTED)
    gps_color = GREEN if self.gps_text else MUTED
    rl.draw_circle(int(rect.x + rect.width - 8), int(footer_y + 8), 3, gps_color)
