# Cross-platform desktop apps

The importer, SQLite parser, replay HUD, statistics page, route view, and MP4 renderer share one
Python/PySide6 core. Phase 3 adds small OS-specific launcher/build layers on separate unpublished
branches:

| Platform | Branch | Launchers |
| --- | --- | --- |
| Windows | `codex/phase3-windows-app` | `.bat` launchers and PowerShell build |
| macOS | `codex/phase3-macos-app` | `.command` launchers and shell build |
| Linux | `codex/phase3-linux-app` | shell launchers, `.desktop` file, and shell build |

The importer uses ADB over USB and defaults to `~/Documents/Comma Telemetry` on every platform.
The viewer opens an imported drive folder containing `manifest.json`. MP4 rendering additionally
requires `ffmpeg` and `ffprobe` on `PATH`.

The build scripts use PyInstaller to create local, unsigned artifacts. macOS Gatekeeper and Windows
SmartScreen may warn about unsigned builds; Linux desktop files may need to be marked executable.
No prebuilt app is published in this alpha, and none of these desktop branches changes the comma
install URL `spanconstant5/tskdash`.
