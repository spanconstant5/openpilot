# Dashcam telemetry architecture

## Scope and safety boundary

This project adds read-only telemetry recording, a camera HUD, import tooling, and
desktop replay to this openpilot fork. It does not publish control messages, alter
actuator commands, or decode new CAN traffic. The existing `loggerd`/`encoderd`
pipeline remains authoritative for camera video and openpilot logs.

The implementation has four independent pieces:

1. `system.telemetry.telemetryd` subscribes to existing cereal services and writes
   a second, deliberately small SQLite data set.
2. `HudRenderer` paints the live overlay after the existing camera and model-path
   renderers have drawn. Nothing is burned into recorded video.
3. `tools/telemetry_importer` copies only manifest entries marked `complete` and
   then copies the associated existing `fcamera.hevc` segment directories.
4. `tools/telemetry_viewer` discovers those files and synchronizes video playback
   to telemetry using monotonic offsets.

```text
cereal services ---------------------> telemetryd ----> SQLite + manifest
       |                                      |
       |                                      +-------> video associations
       v
UI SubMaster --> camera --> model path --> HUD paint (display only)

/data/media/0/realdata/<route>--N/fcamera.hevc
                          ^
                          | roadEncodeIdx.segmentNum + CurrentRoute
                          |
/data/media/0/telemetry/YYYY-MM-DD/drive_NNN/segment_NNN.db
                          |
                          +---- ADB importer ---- desktop viewer
```

## Verified fork interfaces

The following fields were verified in this checkout rather than inferred from a
newer upstream revision.

| Service | Fields used | Rate in `cereal/services.py` |
| --- | --- | --- |
| `carState` | `vEgo`, `aEgo`, `gas`, `gasPressed`, `brake`, `brakePressed`, `steeringAngleDeg`, `steeringTorque`, `steeringPressed`, `engineRpm` | 100 Hz |
| `selfdriveState` | `state`, `enabled`, `active`, `engageable`, alert text/type/status | 100 Hz |
| `gpsLocationExternal`, `gpsLocation` | latitude, longitude, altitude, speed, bearing, horizontal/speed accuracy, fix, wall-clock GPS time | 10 Hz / 1 Hz |
| `driverMonitoringState` | `faceDetected`, `isDistracted`, `awarenessStatus`, active mode, right-hand-drive state | 20 Hz |
| `driverStateV2` | selected driver `faceProb` and `faceOrientation` | 20 Hz |
| `modelV2` | predicted path `position.x/y/z`, frame id | 20 Hz |
| `roadEncodeIdx` | encoder `segmentNum`, frame/encode ids and timestamps | 20 Hz |

The recorder samples the latest values at 20 Hz instead of persisting all 100 Hz
updates. Change-only events are stored separately. This bounds CPU, storage, and
SQLite transaction overhead while retaining sufficient resolution for a visual
replay HUD.

`CarState.engineRpm` exists in the fork, but not every vehicle interface populates
it. The HUD treats RPM as available only after a positive value is observed during
the current on-road session. It is rendered as compact text, never a tachometer.

No generic messages in this fork identify hybrid battery state-of-charge, EV mode,
hybrid power flow, or exact stock Toyota Safety Sense state. The HUD provider API
therefore returns those values as unavailable by default and hides the related
panel. Vehicle contributors can implement a provider only after adding reviewed,
tested decoding in opendbc; they must not parse speculative CAN addresses in UI or
telemetry code. The generic upper-right indicator is labeled `ASSIST` and reflects
openpilot system state, not stock TSS state.

## On-device recorder

### Lifecycle

`telemetryd` is a `PythonProcess` with the same on-road lifecycle predicate as
`loggerd`. It has no publishers. On start it:

1. creates the telemetry root (`/data/media/0/telemetry` on device),
2. repairs any previously active segments,
3. allocates the next `YYYY-MM-DD/drive_NNN` directory,
4. writes `metadata.json` atomically, and
5. opens `segment_000.db` and advertises it as `active` in `manifest.json`.

