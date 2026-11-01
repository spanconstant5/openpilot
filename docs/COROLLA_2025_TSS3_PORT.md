# 2025 Corolla Hybrid TSS 3.0 signer port

This branch integrates the RAM-resident request signer for the
`spanconstant5` 2025 Corolla Hybrid into StarPilot. It is based on StarPilot
`823a5d5674ec6635b51dd989884dfbd661f90dc4`.

## Live evidence

- Exact EPS F181: `8965F1208000 / 8A3111213000`.
- Revoked resident payload SHA-256:
  `72ffc3eebbec7966177c700a12e3d132f4a5bd03682e61f266bfea62815f8122`.
  It signs correctly but lost residency 7.846 and 8.091 seconds after
  installation in consecutive Corolla captures. StarPilot refuses to install
  that exact payload; only the separately pinned successor candidate is
  accepted.
- Successor candidate payload SHA-256:
  `6234bb5bd496a82fabb32c27b56b3db0f1907b5bf6482e4c19f8835153ff69fc`,
  built from clean `kaikozlov/ghidra_rh850` commit
  `9a7c8a7ec6d0045fdbdb8452cac7d4cf52439e2c`. An independent build produced
  identical payload, runtime sources, debug ELFs, and disassemblies. Exact
  archive, entrypoint, runtime-tree, and toolchain hashes are recorded in
  [`COROLLA_2025_TSS3_SIGNER_KIT.json`](COROLLA_2025_TSS3_SIGNER_KIT.json).
  This is an offline-qualified candidate, not a vehicle-liveness pass.
- Installer verdict: `request_signer_live_probe_pass`.
- Request carrier: four classic eight-byte `0x777` frames on Panda bus 0.
- Response: classic eight-byte `0x7A9` on Panda bus 0, status zero, containing
  `FV4||MAC28`.
- The standalone self-test passed.
- The 100 Hz benchmark sent all 100 requests and received 95 valid responses at
  94.343 effective responses/second. Median response latency was 9.230 ms,
  p95 was 18.657 ms, maximum was 25.366 ms, and no more than seven requests
  were outstanding.
- Missing signer sequences were 3, 20, 55, 80, and 91. Later responses
  continued, so the EPS did not stall and the eight-request pipeline did not
  saturate. The corresponding install log reported `rx_buffer_overflow: 1733`;
  Panda receive pressure is the leading explanation and remains follow-up work.

## Kai baseline reconciliation

The StarPilot port was checked against `kaikozlov/openpilot` branch
`tss3-expand` at openpilot commit
`80b8615c39fd1b99dc90303f33053cab975a22ea` and its opendbc commit
`d8a50afdbe44a2eb55d78b14b6e4f77900dca2fd`. The shared baseline covers the
TSS3 parser/controller, signer-response engagement gate, checksum validation,
and Toyota safety policy. This branch retains its Corolla-specific startup
bridge, bus-2 receive topology, request-plane diagnostics, and narrower Panda
allowlist because those are backed by the later vehicle evidence here.

The Corolla firmware map from that branch is now included. The exact target
EPS `8965F1208000 / 8A3111213000` is confirmed on this car; the accompanying
engine `8A2220212400`, ABS `F152612A5400`, and radar `8821F7801200` values are
Kai's reference set and still need confirmation from this vehicle. Automatic
matching therefore remains provisional. The baseline's live longitudinal
policy was deliberately not imported: both longitudinal fields remain forced
to zero in the interface, controller, and Panda safety layers.

## Runtime path

At each 100 Hz controller tick, StarPilot constructs the complete 28-byte
`TSS3_CONTROL_REQUEST` application. Corolla uses the functional-nibble carrier:

```text
0x80 | sequence.low_nibble   + application[0:7]
0x90 | sequence.high_nibble  + application[7:14]
0xA0 | sequence.low_nibble   + application[14:21]
0xB0 | sequence.high_nibble  + application[21:28]
```

The EPS returns a sequence-matched `0x7A9` response. StarPilot appends its
four-byte security trailer to the original application and publishes the
signed 32-byte `0x08A` on bus 0.

The application's six-bit `REQUEST_SEQUENCE` is the low six bits of the outer
carrier sequence. This preserves the relationship used by the live installer
probe, including across the carrier's 255-to-1 wrap, and makes the first
runtime preflight identical to the known-answer request below.

The transport supports up to eight pending generations and uses a 90 ms
publication deadline. When a later response arrives after an older response
was dropped, the older request is marked superseded so it cannot stall the
queue or replay stale actuator state. Disable, CAN invalidity, explicit signer
failure, or watchdog expiry releases host ownership.

The live known-answer inactive application and carrier are:

```text
application: 0000000880002d4700000000007fff007fff0000c000100032000100
frames:
  810000000880002d
  904700000000007f
  a1ff007fff0000c0
  b000100032000100
```

## Panda ownership during installation

