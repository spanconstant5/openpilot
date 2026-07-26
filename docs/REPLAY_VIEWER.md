# Desktop replay viewer

The viewer is a Windows-first, cross-platform PySide6 application. It opens one imported drive
folder, discovers completed SQLite segments, switches associated `fcamera.hevc` files, and overlays
the same layout used on-device.

## Setup and launch

From the repository root on Windows:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r tools\telemetry_viewer\requirements.txt
tools\telemetry_viewer\ReplayViewer.bat
```

Open a folder containing `manifest.json`, or pass it on the command line. Qt uses the operating
system's media backend; HEVC playback requires a working HEVC decoder on the PC. Telemetry-only
playback still works when video or a codec is absent.

The **Replay** page includes timeline markers for distraction, brake/steering override, engagement
changes, and alerts. Its side panel reports the drive summary, video availability, and a simple
offline GPS trace.

The dedicated **Statistics** page reports distance, duration, average and maximum speed, assist
engagement time, distracted time, driver-override time, GPS coverage, telemetry sample count,
video coverage, maximum steering angle, route-point count, and event-activation totals. Statistics
are calculated locally from the imported read-only SQLite segments; no network service is used.

## Generate a safe sample

No real recording is committed to Git. Generate three minutes of synthetic telemetry with:

```powershell
.venv\Scripts\python.exe -m openpilot.tools.telemetry_viewer.generate_sample sample_telemetry
```

Then open `sample_telemetry\<date>\drive_001`. It intentionally contains no video so UI behavior can
be tested without a comma. Delete the generated folder when finished.

## Synchronization

Every video association stores the recorder's first/last monotonic sample time for one openpilot
route segment. The viewer converts its global telemetry position to a local video offset and uses a
binary search for the nearest 20 Hz sample. It changes video source when playback crosses the next
association boundary.
