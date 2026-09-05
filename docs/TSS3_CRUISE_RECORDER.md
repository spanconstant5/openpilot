# Automatic Toyota TSS3 cruise-button recorder

## What this branch does

Install the branch once and use the comma normally. Whenever openpilot enters its on-road state,
the process manager starts `tss3cruiseprobed`. It passively watches physical receive traffic for:

- `0x24D` (`PCM_CRUISE_4`): the five DBC-named cruise-button bits plus their counter and SecOC
  fields;
- `0x1D3` (`PCM_CRUISE_2`): stock main state, follow distance, low-speed lockout, set speed,
  ACC fault, brake bit, and checksum state.

It records button transitions, every frame while a named button remains asserted, 16 recent
pre-button frames, one neutral `0x24D` sample per second, and one unchanged `0x1D3` sample every
five seconds. Rolling SecOC counter/authenticator changes alone do not create events.

This is evidence collection, not a claim that a later transmit experiment will work on the car.
The DBC bit positions are source-backed, but their physical behavior and bus placement still need
validation on this specific Toyota.

## Safety boundary

The automatic component is receive-only:

- it subscribes to `can` and has no `sendcan` publisher;
- it ignores panda TX-return and TX-rejection receipts (`src >= 0x80`);
- it never creates or replays a CAN frame;
- it changes no panda safety configuration or vehicle actuation code;
- it does not import or start the separate one-shot admission/transmit experiment.

The stock Toyota behavior and openpilot behavior are therefore unchanged by this recorder. This is
still an unvalidated research build: test parked first, keep control of the vehicle, and return to
known-good software if the comma behaves unexpectedly.

## Install like other custom comma software

On the comma setup screen, choose **Custom Software** and enter:

```text
spanconstant5/tss3-passive-recorder
```

The expanded installer address is:

```text
https://installer.comma.ai/spanconstant5/tss3-passive-recorder
```

This installs the branch from `spanconstant5/openpilot`. After installation, there is no separate
service setup, boot script, PID file, or start command. The recorder is a normal openpilot manager
process and starts on every on-road transition. It stops and finalizes the current file when the
comma returns off-road.

If the fork is already installed and you are deliberately updating it over SSH:

```sh
cd /data/openpilot
git fetch origin tss3-passive-recorder
git switch -C tss3-passive-recorder origin/tss3-passive-recorder
sudo reboot
```

Do not copy the recorder into the checkout by hand. A dirty openpilot checkout can interfere with
normal fork updates.

## Where the logs live

```text
/data/tss3-cruise-probe/logs/
```

Each ignition/on-road session receives a unique ID. A file ends in `.active` while it is being
written, then is atomically renamed to `.jsonl` on normal stop or rotation. An unfinished file from
an interrupted reboot is retained as `.recovered.jsonl` at the next start.

Parts rotate after 30 minutes or 8 MiB, whichever comes first. Completed logs are capped at 256
MiB. The oldest completed parts are pruned when that cap is exceeded or the device has less than
2 GiB free. The active file, unrelated files, and paths outside the marker-validated log directory
are never pruned by this process. Files are created private to the device user.

The live status file is in RAM at:

```text
/dev/shm/tss3_cruise_probe_status.json
```

It reports recorder state, buses found, button counts, active filename, archive size, last receive
time, and the latest error. It does not add repeated status writes to flash.

## Check it later over SSH

After connecting to the comma:

```sh
cd /data/openpilot
python -m openpilot.system.tss3_cruise_recorder.control status
python -m openpilot.system.tss3_cruise_recorder.control list
python -m openpilot.system.tss3_cruise_recorder.control summary
```

To include the currently open file in a list or summary, add `--include-active`. Prefer copying
completed `.jsonl` files after the drive ends.

From a computer with SSH access to the comma, replace `DEVICE_IP` and choose a local destination:

```sh
scp "comma@DEVICE_IP:/data/tss3-cruise-probe/logs/*.jsonl" .
```

The JSONL files contain raw payloads and timestamps. Treat them as private vehicle data even though
the recorder intentionally excludes location, video, VIN, and camera/driver-monitoring data.

## First parked test

1. Install the branch and reboot.
2. Turn the vehicle on while safely parked and wait for the normal on-road UI.
3. Press and release one stock cruise button at a time, noting the order and approximate time.
4. Turn the vehicle off and wait for the comma to return off-road.
5. SSH in and run `status`, `list`, and `summary` above.
6. Confirm that the reported names/order match the physical buttons. Preserve the raw logs even if
   a label is wrong; discovering model-specific differences is the purpose of the probe.

Do not perform an active CAN test as part of this checklist. Transmit testing remains separate,
manual, parked-only, and explicitly gated in the standalone research repository.

## Architecture and failure behavior

```text
pandad physical CAN receive stream
              |
              v
 tss3cruiseprobed (subscriber only)
              |
      semantic edge filter
              |
              v
 bounded private JSONL archive + RAM status
```

The process is registered with openpilot's `only_onroad` lifecycle and `restart_if_crash=True`.
Messaging or storage failures put only this recorder into bounded retry/backoff; they do not change
stock cruise, openpilot controls, or panda safety. Manager shutdown sends a normal signal and the
recorder finalizes promptly. If it is forcibly interrupted, the `.active` recovery behavior above
preserves the partial evidence.

To stop automatic recording, switch the comma to another openpilot branch or reinstall known-good
software. Existing files under `/data/tss3-cruise-probe/logs` are intentionally preserved so a
software switch does not silently discard the experiment.
