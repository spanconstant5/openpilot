# Telemetry schema v2

Each drive contains atomic `metadata.json` and `manifest.json` files plus one SQLite database per
30-minute interval. All synchronization uses `mono_time_ns`; `wall_time_ms` is Unix time for display.

## Manifest states

- `active`: writer may still change the database; importer must ignore it.
- `complete`: WAL checkpoint and clean close succeeded; importer may copy it.
- `corrupt`: recovery failed; importer must ignore it.

The manifest also maps route/encoder segment numbers to
`<route>--<segment>/fcamera.hevc`. Metadata includes schema version, sample rate, route when known,
and non-sensitive vehicle brand/fingerprint when CarParams is available.

## SQLite tables

### `segment_metadata`

One row: schema version, drive/segment identity, active/complete status, start/end monotonic and wall
times, and close reason.

### `samples` (20 Hz)

- motion: `v_ego_mps`, `a_ego_mps2`;
- steering: angle, torque, and driver-pressed state;
- longitudinal display: optional analog gas/brake, pressed states, optional RPM and engine-running state;
- hybrid display: nullable battery percentage, EV mode, signed power flow/source, and decoded wheel force;
- existing stock assistance: `stock_aeb`, `cruise_available`, `cruise_enabled`, nullable LTA-active state,
  and a derived TSS status label;
- openpilot state and current alert text/status;
- GPS location, altitude, speed, bearing, accuracy, fix, and GPS wall time;
- driver monitoring: face/distracted state, awareness, face probability, pitch/yaw/roll;
- encoder association: road segment and encoder identifiers.

SQLite uses ordinary `NULL` for unavailable optional values. A missing analog value is distinct from
zero throttle or brake.

Schema v2 readers remain compatible with schema v1 recordings. For the 2025 Corolla Hybrid,
unverified battery state-of-charge remains `NULL`; the recorder never substitutes a guessed value.

### `events`

Change-only engagement, alert, distraction, brake override, and steering override records with
optional severity and JSON details.

### `model_paths` (5 Hz)

Model frame id plus JSON arrays for predicted path x/y/z. Decimation bounds storage and replay work.

### `video_segments`

Route, segment number, relative source path, first/last telemetry time, and encoder timestamps. The
table contains associations only; no video bytes are stored in SQLite.

## Durability

Databases use WAL mode, `synchronous=NORMAL`, one-second commits, an explicit final checkpoint, and
atomic JSON replacement. Startup `quick_check` recovery finalizes a healthy database left active by
an unexpected shutdown.
