from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from openpilot.tools.telemetry_viewer.hud import HudOverlay
from openpilot.tools.telemetry_viewer.model import DriveData, DriveSummary, Event, VideoSegment


EVENT_COLORS = {
  "driver_distraction": QColor("#ff9123"),
  "brake_override": QColor("#e74141"),
  "steering_override": QColor("#1f89e5"),
  "engagement": QColor("#70cf4e"),
  "alert": QColor("#ffd34d"),
}

APP_STYLESHEET = " ".join((
  "QWidget { background: #12161a; color: #f2f4f5; }",
  "QPushButton { padding: 7px 18px; background: #263039; border-radius: 5px; }",
  "QTabBar::tab { padding: 9px 22px; background: #1c2329; }",
  "QTabBar::tab:selected { background: #2b363f; color: #70cf4e; }",
  "QFrame#statisticCard { background: #1a2025; border: 1px solid #323b42; border-radius: 8px; }",
  "QLabel#statisticTitle { color: #9da5ad; font-size: 11px; font-weight: 600; }",
  "QLabel#statisticValue { color: #f2f4f5; font-size: 24px; font-weight: 600; }",
  "QLabel#statisticDetail { color: #9da5ad; font-size: 11px; }",
  "QLabel#statisticsHeading { font-size: 28px; font-weight: 600; }",
  "QLabel#statisticsDate { color: #9da5ad; margin-bottom: 12px; }",
  "QLabel#statisticsPanel { background: #1a2025; border: 1px solid #323b42; border-radius: 8px; padding: 14px; min-height: 100px; }",
))


class MarkerSlider(QSlider):
  def __init__(self):
    super().__init__(Qt.Orientation.Horizontal)
    self.markers: list[tuple[float, QColor]] = []

  def set_events(self, events: list[Event], start_mono_ns: int, duration_seconds: float) -> None:
    denominator = max(duration_seconds * 1e9, 1.0)
    self.markers = [
      (max(0.0, min(1.0, (event.mono_time_ns - start_mono_ns) / denominator)),
       EVENT_COLORS.get(event.kind, QColor("white")))
      for event in events
    ]
    self.update()

  def paintEvent(self, event) -> None:
    super().paintEvent(event)
    painter = QPainter(self)
    for fraction, color in self.markers:
      x = 8 + fraction * max(1, self.width() - 16)
      painter.fillRect(round(x) - 1, 0, 3, 7, color)


class RouteWidget(QWidget):
  def __init__(self):
    super().__init__()
    self.points: list[tuple[float, float]] = []
    self.setMinimumHeight(120)

  def set_points(self, points: list[tuple[float, float]]) -> None:
    self.points = points
    self.update()

  def paintEvent(self, _event) -> None:
    painter = QPainter(self)
    painter.fillRect(self.rect(), QColor("#101418"))
    if len(self.points) < 2:
      painter.setPen(QColor("#9da5ad"))
      painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "GPS route unavailable")
      return
    latitudes = [point[0] for point in self.points]
    longitudes = [point[1] for point in self.points]
    lat_span = max(max(latitudes) - min(latitudes), 1e-8)
    lon_span = max(max(longitudes) - min(longitudes), 1e-8)
    projected = []
    for latitude, longitude in self.points:
      x = 12 + (longitude - min(longitudes)) / lon_span * (self.width() - 24)
      y = self.height() - 12 - (latitude - min(latitudes)) / lat_span * (self.height() - 24)
      projected.append((x, y))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#70cf4e"))
    for start, end in zip(projected, projected[1:], strict=False):
      painter.drawLine(round(start[0]), round(start[1]), round(end[0]), round(end[1]))


class StatisticCard(QFrame):
  def __init__(self, title: str):
    super().__init__()
    self.setObjectName("statisticCard")
    self.setMinimumHeight(105)
    layout = QVBoxLayout(self)
    title_label = QLabel(title.upper())
    title_label.setObjectName("statisticTitle")
    self.value_label = QLabel("—")
    self.value_label.setObjectName("statisticValue")
    self.detail_label = QLabel("")
    self.detail_label.setObjectName("statisticDetail")
    layout.addWidget(title_label)
    layout.addWidget(self.value_label)
    layout.addWidget(self.detail_label)

  def set_value(self, value: str, detail: str = "") -> None:
    self.value_label.setText(value)
    self.detail_label.setText(detail)


