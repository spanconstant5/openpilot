# Install on comma

## Alpha warning

`v0.1.0-alpha.1` is an owner-test build, not a validated device release. It changes no vehicle
control or panda safety code, but it does change the on-road UI and adds a recording process.
Keep the normal openpilot installer URL available for recovery and test only while able to take
over immediately.

## Device support

| Device | openpilot target | HUD implementation | Alpha status |
| --- | --- | --- | --- |
| comma 3 | `tici` | large on-road HUD | build/desktop checked; hardware test required |
| comma 3X | `tizi` | large on-road HUD | build/desktop checked; hardware test required |
| comma 4 | `mici` | dedicated 300x180 compact HUD | build/desktop checked; hardware test required |

This branch follows current upstream openpilot because official comma four support postdates the
original fork base.

## Install from the comma setup screen

Choose **Custom Software** and type exactly:

```text
spanconstant5/tskdash
```

Both the comma 3/3X and comma 4 setup screens automatically expand a two-part entry to
`https://installer.comma.ai/spanconstant5/tskdash`. The installer then downloads the `tskdash`
branch from `spanconstant5/openpilot`.

## Developer SSH install

For an existing developer installation, connect over SSH and run:

```sh
cd /data/openpilot
git remote add dashcam https://github.com/spanconstant5/openpilot.git || \
  git remote set-url dashcam https://github.com/spanconstant5/openpilot.git
git fetch dashcam tag v0.1.0-alpha.1
git switch --detach v0.1.0-alpha.1
sudo reboot
```

For branch testing before the tag is installed, replace the fetch/switch pair with:

```sh
git fetch dashcam feature/dashcam-telemetry-v1
git switch -C feature/dashcam-telemetry-v1 dashcam/feature/dashcam-telemetry-v1
```

Do not run the comma 4 with a pre-comma-four openpilot base. The alpha tag is based on current
upstream and includes both `mici` and C3/3X UI integrations.

## On-device validation checklist

1. Start a parked on-road session and confirm the camera/model path still render.
2. Confirm speed is bottom-center, Throttle/Brake bottom-left, and steering bottom-right.
3. On comma 4, confirm no compact HUD element clips the 300x180 content area.
4. Confirm normal Toyota cruise displays `TSS CRUISE ACTIVE`; trigger no AEB test intentionally.
5. Press gas, brake, and steering separately; confirm the small orange driver warning.
6. Drive for at least 31 minutes and confirm a completed 30-minute SQLite segment plus an active one.
7. End the route normally; confirm every manifest database entry becomes `complete`.
8. Import with the Windows tool and verify video/telemetry alignment at segment boundaries.
9. Monitor thermal and free-space behavior. Stop testing if the UI stutters or device temperature changes materially.

Hardware validation results should include the device model, vehicle fingerprint, openpilot commit,
drive duration, any missing fields, and whether the route video aligned.

## Recovery

From SSH, switch back to the official remote/branch previously used, or uninstall custom software
from device settings and reinstall from `openpilot.comma.ai`. Telemetry under
`/data/media/0/telemetry` is not deleted automatically.
