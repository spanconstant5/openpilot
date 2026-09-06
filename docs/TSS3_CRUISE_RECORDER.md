# Passive Toyota TSS3 rlog collection

## What this branch does

Install the branch and use the comma normally. It adds **no recorder process**. openpilot's existing
native `loggerd` already records all messages on the cereal `can` service into the route's
`rlog.zst` files. The added SSH helper only finds those files and can analyze them after a test.

This is intentionally different from the earlier Discovery v2 build. That version subscribed to
all CAN traffic in Python, converted each frame to JSON and gzip-compressed another archive while
on-road. It duplicated data already present in rlogs and could put unnecessary load on a comma. The
duplicate daemon, manager registration, JSON archive, rotation code and RAM status file have all
been removed.

The first two narrow captures watched `0x24D` and `0x1D3`. They retained 720 and 800 `0x24D`
records on buses 0 and 2, but showed no button transitions even though the owner pressed the stock
buttons and changed the displayed Toyota set speed. Those recordings are inconclusive. A complete
rlog avoids assuming the address, bus, payload length or decoder before seeing the evidence.

## Safety and resource boundary

- No extra process starts at boot, ignition, or on-road transition.
- No code subscribes to live CAN for this experiment.
- No CAN publisher or `sendcan` path is present.
- No frame is created, replayed, acknowledged, blocked, or modified.
- No panda safety setting, Toyota control code, or stock fallback behavior changes.
- Normal openpilot `loggerd`, uploader and deleter behavior is left intact.
- Analysis runs only when you explicitly invoke `summary`; do that parked and off-road.

The helper cannot prove that the panda can physically see a network behind the harness. It only
reports traffic already received and logged by openpilot. The owner reports that the Toyota pin-swap
is installed; record its version and orientation with each test because software cannot verify it.
Inspect or change harness wiring only with vehicle power removed.

## Install

On the comma Custom Software screen, enter:

```text
spanconstant5/tss3
```

The installer expands that to:

```text
https://installer.comma.ai/spanconstant5/tss3
```

To update an existing checkout over SSH, confirm `git branch --show-current` says `tss3` (an older
installation may still say `tss3-passive-recorder`), then run:

```sh
cd /data/openpilot
git fetch origin tss3
git merge --ff-only FETCH_HEAD
sudo reboot
```

The reboot is important when upgrading from Discovery v2 because it guarantees the removed Python
recorder is no longer running.

## Run a parked button test

1. Park safely. Do not combine this passive collection with a transmit experiment.
2. Start the car and let comma reach its normal on-road screen.
3. Note the wall-clock start time.
4. Press and release one stock cruise button at a time, five times each, several seconds apart.
5. Say the button name aloud or write down the button order and approximate times.
6. Include changes made by both short presses and press-and-hold, but do not create a traffic hazard.
7. End the drive and wait for comma to return fully off-road before inspecting the logs.

Use at least two independent test drives before treating a signal assignment as repeatable. Capture
variation can come from route segmentation, startup timing, vehicle state, wiring, dropped traffic,
or a signal that uses a counter/checksum alongside the actual button bits.

## Find the files over SSH

After the drive is over:

```sh
cd /data/openpilot
python -m openpilot.system.tss3_cruise_recorder.control status
python -m openpilot.system.tss3_cruise_recorder.control list --latest 3
```

The normal log root is `/data/media/0/realdata`. Each drive is split into roughly one-minute route
directories, and each directory has its own `rlog.zst`. Copy **every segment from the test route**.
Do not substitute `qlog.zst`: qlogs contain only a heavily decimated CAN subset.

For a clean, one-path-per-line list:

```sh
python -m openpilot.system.tss3_cruise_recorder.control list --latest 1 --paths-only
```

From the computer, copy each printed path with `scp`. For example:

```sh
scp "comma@DEVICE_IP:/data/media/0/realdata/ROUTE--*/rlog.zst" ./tss3-test-1/
```

Replace `DEVICE_IP` and `ROUTE` with the values printed by the helper. Quoting keeps wildcard
expansion on the comma. If that `scp` client does not accept the wildcard, copy the printed paths
one at a time. Retrieve the route promptly: openpilot's normal uploader/deleter may eventually move
or remove local segments. This branch does not pin logs or change retention policy.

## Optional off-road inventory

The full rlogs are the primary evidence. You can also generate an initial inventory on the comma,
but only after the drive while parked/off-road:

```sh
cd /data/openpilot
python -m openpilot.system.tss3_cruise_recorder.control summary --latest 1 --top 50
python -m openpilot.system.tss3_cruise_recorder.control summary --latest 1 --json /data/tss3-can-inventory.json
```

`summary` reads the selected rlogs once and reports each physical bus/address/length stream, frame
count, number of payload transitions, bounded distinct-payload count, and a bit-change mask. It
ignores panda TX receipts (`src >= 0x80`). The distinct-payload set is capped at 256 per stream so
the manual analyzer's memory use remains bounded. A trailing `+` means the cap was reached.

The inventory does not identify a button by itself. Normal counters, checksums, wheel speed and many
other signals change frequently. Correlation requires the press order/times and preferably a quiet
parked control period. Preserve the raw rlogs even if you also send the JSON inventory.

## Architecture

```text
pandad -> cereal can -> native loggerd -> existing rlog.zst
                                           |
                                  SSH list/copy helper
                                           |
                          optional manual off-road summary
```

There is no experiment-specific component in the live path. Switching to another branch leaves no
background service to disable. Old `/data/tss3-cruise-probe/logs` JSONL files from Discovery v2 are
not deleted automatically; they can be copied or removed later by the owner.

## Privacy and limitations

Rlogs contain much more than cruise-button traffic, including vehicle state, location and device
information. Treat them as sensitive and share them only with people you trust. This tooling is an
unvalidated research aid, not proof that a message is safe to transmit and not authorization to
weaken panda safety. Any later active test must remain separate, explicitly armed, parked-only and
within existing panda safety limits, with stock behavior as the fallback.
