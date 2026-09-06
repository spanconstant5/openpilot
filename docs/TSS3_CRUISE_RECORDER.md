# Automatic Toyota TSS3 cruise-button recorder

## What this branch does

Install the branch once and use the comma normally. Whenever openpilot enters its on-road state,
the process manager starts `tss3cruiseprobed`. **Discovery v2** records all physical CAN frames
delivered to its cereal subscriber, including other addresses, short frames and longer payloads.
It preserves every delivered payload, its bus, message order within a batch, and the batch timestamp.
It applies no button decoder or address filter. TX-return/rejection receipts are counted and excluded.

The original recorder watched only `0x24D` and `0x1D3`, requiring eight-byte payloads. The two
September 5 captures contained 720 and 800 retained `0x24D` records respectively, on buses 0 and 2,
with no decoded button transitions or `0x1D3` records. The owner confirmed actual cruise-button
presses and stock set-speed changes during both captures. The limited recordings cannot distinguish
an address/layout mismatch, a payload-length mismatch, or traffic inaccessible through the current
wiring/receive path. Discovery v2 removes those software filtering assumptions.

Recording is best effort: it only sees traffic supplied by pandad to this subscriber. It does not
prove that every frame on every vehicle network is visible or that the underlying queue lost none.
Each log records event validity and source/receive timestamps; status includes counts per bus,
address and length, plus maximum observed delivery age. No CAN transmission is introduced.

## Pin-swap hardware context

The target vehicle owner reports that the Toyota pin-swap is already installed. That is important
provenance for these captures, but it is not something software can verify. The recorder does not
assume a fixed bus number: it watches every physical panda source bus (`src < 0x80`) and stores the
observed bus with every retained frame.

Document the pin-swap version, orientation, and any harness labels alongside the logs. If a capture
contains no target frames, treat that as an inconclusive wiring/routing result—not proof that the
vehicle never sends the messages. Verify harness seating and the intended pin map with vehicle
power removed; do not insert, remove, or repin a powered harness.

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

To update an existing installation of this recorder branch over SSH, first confirm
`git branch --show-current` prints `tss3-passive-recorder`. Then:

```sh
cd /data/openpilot
git fetch origin tss3-passive-recorder
git merge --ff-only FETCH_HEAD
sudo reboot
```

Do not copy the recorder into the checkout by hand. A dirty openpilot checkout can interfere with
normal fork updates.

## Where the logs live

```text
/data/tss3-cruise-probe/logs/
```

Each ignition/on-road session receives a unique ID. Discovery files end in `.jsonl.gz.active` while
being written, then are renamed to `.jsonl.gz` on normal stop or rotation. An unfinished file from
an interrupted reboot is retained with `.recovered.jsonl.gz` at the next start. A missing gzip
footer or incomplete last line is reported by the summary tool; earlier flushed records may still
be recovered. Abrupt power loss can lose buffered data. Older `.jsonl` recordings remain readable.

Parts rotate after 30 minutes or 8 MiB of uncompressed JSON, whichever comes first when writing.
Compression uses the Python standard library at its fastest level. Completed logs are capped at 256
MiB. The oldest completed parts are pruned when that cap is exceeded or the device has less than
2 GiB free. Free space is checked at least every five seconds while processing. If pruning cannot
restore the floor, recording pauses and retries. The active part is additional to the completed-log
cap. Keep this directory dedicated to recordings: matching completed JSONL/gzip files are eligible
for pruning. Files outside this directory are not pruned. Files are private to the device user.

The live status file is in RAM at:

```text
/dev/shm/tss3_cruise_probe_status.json
```

It reports capture version, recorder state, buses found, raw frame counts, traffic inventory, active
filename, archive size, last receive time, and the latest error. It does not report inferred button
counts in discovery mode. Final session statistics are retained in the stopped status and saved to
the archive on orderly shutdown. Status uses RAM rather than repeated flash writes.

## Check it later over SSH

After connecting to the comma:

```sh
cd /data/openpilot
python -m openpilot.system.tss3_cruise_recorder.control status
python -m openpilot.system.tss3_cruise_recorder.control list
python -m openpilot.system.tss3_cruise_recorder.control summary
```

After updating, `status` must show `discovery-v2`. To include the currently open file in a list or
summary, add `--include-active`; an active gzip file may report truncation until finalized.
Copy **all parts** of a completed test after the drive ends.

From a computer with SSH access to the comma, replace `DEVICE_IP` and choose a local destination:

```sh
scp "comma@DEVICE_IP:/data/tss3-cruise-probe/logs/*.jsonl.gz" .
```

The compressed files contain raw payloads and timestamps. Broader CAN traffic can contain vehicle
identifiers and other sensitive data; its contents are not privacy-filtered. Keep the capture private.

Each `can_batch` record has `frames` entries `[bus, address, data_hex]`. `mono_time_ns` is the
cereal event timestamp, shared by the batch; `received_mono_ns` and `wall_time_ns` are local receive
times. Every part's header identifies `capture.version=discovery-v2` and the field order. The old
decoder remains available for research, but is not part of the automatic discovery capture path.

## First parked test

1. With vehicle power removed, confirm the existing pin-swap harness is seated and record its
   version/orientation without changing the wiring.
2. Install the branch and reboot.
3. Turn the vehicle on while safely parked and wait for the normal on-road UI.
4. Press and release one stock cruise button at a time, noting the order and approximate time.
5. Turn the vehicle off and wait for the comma to return off-road.
6. SSH in and run `status`, `list`, and `summary` above.
7. Confirm `discovery-v2`, nonzero physical frame counts, and an inventory of addresses/lengths.
   Record the order and approximate times of presses (several seconds apart); send all compressed
   parts together with those notes. The summary intentionally does not label buttons yet.

Do not perform an active CAN test as part of this checklist. Transmit testing remains separate,
manual, parked-only, and explicitly gated in the standalone research repository.

## Architecture and failure behavior

```text
pandad physical CAN receive stream
              |
              v
 tss3cruiseprobed (subscriber only)
              |
 all physical addresses and lengths
              |
              v
 bounded gzip JSONL archive + RAM status
```

The process is registered with openpilot's `only_onroad` lifecycle and `restart_if_crash=True`.
Messaging or storage failures put only this recorder into bounded retry/backoff; they do not change
stock cruise, openpilot controls, or panda safety. Manager shutdown sends a normal signal and the
recorder finalizes promptly. If it is forcibly interrupted, the `.active` recovery behavior above
preserves the partial evidence.

To stop automatic recording, switch the comma to another openpilot branch or reinstall known-good
software. Existing files under `/data/tss3-cruise-probe/logs` are intentionally preserved so a
software switch does not silently discard the experiment.
