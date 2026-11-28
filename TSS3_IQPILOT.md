# IQPilot Toyota TSS3 test branch

This branch carries the Toyota TSS3 Corolla port and its RAM-resident SecOC
signer bring-up support on IQPilot. It is based on the source commit that backs
the IQPilot 1.0c stable release, rather than an IQPilot nightly.

The public `iq` branch is published as a source snapshot because the upstream
history references two private Git LFS IQVD model objects that cannot be copied
to the public fork. Those two model files are omitted from the snapshot;
IQPilot 1.0c already keeps the IQVD process disabled, so this does not remove an
active driving or UI feature from this release.

## Layout

- Vehicle definitions, DBCs, controller/state integration, and Panda safety
  live under `artifacts/package_sources/iqdbc/iqdbc`, as requested by the
  IQPilot developers.
- The signer lifecycle, bundled signer kit, alerts, and Developer UI live in
  `iqpilot`.
- The Developer-page bring-up control remains visible on release builds. The
  bundled kit means no separate Cyberduck/SSH installation is required.

## Installation

Once the branch has been pushed, install from:

`installer.comma.ai/spanconstant5/iq`

Use this only as a later test build. The IQPilot integration has static and unit
test coverage, but it has not yet been validated in the vehicle. Keep the
known-working stable build available for rollback and perform the first test
stationary.

## Validation recorded for this port

- IQDBC Toyota car tests: 11 passed, 210 subtests passed.
- IQDBC existing Toyota safety suite: 833 passed, 885 subtests passed.
- IQPilot signer-kit tests: 8 passed, 5 subtests passed.
- Panda direct-lease lifecycle tests: 3 passed.
- Python sources compile successfully. A complete IQPilot hardware build was
  not available in the x86 development environment.

The carried TSS3 safety implementation also passed 63 focused tests (with 8
expected skips) from the newer port suite after adapting the harness to
IQPilot's older safety test framework. Five measurement/config assertions in
that borrowed suite are framework/DBC-version mismatches and are not claimed as
passing IQPilot tests.

## Historical milestone

openpilot first became operational on this car at approximately 3,400 miles on
the comma device and 21,100 miles on the vehicle. This note is historical and
does not imply that this IQPilot branch has been road-tested.
