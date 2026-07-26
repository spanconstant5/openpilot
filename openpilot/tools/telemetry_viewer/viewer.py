from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget)

from openpilot.tools.telemetry_viewer.hud import HudOverlay
from openpilot.tools.telemetry_viewer.model import DriveData, Event, VideoSegment


EVENT_COLORS = {
  "driver_distraction": QColor("#ff9123"),
  "brake_override": QColor("#e74141"),
  "steering_override": QColor("#1f89e5"),
  "engagement": QColor("#70cf4e"),
  "alert": QColor("#ffd34d"),
}


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
    self.setCentralWidget(splitter)

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
    date = datetime.fromtimestamp(summary.start_wall_ms / 1000).astimezone().strftime("%b %d, %Y %I:%M %p")
    self.summary_label.setText("\n".join((
      date,
      f"Duration: {self._format_time(summary.duration_seconds)}",
      f"Distance: {summary.distance_meters / 1609.344:.2f} mi",
      f"Average: {summary.average_speed_mps * 2.236936:.1f} mph",
      f"Maximum: {summary.maximum_speed_mps * 2.236936:.1f} mph",
      f"Distracted: {self._format_time(summary.distracted_seconds)}",
      f"Video: {sum(video.local_path is not None for video in drive.videos)}/{len(drive.videos)} segments available",
    )))
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
  application.setStyleSheet("QWidget { background: #12161a; color: #f2f4f5; } " +
                            "QPushButton { padding: 7px 18px; background: #263039; border-radius: 5px; }")
  window = ReplayWindow(args.drive)
  window.show()
  raise SystemExit(application.exec())


if __name__ == "__main__":
  main()
