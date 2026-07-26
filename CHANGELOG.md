# Changelog

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
- Immediate SQLite commit/checkpoint when a known panda reports ignition off

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
