from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from openpilot.tools.telemetry_viewer.hud import HudOverlay
from openpilot.tools.telemetry_viewer.model import DriveData


class ExportFailure(RuntimeError):
  pass


def find_media_tool(name: str) -> Path:
  module_directory = Path(__file__).resolve().parent
  candidates = [module_directory / name, module_directory / f"{name}.exe"]
  from_path = shutil.which(name) or shutil.which(f"{name}.exe")
  if from_path:
    candidates.append(Path(from_path))
  for candidate in candidates:
    if candidate.is_file():
      return candidate.resolve()
  raise ExportFailure(f"{name} was not found. Install FFmpeg and make sure {name} is on PATH.")


def _video_size(ffprobe: Path, video: Path) -> tuple[int, int]:
  result = subprocess.run([
    str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
    "-of", "json", str(video),
  ], capture_output=True, text=True, check=False)
  if result.returncode:
    raise ExportFailure(result.stderr.strip() or f"Could not inspect {video.name}")
  try:
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])
  except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
    raise ExportFailure(f"Could not read video dimensions from {video.name}") from error


def _read_exact(stream, size: int) -> bytes:
  chunks = bytearray()
  while len(chunks) < size:
    chunk = stream.read(size - len(chunks))
    if not chunk:
      break
    chunks.extend(chunk)
  return bytes(chunks)


def render_drive_mp4(drive: DriveData, output: Path, fps: int = 20,
                     progress: Callable[[int], None] | None = None) -> int:
  videos = [video.local_path for video in drive.videos if video.local_path is not None]
  if not videos:
    raise ExportFailure("No copied road-camera video is available for this drive.")
  ffmpeg = find_media_tool("ffmpeg")
  ffprobe = find_media_tool("ffprobe")
  width, height = _video_size(ffprobe, videos[0])
  frame_size = width * height * 4
  output.parent.mkdir(parents=True, exist_ok=True)

  overlay = HudOverlay()
  overlay.resize(width, height)
  overlay.vehicle_brand = str(drive.metadata.get("vehicle_brand") or "").lower() or None

  with tempfile.TemporaryDirectory(prefix="tskdash-export-") as temporary:
    concat_path = Path(temporary) / "videos.txt"
    concat_path.write_text("".join(f"file '{str(video).replace(chr(39), chr(39) * 2)}'\n" for video in videos), encoding="utf-8")
    decoder = subprocess.Popen([
      str(ffmpeg), "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_path),
      "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "bgra", "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    encoder = subprocess.Popen([
      str(ffmpeg), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}",
      "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    if decoder.stdout is None or decoder.stderr is None or encoder.stdin is None or encoder.stderr is None:
      decoder.kill()
      encoder.kill()
      raise ExportFailure("FFmpeg pipes could not be created.")

    frame_index = 0
    try:
      while True:
        frame = _read_exact(decoder.stdout, frame_size)
        if not frame:
          break
        if len(frame) != frame_size:
          raise ExportFailure("The source video ended with an incomplete frame.")
        elapsed = frame_index / fps
        image = QImage(frame, width, height, QImage.Format.Format_ARGB32).copy()
        overlay.set_sample(drive.sample_at_seconds(elapsed), elapsed, drive.path_at_seconds(elapsed))
        painter = QPainter(image)
        overlay.render(painter)
        painter.end()
        encoder.stdin.write(image.bits().tobytes())
        frame_index += 1
        if frame_index % fps == 0:
          if progress:
            progress(frame_index)
          QApplication.processEvents()
    except (BrokenPipeError, OSError) as error:
      raise ExportFailure(f"FFmpeg stopped while rendering: {error}") from error
    finally:
      encoder.stdin.close()

    decoder_code = decoder.wait()
    encoder_code = encoder.wait()
    decoder_error = decoder.stderr.read().decode("utf-8", errors="replace").strip()
    encoder_error = encoder.stderr.read().decode("utf-8", errors="replace").strip()
    if decoder_code or encoder_code:
      output.unlink(missing_ok=True)
      raise ExportFailure(decoder_error or encoder_error or "FFmpeg could not render the MP4.")
  if frame_index == 0:
    output.unlink(missing_ok=True)
    raise ExportFailure("No video frames were decoded.")
  return frame_index
