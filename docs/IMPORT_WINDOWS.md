# Import recordings on Windows

The importer reads manifests over ADB, selects only SQLite entries marked `complete`, and copies
their associated existing road-camera segments. It never deletes device data.

## Setup

1. Install Python 3.11 or newer.
2. Install Android platform-tools, or place `adb.exe` beside
   `tools\telemetry_importer\Import.bat`.
3. Connect exactly one comma by USB and accept its debugging authorization prompt.
4. Run `adb devices` once and confirm its state is `device`, not `unauthorized`.

## Import

Double-click `tools\telemetry_importer\Import.bat`, or run:

```powershell
tools\telemetry_importer\Import.bat
```

The default destination is `%USERPROFILE%\Documents\Comma Telemetry\YYYY-MM-DD\drive_NNN`.
Pass another location through PowerShell when needed:

```powershell
tools\telemetry_importer\Import-CommaTelemetry.ps1 -Destination D:\CommaTelemetry
```

The importer preserves timestamps with `adb pull -a`, verifies sizes, and skips files whose local
size already matches. Re-running it is safe. An active or corrupt SQLite segment is ignored until a
later import finds it completed or recovered. Missing optional metadata or video produces a clear
message without modifying the comma.

No cleanup command is supplied in this alpha. Review imported files and available device space
manually before removing anything over SSH.