The signer installer uses Kai's cooperative direct-Panda lease protocol. It
writes a live requester PID and unique token to
`/tmp/openpilot-pandad-direct-lease`, then signals the managed Python `pandad`
supervisor with `SIGWINCH`. The supervisor interrupts only its native `pandad`
child and publishes the exact token to
`/tmp/openpilot-pandad-direct-ready` after that child exits. The signer never
steals Panda without this acknowledgement.

When the installer removes its lease, the supervisor clears the ready marker
and restarts native `pandad` without taking the Panda reset/reflash path. A
malformed or stale lease is removed, while an unrequested native-child exit
continues through StarPilot's existing recovery path. The rest of openpilot
and its manager remain running throughout the handoff.

The EPS resident is volatile. The old assembly payload at `0xFEBFF9F0` is
revoked because it repeatedly stopped answering within about eight seconds.
Five retained PE1/self-alias RAM captures across the 2025 and 2023 Corolla
packages show its 656-byte candidate region zero and the surrounding tail
stable, so those captures do not prove an application overwrite or require
relocation. The successor uses Kai's current
self-resolving C implementation and remains a stationary-only candidate until
it crosses the old lifetime boundary on the vehicle. With that exact reviewed
kit installed, when `CarModel` already selects this exact Corolla, `card` starts the
installer-proven inactive `0x777` challenge as soon as live CAN also shows the
mirrored 32-byte native `0x08A` plane on buses 0 and 2. One transport maintains
a single response-paced inactive challenge through CAN-only fingerprinting and
parser warmup; the normal Toyota interface takes over on the first valid
CarState. Successful Corolla responses refill that single challenge at no more
than the 100 Hz controller cadence, matching the only sustained live benchmark.
An unanswered challenge still times out and uses the bounded startup retry
instead of accumulating requests. Fingerprint recovery still requires the
complete live three-bus census. Panda's initial
ELM327 safety mode admits the eight-byte
`0x777` carrier, which contains no active lateral or longitudinal command.
For `TSS3_SIGNER`, native `pandad` disables bus-wide automatic CAN-FD promotion
and selects the format per packet: the eight-byte `0x777` carrier remains
Classical CAN while 32-byte traffic remains CAN-FD. No
phase uses signer admin, publishes host `0x08A`, or takes direct-Panda ownership.

## Guided startup sequence

The settings control runs the kit's `ui-bringup` entry point, not its plain
`install` command. Arm it while the vehicle is fully OFF/not READY and in Park.
Wait until the page reports `armed`, then press the brake and POWER normally.
The backend catches the EPS startup response, requests programming during that
bounded window, installs the volatile resident, checks peer health, and runs a
fresh-signing self-test. The Comma 4 page remains visible across the transition
to READY and reports each validated JSONL stage from the backend.

Closing the page before PROGRAMMING writes the backend's cooperative cancel
marker. After the programming boundary, bringup is allowed to finish instead of
being force-killed mid-handoff. Do not drive until the page reports completion;
a full EPS power loss removes the resident and requires this sequence again.

## Safety boundaries

- Only manually selected `TOYOTA_COROLLA_TSS3` enters this path.
- Longitudinal is disabled. Both acceleration fields in host `0x08A` must be
  zero.
- Panda admits only signer admin and the functional-nibble `0x777` carrier on
  bus 0, plus signed 32-byte `0x08A` on bus 0.
- Panda validates the fixed application envelope, lateral request ID/gain pair,
  active-control state, and requested angle.
- The requested steering-wheel angle is limited to 55 degrees. Safety uses the
  US-sedan E210 2.70 m wheelbase and 13.9 steering ratio with a conservative
  zero-slip model.
- Native `0x08A` forwarding is blocked only while host replacement is active.
  It fails open after 100 ms without a well-shaped host publication.
- The safety mode is available only in builds compiled with `ALLOW_DEBUG`.
  Production Panda builds reject the experimental path.
- The superseded direct camera-`0x160` and gateway-`0x1A0` paths are not in
  the signer-mode transmit allowlist.

## Remaining vehicle work

The ordered evidence gates and post-route analysis command are maintained in
[`COROLLA_2025_TSS3_VALIDATION.md`](COROLLA_2025_TSS3_VALIDATION.md).

- Road-qualify this exact StarPilot integration while stationary first, then
  under controlled driving conditions.
- Repeat the stationary sustained-rate benchmark long enough to cross both the
  ELM327-to-Toyota safety transition and the earlier eight-second signer
  boundary after installing the reviewed successor. The old payload remains
  revoked because it stops responding at that boundary.
- Dynamically validate the 2025 steering calibration and driver-override
  threshold rather than relying indefinitely on inherited E210 geometry.
- Complete an unambiguous fingerprint and standard firmware-query mapping.
- Keep hands-on operation: no verified suppression exists for Toyota's
  torque-timeout warning.

Manual vehicle selection remains required because the retained census overlaps
other TSS3 evidence and does not uniquely bind the moving logs to this F181.

The earlier `Corolla_Fingerprint_v1.zip` package is from a 2023 US-built,
non-hybrid Corolla SE. It is used as corroborating E210-sedan geometry and CAN
topology evidence only. Its superseded camera-`0x160` control path and bus
assignments do not override the live 2025 Hybrid signer observations.