class StatisticsPage(QWidget):
  def __init__(self):
    super().__init__()
    layout = QVBoxLayout(self)
    layout.setContentsMargins(28, 24, 28, 24)
    heading = QLabel("Drive statistics")
    heading.setObjectName("statisticsHeading")
    self.date_label = QLabel("Open a copied drive folder to view statistics.")
    self.date_label.setObjectName("statisticsDate")
    layout.addWidget(heading)
    layout.addWidget(self.date_label)

    self.cards = {name: StatisticCard(title) for name, title in (
      ("distance", "Distance"),
      ("duration", "Duration"),
      ("average_speed", "Average speed"),
      ("maximum_speed", "Maximum speed"),
      ("engagement", "Assist engaged"),
      ("distraction", "Driver distracted"),
      ("override", "Driver override"),
      ("gps", "GPS coverage"),
    )}
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(14)
    for index, card in enumerate(self.cards.values()):
      grid.addWidget(card, index // 4, index % 4)
    layout.addLayout(grid)

    detail_grid = QGridLayout()
    self.data_label = QLabel("No telemetry loaded")
    self.data_label.setObjectName("statisticsPanel")
    self.data_label.setAlignment(Qt.AlignmentFlag.AlignTop)
    self.event_label = QLabel("No events loaded")
    self.event_label.setObjectName("statisticsPanel")
    self.event_label.setAlignment(Qt.AlignmentFlag.AlignTop)
    detail_grid.addWidget(self.data_label, 0, 0)
    detail_grid.addWidget(self.event_label, 0, 1)
    detail_grid.setColumnStretch(0, 1)
    detail_grid.setColumnStretch(1, 1)
    layout.addLayout(detail_grid)
    layout.addStretch()

  @staticmethod
  def _format_time(seconds: float) -> str:
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

  def set_summary(self, summary: DriveSummary, available_videos: int, total_videos: int) -> None:
    date = (datetime.fromtimestamp(summary.start_wall_ms / 1000).astimezone().strftime("%B %d, %Y at %I:%M %p")
            if summary.start_wall_ms else "Recording time unavailable")
    duration = max(summary.duration_seconds, 1e-9)
    self.date_label.setText(date)
    self.cards["distance"].set_value(
      f"{summary.distance_meters / 1609.344:.2f} mi", f"{summary.distance_meters / 1000:.2f} km")
    self.cards["duration"].set_value(self._format_time(summary.duration_seconds))
    self.cards["average_speed"].set_value(f"{summary.average_speed_mps * 2.236936:.1f} mph")
    self.cards["maximum_speed"].set_value(f"{summary.maximum_speed_mps * 2.236936:.1f} mph")
    self.cards["engagement"].set_value(
      self._format_time(summary.engaged_seconds), f"{summary.engaged_seconds / duration * 100:.1f}% of drive")
    self.cards["distraction"].set_value(
      self._format_time(summary.distracted_seconds), f"{summary.distracted_seconds / duration * 100:.1f}% of drive")
    self.cards["override"].set_value(
      self._format_time(summary.driver_override_seconds), f"{summary.driver_override_seconds / duration * 100:.1f}% of drive")
    self.cards["gps"].set_value(f"{summary.gps_fix_percent:.1f}%", "samples with a GPS fix")
    self.data_label.setText("\n".join((
      "DATA COVERAGE",
      f"Telemetry samples: {summary.sample_count:,}",
      f"Video segments: {available_videos}/{total_videos} available",
      f"Maximum steering angle: {summary.maximum_steering_angle_deg:.1f}°",
      f"GPS route points: {len(summary.gps_route):,}",
    )))
    event_lines = ["EVENTS"]
    if summary.event_counts:
      event_lines.extend(f"{kind.replace('_', ' ').title()}: {count}" for kind, count in sorted(summary.event_counts.items()))
    else:
      event_lines.append("No recorded event activations")
    self.event_label.setText("\n".join(event_lines))


class VideoCanvas(QFrame):
  def __init__(self):
    super().__init__()
    self.setStyleSheet("background: #050709;")
    self.video = QVideoWidget(self)
    self.hud = HudOverlay(self)

  def resizeEvent(self, event) -> None:
    super().resizeEvent(event)
    self.video.setGeometry(self.rect())
    self.hud.setGeometry(self.rect())
    self.hud.raise_()


class ReplayWindow(QMainWindow):
  def __init__(self, drive_directory: Path | None = None):
    super().__init__()
    self.setWindowTitle("Comma Telemetry Replay")
    self.resize(1280, 820)
    self.drive: DriveData | None = None
    self.current_video: VideoSegment | None = None
    self.current_seconds = 0.0
    self.scrubbing = False
    self.pending_position_ms: int | None = None
    self.resume_after_load = False

    self.player = QMediaPlayer(self)
    self.audio = QAudioOutput(self)
    self.audio.setMuted(True)
    self.player.setAudioOutput(self.audio)
    self.canvas = VideoCanvas()
    self.player.setVideoOutput(self.canvas.video)
    self.player.positionChanged.connect(self._media_position_changed)
    self.player.mediaStatusChanged.connect(self._media_status_changed)

    self.play_button = QPushButton("Play")
    self.play_button.clicked.connect(self.toggle_playback)
    self.timeline = MarkerSlider()
    self.timeline.setRange(0, 0)
    self.timeline.sliderPressed.connect(self._scrub_started)
    self.timeline.sliderReleased.connect(self._scrub_finished)
    self.timeline.sliderMoved.connect(self._scrub_preview)
    self.position_label = QLabel("00:00 / 00:00")

    controls = QHBoxLayout()
    controls.addWidget(self.play_button)
    controls.addWidget(self.timeline, 1)
    controls.addWidget(self.position_label)
    video_column = QVBoxLayout()
    video_column.setContentsMargins(0, 0, 0, 0)
    video_column.addWidget(self.canvas, 1)
    video_column.addLayout(controls)
    video_container = QWidget()
    video_container.setLayout(video_column)

    self.summary_label = QLabel("Open a copied drive folder to begin.")
    self.summary_label.setWordWrap(True)
    self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop)
    self.route = RouteWidget()
    side_layout = QVBoxLayout()
    side_layout.addWidget(QLabel("Drive summary"))
    side_layout.addWidget(self.summary_label)
    side_layout.addWidget(QLabel("GPS route"))
    side_layout.addWidget(self.route)
    side_layout.addStretch()
    side = QWidget()
    side.setMinimumWidth(255)
    side.setMaximumWidth(360)
    side.setLayout(side_layout)

    splitter = QSplitter()
    splitter.addWidget(video_container)
    splitter.addWidget(side)
    splitter.setStretchFactor(0, 1)
    self.statistics_page = StatisticsPage()
    self.pages = QTabWidget()
    self.pages.addTab(splitter, "Replay")
    self.pages.addTab(self.statistics_page, "Statistics")
    self.setCentralWidget(self.pages)

    file_menu = self.menuBar().addMenu("File")
    open_action = QAction("Open drive folder…", self)
    open_action.setShortcut("Ctrl+O")
    open_action.triggered.connect(self.choose_drive)
    file_menu.addAction(open_action)

    self.timer = QTimer(self)
    self.timer.setInterval(50)
    self.timer.timeout.connect(self._tick)
    self.timer.start()
    self.synthetic_playing = False

    if drive_directory is not None:
      QTimer.singleShot(0, lambda: self.open_drive(drive_directory))

  @staticmethod
  def _format_time(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"

  def choose_drive(self) -> None:
    selected = QFileDialog.getExistingDirectory(self, "Open telemetry drive")
    if selected:
      self.open_drive(Path(selected))

  def open_drive(self, directory: Path) -> None:
    try:
      drive = DriveData.open(directory)
    except (OSError, ValueError) as error:
      QMessageBox.critical(self, "Unable to open drive", str(error))
      return
    self.player.stop()
    self.drive = drive
    self.canvas.hud.vehicle_brand = str(drive.metadata.get("vehicle_brand")) if drive.metadata.get("vehicle_brand") else None
    self.current_video = None
    self.current_seconds = 0.0
    self.synthetic_playing = False
    self.play_button.setText("Play")
    self.timeline.setRange(0, max(0, round(drive.duration_seconds * 1000)))
    self.timeline.set_events(drive.markers(), drive.start_mono_ns, drive.duration_seconds)
    summary = drive.summary()
    date = (datetime.fromtimestamp(summary.start_wall_ms / 1000).astimezone().strftime("%b %d, %Y %I:%M %p")
            if summary.start_wall_ms else "Recording time unavailable")
    self.summary_label.setText("\n".join((
      date,
      f"Duration: {self._format_time(summary.duration_seconds)}",
      f"Distance: {summary.distance_meters / 1609.344:.2f} mi",
      f"Average: {summary.average_speed_mps * 2.236936:.1f} mph",
      f"Maximum: {summary.maximum_speed_mps * 2.236936:.1f} mph",
      f"Distracted: {self._format_time(summary.distracted_seconds)}",
      f"Video: {sum(video.local_path is not None for video in drive.videos)}/{len(drive.videos)} segments available",
    )))
    available_videos = sum(video.local_path is not None for video in drive.videos)
    self.statistics_page.set_summary(summary, available_videos, len(drive.videos))
    self.route.set_points(summary.gps_route)
    self._set_position(0.0, force_video=True)
    self.setWindowTitle(f"Comma Telemetry Replay — {directory.name}")

  def toggle_playback(self) -> None:
    if self.drive is None:
      self.choose_drive()
      return
    if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or self.synthetic_playing:
      self.player.pause()
      self.synthetic_playing = False
      self.play_button.setText("Play")
      return
    video = self._video_at(self.current_seconds)
    if video is not None and video.local_path is not None:
      self._select_video(video, self.current_seconds, resume=True)
    else:
      self.synthetic_playing = True
    self.play_button.setText("Pause")

  def _video_at(self, seconds: float) -> VideoSegment | None:
    if self.drive is None:
      return None
    return self.drive.video_for_mono_time(self.drive.start_mono_ns + round(seconds * 1e9))

  def _select_video(self, video: VideoSegment, seconds: float, resume: bool) -> None:
    if self.drive is None or video.local_path is None:
      return
    position_ms = max(0, round((self.drive.start_mono_ns + seconds * 1e9 - video.first_mono_ns) / 1e6))
    if self.current_video != video:
      self.current_video = video
      self.pending_position_ms = position_ms
      self.resume_after_load = resume
      self.player.setSource(QUrl.fromLocalFile(str(video.local_path)))
    else:
      self.player.setPosition(position_ms)
      if resume:
        self.player.play()

  def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
    if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
      if self.pending_position_ms is not None:
        self.player.setPosition(self.pending_position_ms)
        self.pending_position_ms = None
      if self.resume_after_load:
        self.resume_after_load = False
        self.player.play()

  def _media_position_changed(self, position_ms: int) -> None:
    if self.scrubbing or self.drive is None or self.current_video is None:
      return
    seconds = (self.current_video.first_mono_ns - self.drive.start_mono_ns) / 1e9 + position_ms / 1000
    self._set_position(seconds)

  def _set_position(self, seconds: float, force_video: bool = False) -> None:
    if self.drive is None:
      return
    self.current_seconds = max(0.0, min(self.drive.duration_seconds, seconds))
    if not self.scrubbing:
      self.timeline.setValue(round(self.current_seconds * 1000))
    self.canvas.hud.set_sample(self.drive.sample_at_seconds(self.current_seconds), self.current_seconds)
    self.position_label.setText(
      f"{self._format_time(self.current_seconds)} / {self._format_time(self.drive.duration_seconds)}")
    video = self._video_at(self.current_seconds)
    if force_video and video is not None and video.local_path is not None:
      self._select_video(video, self.current_seconds, resume=False)
    elif (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and video is not None and
          video.local_path is not None and video != self.current_video):
      self._select_video(video, self.current_seconds, resume=True)

  def _scrub_started(self) -> None:
    self.scrubbing = True

  def _scrub_preview(self, value: int) -> None:
    if self.drive is None:
      return
    seconds = value / 1000
    self.current_seconds = seconds
    self.canvas.hud.set_sample(self.drive.sample_at_seconds(seconds), seconds)
    self.position_label.setText(f"{self._format_time(seconds)} / {self._format_time(self.drive.duration_seconds)}")

  def _scrub_finished(self) -> None:
    if self.drive is None:
      return
    was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or self.synthetic_playing
    self.scrubbing = False
    self._set_position(self.timeline.value() / 1000, force_video=True)
    video = self._video_at(self.current_seconds)
    if video is not None and video.local_path is not None:
      self.synthetic_playing = False
      self._select_video(video, self.current_seconds, resume=was_playing)

  def _tick(self) -> None:
    if self.drive is None or self.scrubbing:
      return
    if self.synthetic_playing:
      next_position = self.current_seconds + self.timer.interval() / 1000
      if next_position >= self.drive.duration_seconds:
        self.synthetic_playing = False
        self.play_button.setText("Play")
      self._set_position(next_position)


def main() -> None:
  parser = argparse.ArgumentParser(description="Replay a copied comma telemetry drive")
  parser.add_argument("drive", type=Path, nargs="?", help="drive folder containing manifest.json")
  args = parser.parse_args()
  application = QApplication(sys.argv[:1])
  application.setStyleSheet(APP_STYLESHEET)
  window = ReplayWindow(args.drive)
  window.show()
  raise SystemExit(application.exec())


if __name__ == "__main__":
  main()
