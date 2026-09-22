# 2025sop — kaikozlov TSS3 port adapted toward Span's 2025 Corolla Hybrid

**Status: SCAFFOLD. Not buildable/flashable as-is, not drivable. Actuation held OFF.**
This branch vendors kaikozlov's latest TSS3 openpilot port and adds a Corolla
platform for Span's car so the code loads and can be reviewed/extended. It does
**not** make the car steer or brake. Read every caveat below before building.

## What this branch contains

Base: `origin/master` (openpilot), opendbc submodule at commaai `44c977f`.

Vendored from **kaikozlov/opendbc @ `tss3-openpilot` (`566ab6b`, "toyota: run TSS3
request plane at 100 Hz")** into `opendbc_repo/opendbc/`:
- `car/toyota/` — `carcontroller.py`, `carstate.py`, `toyotacan.py`, `values.py`,
  `interface.py`, `fingerprints.py`, `radar_interface.py`, `tss3.py`, `__init__.py`
- `car/secoc.py`
- `safety/modes/toyota.h`  (his newer path; see caveat 1)
- `dbc/generator/toyota/toyota_tss3_pt.dbc`

Span-specific adaptation (the only edits on top of his files):
- `values.py`: added `CAR.TOYOTA_COROLLA_TSS3` platform (specs approximated from
  Corolla TSS2; TSS3 flag; `toyota_tss3_pt_generated` dbc).
- `fingerprints.py`: added the Corolla EPS F181 (`8965F1208000 / 8A3111213000`).
- `interface.py`: Corolla branch that **holds actuation off** — `dashcamOnly=True`,
  `openpilotLongitudinalControl=False`, and the `TSS3_SIGNER`/`TSS3_08A_HOST`
  safety flags **not** asserted (panda blocks `0x08A` TX).

Control modes (as requested): **steering held (dashcamOnly), longitudinal OFF.**

## CRITICAL CAVEATS — why this is not drivable yet

1. **opendbc base mismatch (build blocker).** His port targets a *newer* opendbc
   than master `44c977f`. Evidence: his safety lives at `opendbc/safety/modes/toyota.h`,
   which master's opendbc does not have (safety hadn't moved into opendbc yet).
   Python files pass `py_compile`, but **import/link compatibility against master's
   opendbc core and the openpilot build was NOT verified** (no build was possible in
   this environment). To actually build, either bump the opendbc submodule to a base
   near his, or track `kaikozlov/opendbc@tss3-openpilot` wholesale.

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
