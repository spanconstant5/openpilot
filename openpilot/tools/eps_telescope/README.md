# EPS Telescope for comma4

EPS Telescope is integrated into the comma touchscreen. It requires no SSH,
terminal commands, or separate dependency installation after this openpilot
fork is installed.

## Install

Uninstall the current software from the comma, and enter:

```text
installer.comma.ai/spanconstant5/eps
```

This is the GitHub-fork installation format documented by comma. If the fork
causes startup trouble, restore the device at
[flash.comma.ai](https://flash.comma.ai), then install stock openpilot.

The installer also fetches the pinned upstream EPS Telescope submodule. No
separate clone, package install, SSH session, or terminal command is needed.

## Use on comma4

1. Turn the vehicle ignition on.
2. Keep the vehicle completely stationary in Park with openpilot disengaged.
3. Open **Settings → EPS Scope**.
4. Select **UDS**, **Security**, or **Deep**.
5. Choose whether to identify the vehicle. In Deep mode, choose whether to scan
   the firmware signature.
6. Press **Run**, read the confirmation, and leave the vehicle in Park until
   normal comma services are restored.
7. After a Deep run, power the vehicle fully off and back on before driving.

Reports are saved under `/data/eps_telescope/<timestamp>/` as `probe.json`
and `probe.md`. The latest result is also available through **Last Result**.
With **Prepare PC Download** enabled, each run also creates a
`<timestamp>.eps-telescope.zip` bundle under the comma telemetry folder.

To copy it off the comma, enable ADB in **Settings → Developer**, run
`tools/telemetry_portal/Open-CommaPortal.bat` on the Windows PC, connect to
the comma's private IP, and press **Copy** next to the EPS Telescope bundle.
The bundle can then be attached to a private GitHub issue if desired. This
design avoids storing a GitHub access token on the comma.

## Mode boundaries

- **UDS** uses only the default diagnostic session. It does not request
  Security Access, enter the programming session, probe RequestDownload, or
  upload code.
- **Security** uses the default and extended diagnostic sessions and checks
  Security Access. It does not enter the programming session, probe
  RequestDownload, or upload code.
- **Deep** enters the programming session, probes RequestDownload, checks
  Security Access, and uploads the SHA-256-pinned read-only payload to RAM. It
  never writes flash.

Starting any mode pauses normal openpilot driving processes and `pandad` so
the probe has exclusive access to the Panda. Completion, cancellation, and
errors all clear probe mode so the manager restores normal services.

## Safety and recovery

- Do not start a run unless the vehicle is stationary in Park.
- Do not shift, steer, or drive during a run.
- The UI and manager independently reject a start unless the car is in Park,
  stationary, and openpilot is disengaged.
- Deep mode can leave the EPS in an altered diagnostic state despite the
  best-effort return to the default session. Always power-cycle afterward.
- This is third-party software. comma support requires reproducing hardware
  issues on stock openpilot.
