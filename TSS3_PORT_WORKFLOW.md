# TSS3 fork-port workflow

Use this checklist when moving the Toyota TSS3 Corolla work to a new IQPilot
release or another fork. It keeps working stable branches immutable and
separates vehicle/safety code from fork-specific UI and process integration.

## 1. Choose and record the base

1. Start from the source commit corresponding to the fork's latest stable
   release, not its prebuilt-only release commit.
2. Create a new working branch. Never update the public stable branch until all
   offline validation gates below pass.
3. Record the base commit and release in `TSS3_IQPILOT.md` (or the equivalent
   port note for another fork).

For IQPilot, the vehicle port belongs in:

`artifacts/package_sources/iqdbc/iqdbc`

Do not create a second top-level OpenDBC copy.

## 2. Apply changes by ownership

Apply and review these groups independently:

1. **IQDBC vehicle layer:** Toyota platform definitions, firmware fingerprints,
   DBC generators, state/controller/radar interfaces, and signer transport.
2. **IQDBC safety:** TSS3 flags, bus topology, signer request approval,
   CONTROL_REQUEST publication checks, and retained fork-specific Toyota safety
   behavior such as IQPilot AOL.
3. **Panda lifecycle:** startup catcher and cooperative direct-Panda lease. Keep
   multi-Panda behavior from the destination fork.
4. **Fork runtime:** event/alert, manager process, bundled RAM signer kit, and
   parameters.
5. **UI:** Developer-page auto-arm toggle and manual bring-up entry. Keep it
   visible in release builds when that is the branch's intended behavior.

Do not mix optional cosmetics, sounds, unrelated controls tuning, or other fork
features into the port commit.

## 3. Resolve destination-fork differences explicitly

Before copying a whole file, compare the destination version and preserve:

- fork-specific safety flags and RX checks;
- the destination Panda wrapper's flashing and multi-device lifecycle;
- existing settings and navigation controls;
- schema ordinals and parameter-key policies;
- the destination package namespace (`iqpilot`/`iqdbc`, not
  `openpilot`/`opendbc`).

Run `git diff --check` after every group and remove all patch reject files.

## 4. Validation gates

Minimum offline gates before publishing a stable test branch:

1. Generate the Toyota DBCs and compile the safety library.
2. Run the destination's complete Toyota car tests.
3. Run the destination's complete Toyota safety tests; zero regressions are
   allowed.
4. Run signer-kit and direct-Panda lease lifecycle tests.
5. Compile all changed Python and load the Cap'n Proto schemas.
6. Build native pandad on the target architecture when an appropriate build
   environment is available.
7. Review `git diff --check`, `git status`, and the final staged file list.

Record exact results and any unavailable gate in the port note. Never turn an
unavailable native build into a claim of success.

## 5. Publish and test

1. Commit the port as a focused, documented change.
2. Push to a simple branch name (`iq`, `sun`, `op`, etc.).
3. Verify the remote branch hash after pushing.
4. First vehicle test is stationary, with a known-working rollback branch
   available.
5. Confirm fingerprint, CAN validity, signer residency, safety mode/parameter,
   and host `0x08A` routing before any moving test.
6. Promote later updates only after reviewing upstream changes and repeating all
   applicable gates; never silently fast-forward a known-working stable branch.