The process rotates after 1,800 seconds of monotonic time. Shutdown checkpoints
the WAL, marks the SQLite metadata row complete, closes the database, and finally
changes the manifest entry to `complete`. The importer trusts the manifest only;
an `active`, `corrupt`, missing, or size-changing file is never copied.

At startup, recovery inspects every manifest with an active entry. SQLite WAL
recovery is allowed to complete by opening the database and running
`PRAGMA quick_check`, followed by a checkpoint. A healthy recovered segment is
closed with `close_reason = 'crash_recovered'` and becomes complete. A failed check
is marked corrupt and remains in place for manual inspection.

### Durability and schema

Each database uses:

- `PRAGMA journal_mode=WAL`
- `PRAGMA synchronous=NORMAL`
- batched commits at one-second intervals
- an explicit schema version in both SQLite and JSON metadata
- integer nanosecond monotonic timestamps and integer millisecond UTC timestamps

The normalized event table avoids repeating alert strings in every sample. Model
paths are decimated to 5 Hz and stored separately. See
[`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md) for the full schema.

### Video association

The recorder never opens a camera stream. It observes `roadEncodeIdx.segmentNum`
and `Params("CurrentRoute")`, then records an association to:

```text
/data/media/0/realdata/<CurrentRoute>--<segmentNum>/fcamera.hevc
```

Encoder timestamps and the recorder's receipt monotonic time are both retained.
Replay synchronization uses the association's first telemetry timestamp as the
offset for that one-minute video. This is intentionally metadata-only: encoderd
continues to perform the sole road-camera encode.

## Live HUD

The existing render order is preserved:

1. camera frame,
2. model path, lane lines, and leads,
3. driver monitoring,
4. dashcam HUD.

The HUD reads the existing `UIState::SubMaster`; it opens no sockets and performs
no allocations proportional to route length. Its layout follows the supplied
reference while fitting comma's on-road surface:

- speed: bottom center;
- throttle and brake: bottom left;
- steering-angle scale: bottom right;
- driver attention: left side;
- assist state and optional hybrid provider: upper right;
- RPM: compact numeric text only when available;
- clock, elapsed on-road duration, and GPS fix summary: slim footer.

Pressed booleans are used when analog gas/brake values are absent. Driver override
and system engagement use separate labels and colors. Missing values are omitted,
not shown as synthetic zeroes.

## Desktop replay

The viewer is a Python/PySide6 application. Its data/discovery and synchronization
modules have no Qt dependency and are unit-testable. The UI uses one media player,
one overlay item, and a timeline slider. At a playback position it binary-searches
the sample timestamp index, displays the closest sample, and switches source video
when crossing an association boundary.

Event markers are generated from state transitions and explicit event rows for
driver distraction, brake override, steering override, engagement/disengagement,
and alerts. Summary calculations tolerate absent GPS or driver-monitoring data.

## Windows import

`Import.bat` launches the PowerShell importer. It accepts an `adb.exe` beside the
script or resolves `adb` from `PATH`, requires exactly one authorized device,
downloads manifests first, and constructs a copy plan from complete entries. Files
whose destination size already matches are skipped. Associated video is copied
without changing the source and imports are rooted at:

```text
%USERPROFILE%\Documents\Comma Telemetry\
```

No cleanup occurs in the import command. A future cleanup command must be separate,
explicit, and interactive.

## Failure isolation and resource budget

- A telemetry failure terminates only `telemetryd`; it cannot stop loggerd or UI.
- SQLite I/O is batched, model paths are decimated, and the sampling ceiling is
  20 Hz.
- Disk deletion policy is intentionally not extended in v1. Users must import and
  explicitly remove telemetry when desired.
- The viewer and importer accept missing optional tables, columns, and video.
- The project records no new driver-camera video; face orientation/probability is
  sensitive telemetry and is documented as such.

## Hardware validation gates

Desktop unit tests and builds cannot establish comma-device performance, GPS source
selection, or Toyota signal availability. Before a device release, verify on a
comma 3/3X that recorder CPU and write rates remain acceptable, shutdown leaves no
active manifest entries, every video association opens, and the overlay is readable
in daylight and at night. Vehicle-control behavior must be regression-tested even
though this feature does not change its code paths.
