# Changelog

## Unreleased — Phase 3 Toyota hybrid owner-test build

Status: prepared on `codex/phase3-toyota-hybrid` and intended for upload without a tag, release, or
pull request. Phase 1 remains on `tskdash`; Phase 2 remains on `codex/phase2-desktop-replay`.

### Toyota and TSS

- Read-only decode of allowlisted signals already present in the selected Toyota DBC: engine RPM,
  engine-running state, signed hybrid drive force, and LTA state
- EV mode derived only from a fresh engine signal
- Signed wheel-power calculation, with motion-derived fallback visibly marked `EST`
- TSS status distinguishes actively engaged radar cruise and LTA from manual city driving
- Hybrid battery percentage stays unavailable until a verified 2025 Corolla Hybrid mapping exists

### Replay and export

- Openpilot-style path ribbon from recorded `modelV2` trajectory data
- Moving GPS route marker and explicit OpenStreetMap browser link
- Local FFmpeg-based rendered MP4 export with synchronized HUD and path
- Telemetry schema v2 with backward-compatible schema v1 replay

### Platform app branches

- `codex/phase3-windows-app`
- `codex/phase3-macos-app`
- `codex/phase3-linux-app`

Each platform branch contains lightweight import/view launchers and a PyInstaller build script over
the same audited Python core. None is a published release or signed binary.

## Unreleased — planned `v0.1.1-alpha.1` (Phase 2)

Status: uploaded to `codex/phase2-desktop-replay` for owner testing, but not published as a GitHub
release. The `tskdash` branch and `v0.1.0-alpha.1` Phase 1 release are unchanged.

### Phase 2 checklist

- Desktop replay application
- Windows `Import.bat` launcher and resumable ADB importer
- Read-only SQLite telemetry parser
- Telemetry/video synchronization across route segments
- Synchronized HUD replay and event markers
- Offline GPS route and drive summary
- Dedicated Statistics page with distance, duration, average/maximum speed, assist engagement,
  distraction, driver override, GPS coverage, video availability, steering range, sample count,
  route-point count, and event totals
- Empty-drive handling that does not display a false epoch timestamp

### Validation

- Ruff passed
- Python compilation passed
- 14 focused telemetry, importer, replay, and HUD tests passed
- Synthetic-data offscreen replay and Statistics page render passed

## `v0.1.0-alpha.1` — Phase 1 road-test build

- Manager-owned 20 Hz SQLite telemetry recorder
- Recoverable 30-minute segmentation and manifest tracking
- comma 3, comma 3X, and comma 4 HUD integrations
- Bottom-centered speed, Throttle/Brake bars, steering scale, driver attention, timestamp, TSS state,
  orange driver-override warning, and compact numeric RPM
- Published comma install entry: `spanconstant5/tskdash`
