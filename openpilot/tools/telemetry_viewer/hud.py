from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from openpilot.tools.telemetry_viewer.model import ModelPath


WHITE = QColor(255, 255, 255, 245)
MUTED = QColor(211, 216, 221, 210)
GREEN = QColor(112, 207, 78)
BLUE = QColor(31, 137, 229)
ORANGE = QColor(255, 145, 35)
RED = QColor(231, 65, 65)
EMPTY = QColor(30, 34, 38, 220)
PANEL = QColor(7, 10, 13, 190)


class HudOverlay(QWidget):
  """Transparent replay overlay mirroring the on-device dashcam HUD."""

  def __init__(self, parent: QWidget | None = None):
    super().__init__(parent)
    self.sample: dict[str, Any] = {}
    self.vehicle_brand: str | None = None
    self.elapsed_seconds = 0.0
    self.model_path: ModelPath | None = None
    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

  def set_sample(self, sample: dict[str, Any] | None, elapsed_seconds: float,
                 model_path: ModelPath | None = None) -> None:
    self.sample = sample or {}
    self.elapsed_seconds = elapsed_seconds
    self.model_path = model_path
    self.update()

  @staticmethod
  def _font(size: float, bold: bool = False) -> QFont:
    font = QFont("Inter")
    font.setPixelSize(max(8, round(size)))
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Medium)
    return font

  @staticmethod
  def _value(sample: dict[str, Any], key: str) -> float | None:
    value = sample.get(key)
    return float(value) if value is not None else None

  @staticmethod
  def _panel(painter: QPainter, rect: QRectF, radius: float = 14.0) -> None:
    painter.setPen(QPen(QColor(255, 255, 255, 58), 1.0))
    painter.setBrush(PANEL)
    painter.drawRoundedRect(rect, radius, radius)

  def _draw_control(self, painter: QPainter, label: str, y: float, value: float | None,
                    driver_override: bool, color: QColor, scale: float, automation_label: str | None = None) -> None:
    label_width = 90 * scale
    x = 34 * scale
    painter.setFont(self._font(22 * scale))
    painter.setPen(WHITE)
    painter.drawText(QRectF(x, y, label_width, 28 * scale), Qt.AlignmentFlag.AlignVCenter, label)
    analog = value is not None
    level = max(0.0, min(1.0, value if analog else float(driver_override or automation_label is not None)))
    bar_x = x + label_width
    width = 260 * scale
    gap = 4 * scale
    segment_width = (width - gap * 9) / 10
    filled = round(level * 10 + 0.49)
    for index in range(10):
      rect = QRectF(bar_x + index * (segment_width + gap), y + 3 * scale, segment_width, 22 * scale)
      painter.setPen(QPen(QColor(255, 255, 255, 55), max(1.0, scale)))
      painter.setBrush(ORANGE if driver_override and index < filled else color if index < filled else EMPTY)
      painter.drawRoundedRect(rect, 3 * scale, 3 * scale)
    text = f"{round(level * 100)}%" if analog else ("ON" if level > 0 else "OFF")
    painter.setPen(WHITE)
    painter.drawText(QRectF(bar_x + width + 12 * scale, y, 60 * scale, 28 * scale), Qt.AlignmentFlag.AlignVCenter, text)
    if driver_override or automation_label:
      painter.setFont(self._font(12 * scale, True))
      painter.setPen(ORANGE if driver_override else color)
      notice = "! DRIVER" if driver_override else str(automation_label)
      painter.drawText(QRectF(bar_x + width + 66 * scale, y, 80 * scale, 28 * scale), Qt.AlignmentFlag.AlignVCenter, notice)

  def _draw_steering(self, painter: QPainter, width: float, height: float, scale: float) -> None:
    bar_width = 390 * scale
    x = width - bar_width - 42 * scale
    y = height - 128 * scale
    painter.setFont(self._font(21 * scale))
    painter.setPen(WHITE)
    painter.drawText(QRectF(x, y - 30 * scale, bar_width, 26 * scale), Qt.AlignmentFlag.AlignCenter, "Steering Angle")
    painter.setPen(QPen(MUTED, max(1.0, 2 * scale)))
    painter.drawLine(QPointF(x, y), QPointF(x + bar_width, y))
    for index in range(11):
      tick_x = x + index * bar_width / 10
      tick_height = (13 if index in (0, 5, 10) else 7) * scale
      painter.drawLine(QPointF(tick_x, y - tick_height / 2), QPointF(tick_x, y + tick_height / 2))
    angle = self._value(self.sample, "steering_angle_deg") or 0.0
    marker_x = x + (max(-45.0, min(45.0, angle)) + 45.0) / 90.0 * bar_width
    painter.setPen(QPen(ORANGE if self.sample.get("steering_pressed") else BLUE, max(3.0, 5 * scale)))
    painter.drawLine(QPointF(marker_x, y - 14 * scale), QPointF(marker_x, y + 14 * scale))
    painter.setFont(self._font(18 * scale))
    painter.setPen(MUTED)
    painter.drawText(QRectF(x - 8 * scale, y + 8 * scale, 60 * scale, 24 * scale), "-45°")
    painter.drawText(QRectF(x + bar_width - 35 * scale, y + 8 * scale, 50 * scale, 24 * scale), "45°")
    painter.setFont(self._font(23 * scale, True))
    painter.setPen(WHITE)
    painter.drawText(QRectF(x, y + 8 * scale, bar_width, 28 * scale), Qt.AlignmentFlag.AlignCenter, f"{round(angle)}°")

  def _draw_assist(self, painter: QPainter, width: float, scale: float) -> None:
    box = QRectF(width - 275 * scale, 28 * scale, 240 * scale, 86 * scale)
    self._panel(painter, box, 12 * scale)
    engaged = bool(self.sample.get("engaged"))
    override = bool(self.sample.get("steering_pressed") or self.sample.get("gas_pressed") or self.sample.get("brake_pressed"))
    if self.vehicle_brand == "toyota":
      state = str(self.sample.get("tss_status") or (
        "TSS RADAR CRUISE ACTIVE" if self.sample.get("cruise_enabled") else
        "TSS READY" if self.sample.get("cruise_available") else "TSS OFF"
      ))
    else:
      state = "ENGAGED" if engaged else "STANDBY"
    assist_active = bool(self.sample.get("cruise_enabled") or self.sample.get("lta_active") or self.sample.get("stock_aeb"))
    color = GREEN if engaged or assist_active else MUTED
    painter.setFont(self._font(22 * scale, True))
    painter.setPen(WHITE)
    painter.drawText(QRectF(box.x() + 16 * scale, box.y() + 10 * scale, box.width(), 28 * scale), "ASSIST")
    painter.setFont(self._font(19 * scale))
    painter.setPen(color)
    painter.drawText(QRectF(box.x() + 16 * scale, box.y() + 45 * scale, box.width() - 24 * scale, 25 * scale), state)
    if override:
      painter.setFont(self._font(11 * scale, True))
      painter.setPen(ORANGE)
      painter.drawText(QRectF(box.x(), box.bottom() + 3 * scale, box.width(), 18 * scale),
                       Qt.AlignmentFlag.AlignRight, "! DRIVER OVERRIDE")

  def _draw_hybrid(self, painter: QPainter, width: float, scale: float) -> None:
    if self.vehicle_brand != "toyota":
      return
    box = QRectF(width - 275 * scale, 140 * scale, 240 * scale, 114 * scale)
    self._panel(painter, box, 12 * scale)
    battery = self._value(self.sample, "hybrid_battery_percent")
    rpm = self._value(self.sample, "engine_rpm")
    power = self._value(self.sample, "power_flow_kw")
    ev_mode = self.sample.get("ev_mode")
    painter.setFont(self._font(17 * scale, True))
    painter.setPen(WHITE)
    painter.drawText(QRectF(box.x() + 14 * scale, box.y() + 8 * scale, box.width() - 28 * scale, 22 * scale), "HYBRID")
    painter.setFont(self._font(15 * scale))
    painter.setPen(MUTED)
    battery_text = f"Battery {battery:.0f}%" if battery is not None else "Battery --"
    painter.drawText(QRectF(box.x() + 14 * scale, box.y() + 35 * scale, box.width() - 28 * scale, 20 * scale), battery_text)
    mode_text = "EV MODE" if ev_mode is True else "ENGINE" if ev_mode is False else "Mode --"
    painter.setPen(GREEN if ev_mode is True else WHITE if ev_mode is False else MUTED)
    painter.drawText(QRectF(box.x() + 14 * scale, box.y() + 60 * scale, 90 * scale, 20 * scale), mode_text)
    painter.setPen(WHITE)
    rpm_text = f"{round(rpm)} rpm" if rpm is not None else "-- rpm"
    painter.drawText(QRectF(box.x() + 104 * scale, box.y() + 60 * scale, 120 * scale, 20 * scale),
                     Qt.AlignmentFlag.AlignRight, rpm_text)
    source = str(self.sample.get("power_flow_source") or "")
    source_text = " EST" if source == "estimated_traction" else ""
    power_text = f"Power {power:+.1f} kW{source_text}" if power is not None else "Power --"
    painter.setPen(BLUE if power is not None and power < 0 else GREEN if power is not None else MUTED)
    painter.drawText(QRectF(box.x() + 14 * scale, box.y() + 85 * scale, box.width() - 28 * scale, 20 * scale), power_text)

  def _draw_model_path(self, painter: QPainter, width: float, height: float, scale: float) -> None:
    path = self.model_path
    if path is None or len(path.x) < 2:
      return
    center_x = width / 2.0
    horizon_y = height * 0.42
    bottom_y = height - 152 * scale
    left: list[QPointF] = []
    right: list[QPointF] = []
    for forward, lateral in zip(path.x, path.y, strict=False):
      if not math.isfinite(forward) or not math.isfinite(lateral) or forward < 0.0 or forward > 70.0:
        continue
      distance = min(forward / 70.0, 1.0)
      screen_y = bottom_y - distance * (bottom_y - horizon_y)
      perspective = 0.28 + 0.72 * (1.0 - distance)
      lateral_scale = 30.0 * scale * perspective
      center = center_x - lateral * lateral_scale
      half_width = 1.25 * lateral_scale
      left.append(QPointF(center - half_width, screen_y))
      right.append(QPointF(center + half_width, screen_y))
    if len(left) < 2:
      return
    ribbon = QPainterPath(left[0])
    for point in left[1:]:
      ribbon.lineTo(point)
    for point in reversed(right):
      ribbon.lineTo(point)
    ribbon.closeSubpath()
    painter.setPen(QPen(QColor(112, 207, 78, 205), max(1.0, 2.0 * scale)))
    painter.setBrush(QColor(112, 207, 78, 82))
    painter.drawPath(ribbon)

  def _draw_driver(self, painter: QPainter, height: float, scale: float) -> None:
    if self.sample.get("driver_distracted") is None and self.sample.get("driver_face_detected") is None:
      return
    box = QRectF(32 * scale, height * 0.55, 210 * scale, 56 * scale)
    self._panel(painter, box, 11 * scale)
    if self.sample.get("driver_distracted"):
      text, color = "DISTRACTED", ORANGE
    elif self.sample.get("driver_face_detected"):
      text, color = "ATTENTIVE", GREEN
    else:
      text, color = "FACE NOT FOUND", MUTED
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(box.x() + 22 * scale, box.center().y()), 6 * scale, 6 * scale)
    painter.setFont(self._font(20 * scale))
    painter.setPen(color)
    painter.drawText(QRectF(box.x() + 40 * scale, box.y(), box.width() - 44 * scale, box.height()),
                     Qt.AlignmentFlag.AlignVCenter, text)

  def _draw_footer(self, painter: QPainter, width: float, height: float, scale: float) -> None:
    footer = QRectF(18 * scale, height - 58 * scale, width - 36 * scale, 48 * scale)
    self._panel(painter, footer, 16 * scale)
    wall_ms = self.sample.get("wall_time_ms")
    when = datetime.fromtimestamp(int(wall_ms) / 1000).astimezone() if wall_ms else None
    clock = when.strftime("%I:%M:%S %p").lstrip("0") if when else "--:--:--"
    date = when.strftime("%b %d, %Y") if when else "Date unavailable"
    elapsed = round(max(0.0, self.elapsed_seconds))
    duration = f"{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}"
    gps = "GPS unavailable"
    if self.sample.get("gps_has_fix") and self.sample.get("gps_latitude") is not None:
      gps = f"{float(self.sample['gps_latitude']):.5f}, {float(self.sample['gps_longitude']):.5f}"
    painter.setFont(self._font(18 * scale))
    painter.setPen(MUTED)
    painter.drawText(QRectF(footer.x() + 22 * scale, footer.y(), footer.width() * 0.24, footer.height()),
                     Qt.AlignmentFlag.AlignVCenter, clock)
    painter.drawText(QRectF(footer.x() + footer.width() * 0.28, footer.y(), footer.width() * 0.24, footer.height()),
                     Qt.AlignmentFlag.AlignVCenter, date)
    painter.drawText(QRectF(footer.x() + footer.width() * 0.53, footer.y(), footer.width() * 0.16, footer.height()),
                     Qt.AlignmentFlag.AlignVCenter, duration)
    painter.drawText(QRectF(footer.x() + footer.width() * 0.68, footer.y(), footer.width() * 0.29, footer.height()),
                     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, gps)

  def paintEvent(self, _event) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    width, height = float(self.width()), float(self.height())
    scale = min(width / 1280.0, height / 720.0)
    self._draw_model_path(painter, width, height, scale)
    gradient = QPainterPath()
    gradient.addRect(QRectF(0, height - 260 * scale, width, 260 * scale))
    painter.fillPath(gradient, QColor(0, 0, 0, 122))

    speed = max(0.0, (self._value(self.sample, "v_ego_mps") or 0.0) * 2.236936)
    painter.setFont(self._font(92 * scale, True))
    painter.setPen(WHITE)
    painter.drawText(QRectF(width * 0.4, height - 238 * scale, width * 0.2, 104 * scale),
                     Qt.AlignmentFlag.AlignCenter, str(round(speed)))
    painter.setFont(self._font(27 * scale))
    painter.setPen(MUTED)
    painter.drawText(QRectF(width * 0.4, height - 154 * scale, width * 0.2, 38 * scale),
                     Qt.AlignmentFlag.AlignCenter, "mph")

    self._draw_control(painter, "Throttle", height - 128 * scale, self._value(self.sample, "gas"),
                       bool(self.sample.get("gas_pressed")), GREEN, scale)
    tss_aeb = self.vehicle_brand == "toyota" and bool(self.sample.get("stock_aeb"))
    self._draw_control(painter, "Brake", height - 93 * scale, self._value(self.sample, "brake"),
                       bool(self.sample.get("brake_pressed")), RED, scale, "TSS AEB" if tss_aeb else None)
    self._draw_steering(painter, width, height, scale)
    self._draw_assist(painter, width, scale)
    self._draw_hybrid(painter, width, scale)
    self._draw_driver(painter, height, scale)
    self._draw_footer(painter, width, height, scale)
