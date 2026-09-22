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
opendbc submodule = `spanconstant5/opendbc@2025sop` (`b8a51e27`).

The `opendbc_repo` submodule **tracks kaikozlov's opendbc directly** (base mismatch
resolved). `.gitmodules` points `opendbc_repo` at `spanconstant5/opendbc`, branch
`2025sop` (commit `b8a51e27`), which is **kaikozlov/opendbc @ `tss3-openpilot`
(`566ab6b`, "toyota: run TSS3 request plane at 100 Hz")** plus the Span adaptation
commit. All his files (full toyota port, `car/secoc.py`, `safety/modes/toyota.h`,
`dbc/generator/toyota/toyota_tss3_pt.dbc`) are his originals, unmodified.

Span-specific adaptation (the only edits on top of his files):
- `values.py`: added `CAR.TOYOTA_COROLLA_TSS3` platform (specs approximated from
  Corolla TSS2; TSS3 flag; `toyota_tss3_pt_generated` dbc).
- `fingerprints.py`: added the Corolla EPS F181 (`8965F1208000 / 8A3111213000`).
- `interface.py`: Corolla branch that **holds actuation off** — `dashcamOnly=True`,
  `openpilotLongitudinalControl=False`, and the `TSS3_SIGNER`/`TSS3_08A_HOST`
  safety flags **not** asserted (panda blocks `0x08A` TX).

Control modes (as requested): **steering held (dashcamOnly), longitudinal OFF.**

## CRITICAL CAVEATS — why this is not drivable yet

1. **Parent openpilot ↔ opendbc compatibility (unverified).** The opendbc submodule now
   tracks kaikozlov's opendbc wholesale (his self-consistent base — the earlier master
   mismatch is gone). BUT the *parent* openpilot here is `origin/master`, not kaikozlov's
   `openpilot@tss3`. His opendbc car interface may expect his openpilot changes.
   **No build was possible in this environment**, so import/link against this openpilot
   is unverified. If it doesn't build, base the parent on `kaikozlov/openpilot@tss3` too
   (its opendbc pin is his branch). Python files pass `py_compile`; that is not a build.

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

1. Fix the opendbc base (caveat 1) and get a clean build.
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
