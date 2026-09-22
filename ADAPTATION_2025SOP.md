# 2025sop-tss3 — kaikozlov TSS3 port adapted toward Span's 2025 Corolla Hybrid

**THIS IS THE `2025sop-tss3` VARIANT** (the buildable-intent one): the whole tree is
kaikozlov's `openpilot@tss3` + `panda@tss3-openpilot` + `opendbc@tss3-openpilot`,
with only the opendbc submodule repointed to `spanconstant5/opendbc@2025sop` (his
opendbc + the Span Corolla adaptation). The sibling branch `2025sop` is the same
adaptation on top of your `master` openpilot instead. Caveat 1 below (parent/opendbc
mismatch) does NOT apply to this variant; it is his self-consistent stack.

**Status: SCAFFOLD. Actuation held OFF. Not flash-tested here (no build environment).**
Adds a Corolla platform for Span's car; does **not** make the car steer or brake
(Corolla signer backend not wired). Read every caveat below before building.

## What this branch contains

Base: `kaikozlov/openpilot@tss3` (`179df2fd4`); panda = his `tss3-openpilot`;
opendbc submodule = `spanconstant5/opendbc@2025sop` (see the pinned gitlink).

The `opendbc_repo` submodule **tracks kaikozlov's opendbc directly** (base mismatch
resolved). `.gitmodules` points `opendbc_repo` at `spanconstant5/opendbc`, branch
`2025sop`, which is **kaikozlov/opendbc @ `tss3-openpilot`
(`566ab6b`, "toyota: run TSS3 request plane at 100 Hz")** plus the Span adaptation
commits. The Camry signer transport remains the upstream implementation;
the Corolla changes are confined to its platform scaffold, torque substitute,
and regression coverage.

Span-specific adaptation (the only edits on top of his files):
- `values.py`: added `CAR.TOYOTA_COROLLA_TSS3` platform (specs approximated from
  Corolla TSS2; TSS3 flag; `toyota_tss3_pt_generated` dbc).
- `fingerprints.py`: added the Corolla EPS F181 (`8965F1208000 / 8A3111213000`).
- `interface.py`: Corolla branch that **holds actuation off** — `dashcamOnly=True`,
  `openpilotLongitudinalControl=False`, and the `TSS3_SIGNER`/`TSS3_08A_HOST`
  safety flags **not** asserted (panda blocks `0x08A` TX).
- `torque_data/substitute.toml`: maps the Corolla scaffold to existing Corolla
  TSS2 metadata. This prevents the `card` startup `KeyError` seen in the
  September 22 logs; it is not a measured 2025 lateral limit.

Control modes (as requested): **steering held (dashcamOnly), longitudinal OFF.**

## Passive log evidence for the Corolla signer

The September 22 archive (`logs 9-22-1539.zip`, openpilot `b063d136`) predates
the torque-data fix. `card` identified `TOYOTA_COROLLA_TSS3` with fingerprint
source `fixed`, then crashed before publishing `carParams` or `carState`. The
Panda remained in `elm327`; the archive has no host control traffic. Raw CAN
was recorded, including `0x00F`, `0x0D7`, and `0x08A`, but no native `0x0B6`.
It cannot qualify the EPS signer or prove automatic firmware recognition.

The current branch should now initialize `card` while remaining passive. For
each later local route, `tools/car_porting/corolla_tss3_log_check.py` summarizes
the build commit, fingerprint source, `carParams`/`carState` presence, Panda
safety, and received versus host-sent frames on the relevant buses. It accepts
an rlog, a directory of rlogs, or a ZIP of rlogs and writes JSON with `--output`.
This is an offline reader; it sends nothing to the vehicle. Preserve the full
`rlog.zst` segments for analysis: the summary counts alone cannot establish
freshness, native MAC behavior, signer installation, EPS acceptance, or control.

The next evidence gate is a complete passive route containing valid startup
state and native `0x0B6` traffic alongside `0x00F` and `0x0D7`, with exact bus,
length, timestamp, and payload retained in the rlogs. A stock LTA episode may
be needed for that traffic to appear; the September 22 capture does not show
it. If `0x0B6` is again absent, its route or operating condition remains
unresolved. Do not infer a Corolla signer transport from Camry's `0x08A` stream
or enable `TSS3_SIGNER`/host actuation based on message presence alone.

## CRITICAL CAVEATS — why this is not drivable yet

1. **Runtime compatibility remains unverified.** This branch is based on
   `kaikozlov/openpilot@tss3` with the matching opendbc line; the older
   parent/opendbc base mismatch no longer applies. A successful device build
   and a complete passive `card` startup log are still required. Import checks
   and a torque-table unit test do not establish runtime behavior.

2. **The Corolla signer backend is NOT in this port.** `tss3.py` implements the
   **Camry-native** `0x777` host transport (native-authenticated). Span's Corolla EPS
   uses the **command-5/native-MAC** signer path (EPS-side, installed via the
   `corolla-tss3-signer` helper in `kaikozlov/ghidra_rh850`). The Camry transport will
   **not** produce valid `0x08A` signatures on the Corolla EPS. So even with actuation
   enabled, steering would not work until the Corolla backend is wired.

3. **Braking / longitudinal is not implemented for Corolla.** The current Corolla EPS
   payload "alters only B6 Target Lateral ID and target angle" (lateral only). The
   combined `0x08A` longitudinal fields (`LONGITUDINAL_REQUEST_ACCEL_A`, bytes 8-9,
   verified 0.90 vs measured aEgo) are Camry-demonstrated, not Corolla. `long` stays OFF.

4. **Repin required (hardware).** Actuation needs the panda in-line on the powertrain
   bus (bus0/bus2 relay pair) to suppress the stock producer; as of the 2026-07 capture
   Span had not repinned. A software-only suppression (UDS CommunicationControl) is
   unproven and the longitudinal producer is not yet identified.

5. **Fingerprint is incomplete.** Only the EPS F181 is known; fwdCamera/ABS FW were
   not captured. Auto-fingerprint will not resolve — use a **forced fingerprint**
   (`TOYOTA_COROLLA_TSS3`) until full `carFw` is collected. `EPS_SCALE` defaults to 73
   for this car (unverified for Corolla).

6. **Constants are Camry-derived.** `tss3.py` envelopes were measured on ~44,613 Camry
   `0x08A` publications; the target-angle scale (`1024/17870`) and accel/gain envelopes
   need Corolla-native values before any LIVE use.

## Path to make it real (ordered)

1. Confirm the current opendbc pin, build, and complete passive `card` startup.
2. Repin the harness (caveat 4); capture a relay-correct route to confirm bus map.
3. Install the Corolla EPS signer (`corolla-tss3-signer`, targeting Span's F181
   `8965F1208000 / 8A3111213000` — NOT albino's) and wire a Corolla command-5 backend
   into `tss3.py`.
4. Bring up **steering** first in a true shadow (log would-send vs native), then LIVE.
5. Only then investigate extending the command-5 backend to `0x08A` longitudinal (braking).

## References
- `kaikozlov/openpilot@tss3`, `kaikozlov/opendbc@tss3-openpilot` (`566ab6b`),
  `kaikozlov/opendbc@tss3-sunnypilot`, `kaikozlov/ghidra_rh850`.
- `ghidra_rh850/community/spanconstant/README.md` and
  `docs/variants/corolla-8965F1208000.md` — Span's EPS RE (this car).
