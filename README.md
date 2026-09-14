# 2025 Corolla Hybrid — StarPilot TSS 3.0 port

[![Corolla TSS3 checks](https://github.com/spanconstant5/openpilot/actions/workflows/corolla-tss3-ci.yml/badge.svg?branch=spangpt)](https://github.com/spanconstant5/openpilot/actions/workflows/corolla-tss3-ci.yml)

This repository is a StarPilot-based openpilot build for one target: the
Span/`spanconstant5` 2025 Toyota Corolla Hybrid with Toyota Safety Sense 3.0.
It carries the supplied Corolla control work into StarPilot while preserving
the narrow Panda transmit allowlist and the evidence boundaries around the
vehicle.

The branch is ready for code review and offline testing. It has **not** been
independently driven or replayed here against the author's route files, because
those files were not included in `Corolla_Fingerprint_v1.zip`. The source notes
report working longitudinal control on route 24 and working lateral control on
route 28. Those remain source-artifact results rather than new verification by
this repository.

## Current status

| Area | Status | Basis |
|---|---|---|
| 2025 EPS identity | Verified | F181 `8965F1208000` + `8A3111213000`, serial `8965012N50E12H030731`, MCU `R7F701383` |
| EPS application transfer | Verified offline | The analyzed 2025 and 2023 high application regions are byte-identical from `0x17E00` upward |
| Longitudinal command | Implemented | Camera-origin 32-byte `0x160`, supplied route-24 result |
| Lateral command | Implemented | Steering request in `0x160` bytes 22–23 at 537.7 counts/degree, supplied route-28 result |
| E2E protection | Implemented and tested | Counter plus CRC-16/CCITT with data ID `0x444A` |
| Panda safety | Debug-gated and tested | Only 32-byte `0x160` on bus 0 is accepted in TSS3 mode |
| Vehicle identification | Manual path implemented | Saved `TOYOTA_COROLLA_TSS3` selection is refreshed before interface startup; automatic CAN matching remains blocked by the Corolla/Camry census overlap |
| Vehicle-specific tuning | Unresolved | Exact 2025 mass, steering ratio calibration, and driver-override threshold are not proved |

## Use the manual vehicle selection

Until a complete, unique fingerprint is available, select:

```text
Toyota Corolla Hybrid 2025 (TSS 3.0)
```

in StarPilot's vehicle settings and enable **Disable Fingerprinting**. This uses
StarPilot's existing `CarModel` override. The port does not add a partial
fingerprint that could silently identify another Toyota as this car.

The startup path reads both `ForceFingerprint` and `CarModel` directly from
persistent parameters before selecting the vehicle interface. This avoids a
stale previous-route `MOCK` snapshot sending a valid manual selection into
dashcam mode.

## Install `spangpt`

On a freshly reset comma device, choose **Custom Software** and enter:

```text
installer.comma.ai/spanconstant5/spangpt
```

The installable source is the
[`spangpt` branch of `spanconstant5/openpilot`](https://github.com/spanconstant5/openpilot/tree/spangpt).
The comma installer resolves custom branches from a repository named
`openpilot`. GitHub also permits only one fork per account within this shared
openpilot/FrogPilot/StarPilot fork network, and `spanconstant5/openpilot` is the
existing account fork. This branch is based directly on StarPilot commit
`ac3fb6a4d889bb0e43373d602ad80ac349ecb81c`.

Automatic matching cannot be enabled from this car's logs alone. Full `rlog`
segments are still useful for building and checking a review candidate; a
`qlog` is too sparse. Generate the candidate offline with:

```bash
PYTHONPATH=.:opendbc_repo python tools/corolla_tss3_fingerprint.py \
  route-a--0--rlog.zst route-a--1--rlog.zst --bus 0
```

The tool unions every address below `0x800`, rejects changing DLCs, rejects
short captures, and reports whether the last segment still adds addresses. It
prints a candidate; it does not modify `fingerprints.py`. Add a candidate only
after it has converged and is distinguishable from other supported platforms.

The two supplied full rlogs now converge, but comparison against the retained
Camry TSS3 evidence proves that convergence is not uniqueness. The resulting
CAN sets remain census evidence and must not be registered as FPv1. The exact
identity decision and the remaining automatic-selection path are documented in
[docs/COROLLA_2025_FINGERPRINT.md](docs/COROLLA_2025_FINGERPRINT.md).

## What changed

The port adds `TOYOTA_COROLLA_TSS3`, a dedicated CAN FD DBC, target-specific
CarState parsing, 0x160 E2E handling, the controller substitution, and a Panda
safety mode. The controller:

- sends at most once for each new camera counter;
- changes only the known acceleration and steering fields;
- preserves the camera's unknown bytes and whichever axis openpilot is not
  controlling;
- recomputes the counter and E2E checksum;
- never transmits the older gateway-origin `0x1A0` path.

The detailed field map, evidence pins, and implementation boundaries are in
[docs/COROLLA_2025_TSS3_PORT.md](docs/COROLLA_2025_TSS3_PORT.md).

## Safety boundaries

The experimental TSS3 Panda mode is available only when Panda is built with
`ALLOW_DEBUG`. Its transmit allowlist contains one command: a 32-byte `0x160`
on bus 0. Legacy 8-byte `0x160`, `0x1A0`, older Toyota steering messages, and
all unrelated addresses remain blocked.

Panda limits acceleration to the observed stock relay envelope of
`-3.5..2.0 m/s²`; the controller currently clamps its substituted request to
`-1.5..1.5 m/s²`. Steering may change by at most 1,500 counts per accepted
camera frame. A rejected command does not advance the rate-limit baseline.
Panda also enforces the controller's 55-degree absolute request bound and
rejects nonzero steering whenever controls are disengaged.

A production Panda build does not enable this experimental safety allowlist and
will reject the controller's 0x160 output. That is intentional until the
remaining vehicle-level policy and validation work is complete.

## Known vehicle behavior

- The supplied notes report both lateral and longitudinal control working.
- Turn signals were absent from the three tapped buses, so they cannot currently
  cancel the `Turn exceeds limit` condition through a proved signal.
- The Toyota hands-on-wheel warning appears to be enforced by a torque timeout.
  No verified CAN suppression was found; hands-on use remains required.
- The physical driver-torque signal is known on `0x030`, but an acceptable
  driver-override threshold has not been dynamically validated, so the port does
  not invent one.
- The platform currently inherits the established E210 Corolla values of
  3,060 lb, 2.67 m wheelbase, and 13.9 steering ratio. Exact values for this
  specimen remain to be confirmed together.

## Offline checks

The focused GitHub workflow builds the Panda safety test library and runs the
Corolla controller, Panda safety, and fingerprint-tool tests. Locally, with the
project dependencies available:

```bash
export PYTHONPATH="$PWD:$PWD/opendbc_repo"
export ALLOW_DEBUG=1
python -m compileall -q opendbc_repo/opendbc/car/toyota
scons -C opendbc_repo/opendbc/safety/tests -D -j2
pytest -q opendbc_repo/opendbc/car/toyota/tests/test_tss3.py
pytest -q opendbc_repo/opendbc/safety/tests/test_toyota_tss3.py
pytest -q tools/tests/test_corolla_tss3_fingerprint.py tools/tests/test_corolla_tss3_census.py
```

## Related repositories and provenance

- [spanconstant5/2025fwpatch](https://github.com/spanconstant5/2025fwpatch) is
  the separate EPS firmware patch project. The 2026-09-13 retained bundle
  reports a complete exact-identity target write, CRC write, and matching final
  readbacks. That proves the patch transaction, not StarPilot driving behavior.
- [kaikozlov/ghidra_rh850](https://github.com/kaikozlov/ghidra_rh850) is the
  evidence authority for the 2025 EPS identity and application comparison.
- This repository is based on
  [firestar5683/StarPilot](https://github.com/firestar5683/StarPilot) commit
  `ac3fb6a4d889bb0e43373d602ad80ac349ecb81c`.
- The supplied working control implementation originated from a sunnypilot
  port. Its measured behavior and limitations are retained in the port notes.

The original StarPilot project README is preserved at
[docs/STARPILOT_UPSTREAM_README.md](docs/STARPILOT_UPSTREAM_README.md). Existing
license and third-party notice files remain authoritative for inherited code.
