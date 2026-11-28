# Signer Start

Signer Start is a clean openpilot research build for beginning a RAM-resident signer investigation on a new vehicle. It is deliberately independent of SunnyPilot, StarPilot, IQPilot, and existing vehicle-specific signer ports.

Install on a comma with:

```text
installer.comma.ai/spanconstant5/start
```

## Capture workflow

1. Install the build and complete normal openpilot setup.
2. With the vehicle off and openpilot disengaged, open **Settings → Developer → Signer Start Research Capture**.
3. Press **START**, then start the vehicle while it remains parked. The tool waits up to three minutes for CAN traffic.
4. Leave the vehicle on and parked for the 60-second capture. The button shows progress if the Developer page is open.
5. After it displays **SAVED**, retrieve the newest ZIP from `/data/signer-start/` using SSH or Cyberduck. The `LATEST` text file names the corresponding unpacked directory.

The same capture can be started over SSH:

```sh
cd /data/openpilot
python3 -m openpilot.selfdrive.car.signer_start
```

## What the package contains

Every package puts the topology result first in both `report.md` and `report.json`. It includes:

- CAN0/CAN2 separation, overlap, traffic rates, validated marker evidence, and a topology PASS/BLOCK gate;
- a timestamped raw receive-only CAN stream in `can_capture.jsonl`;
- exact/fuzzy fingerprint state, VIN, network location, safety configuration, and longitudinal flags;
- cached ECU firmware responses, including EPS firmware when available;
- openpilot, Panda, branch, commit, and device metadata;
- raw cached `CarParams` blobs and recent qlog/rlog route references;
- a manifest with file sizes and SHA-256 hashes;
- an explicit list of information still requiring authorized vehicle-specific bench work.

The current validated topology profile is Toyota/Lexus TSS3. Other makes still receive the full capture, but the topology gate reports `profile_needed` rather than guessing bus roles. A new profile should only be added after comparing known physical sides and control captures.

## Safety and privacy boundary

Signer Start does not send CAN, enter diagnostic sessions, attempt SecurityAccess, read ECU memory, write RAM/flash, or inject code. It is an extractor for passive discovery evidence, not a universal signer loader.

The ZIP contains a VIN, device identifiers, and raw vehicle traffic. Keep it private unless you deliberately choose to share it with a researcher.

A topology PASS means only that observed CAN0/CAN2 roles match comma harness convention: CAN0 is the car/chassis side and CAN2 is the camera/ADAS side. It is necessary but not sufficient for later signer work, and physical continuity should still be verified.
