# 2025 Corolla Hybrid TSS 3.0 port

This branch ports the measured Corolla TSS 3.0 `0x160` control path to StarPilot.
It is based on StarPilot commit `ac3fb6a4d889bb0e43373d602ad80ac349ecb81c`
and the supplied `Corolla_Fingerprint_v1.zip` artifact (SHA-256
`247ac13d7fd412418cf052e87c98ef15ef50ca6fc91a2741c5c0e2ed4f955fc6`).

## Evidence carried into this branch

- Powertrain is panda bus 1. The relayed ADAS pair is bus 0 and camera bus 2.
- Camera-origin address `0x160` is a 32-byte CAN FD frame at about 40 Hz.
- `0x160` acceleration is the signed 15-bit field in bytes 4-5 at
  `0.001 m/s2/count`.
- `0x160` steering request is signed big-endian bytes 22-23 at
  `537.7 counts/degree`.
- Its keyless AUTOSAR E2E checksum is CRC-16/CCITT over bytes 2-31 plus data ID
  `0x444A` in little-endian order. Bytes 0-1 contain the little-endian CRC and
  byte 2 is the camera counter.
- `0x1A0` is gateway-origin traffic. This branch never transmits it.

The supplied notes report longitudinal validation through route 24, transparent
lateral relay on route 27, and openpilot steering causation and scale validation
on route 28. Those route files are not included here, so this repository records
those as source-artifact claims rather than independently replayed results.

The target-specific EPS evidence comes from `kaikozlov/ghidra_rh850` at
`a747ee291b94ffecbee69cf062aec72b23c4dc8d`: application F181 records
`8965F1208000` and `8A3111213000`, serial `8965012N50E12H030731`, MCU
`R7F701383`, and a byte-identical high application region versus the analyzed
2023 Corolla. This supports transferring the EPS application-code conclusions.
It does not prove that every vehicle-level CAN signal and calibration is identical.

## Fail-closed boundaries

- Only the explicitly selected `TOYOTA_COROLLA_TSS3` platform enters this code.
- The StarPilot vehicle selector supplies the platform because an exact 2025 CAN
  fingerprint and standard on-bus firmware response set are unresolved.
- Panda accepts only a 32-byte `0x160` on bus 0 in TSS3 mode. Legacy 8-byte
  `0x160`, `0x1A0`, Toyota LKA/LTA messages, and other command addresses remain
  outside the allowlist.
- TSS3 Panda mode is compiled only with `ALLOW_DEBUG`. A production safety build
  does not activate the experimental allowlist and therefore rejects the
  controller's `0x160` output.
- Acceleration is limited to the stock relay envelope of `-3.5..2.0 m/s2` in
  Panda; StarPilot's substituted request is additionally clamped to
  `-1.5..1.5 m/s2`.
- Steering changes are capped at 1,500 counts per accepted frame. A rejected
  frame does not advance the rate-limit baseline.
- The controller emits once per new camera counter and preserves every unknown
  camera field. When it is not controlling an axis, it relays that axis's field.

## Unresolved behavior

- The turn signal is absent from the three tapped buses, so the controller cannot
  pause steering from a reliable blinker signal.
- The Toyota hands-on-wheel warning appears torque-timeout enforced; no
  suppressible CAN bit was established. Hands-on operation remains required.
- The four fields in message `0xDA` have not been assigned reliably to driver and
  EPS torque, so `steeringPressed` remains false rather than guessing.
- Exact 2025 vehicle mass, steering tuning, automatic CAN fingerprint, and
  standard diagnostic firmware-query mapping remain unresolved.
- The reported route-24 and route-28 control logs were not part of the archive
  or later rlog supply, so this port has not been independently replay-tested
  against those control sessions.

## Supplied CAN census

Two later user-supplied rlogs were processed offline. The segment-10 raw file is
byte-identical to the decompressed rlog already pinned by `ghidra_rh850` (raw
SHA-256 `98710e8d23a40796718b7be566efc83a569be90ece59b5d7f70377143e38338b`).
Its logical bus 1 contains the tracked 147 address/DLC pairs. The additional
startup rlog expands the union to 152 pairs; processing the segment-10 rlog
second adds no new address. Logical bus 0 contains the stable 22-message ADAS
CAN FD geometry.

The 152-entry union is retained in
`opendbc/car/toyota/tss3_census.py` for parser and review evidence. It is not in
`FINGERPRINTS`: the evidence authority records the Corolla census as overlapping
a TSS3 Camry census, and the moving rlog contains `carParams=MOCK` rather than an
on-route F181 response. Automatic matching would therefore risk an ambiguous or
wrong vehicle identity. Manual StarPilot selection remains the supported path.
