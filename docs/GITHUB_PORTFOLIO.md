# spanconstant5 openpilot and Toyota TSS3 project index

Last reviewed: 2026-11-22 (America/New_York)

This is the single starting point for the active builds, the comma 4 desktop
visualizer, and the Toyota TSS3 research and firmware work. Branches described
as archived were converted to dated Git tags before their branch names were
removed, so the commits and documentation remain recoverable.

## Installable builds

All installable builds live in
[`spanconstant5/openpilot`](https://github.com/spanconstant5/openpilot). Use a
fresh comma custom-software install and enter the URL shown below.

| Branch | Install URL | State | Upstream status on 2026-11-22 |
|---|---|---|---|
| [`sun`](https://github.com/spanconstant5/openpilot/tree/sun) | `installer.comma.ai/spanconstant5/sun` | Primary build; the Corolla TSS3 signer, ICBM support, Device-settings bringup shortcut, takeover handling, and speed-sign observation logger are present. The pre-refresh in-car-working tip is preserved as `archive/2026-11-22/sun-pre-refresh`. | Rebased onto sunnypilot `d48439aa3e`; 0 commits behind at review time. |
| [`op`](https://github.com/spanconstant5/openpilot/tree/op) | `installer.comma.ai/spanconstant5/op` | Stock-openpilot variant with the Corolla signer integration. Preserve as the known working baseline until the Panda startup-catcher changes are ported and retested. | Based on comma openpilot `4e79724ac1`; a refresh to `af90646a4` was reviewed but not published because it conflicts in the safety-critical Panda path. |
| [`star`](https://github.com/spanconstant5/openpilot/tree/star) | `installer.comma.ai/spanconstant5/star` | StarPilot/Galaxy research build. It contains later Corolla work, but previous in-car testing reported a harness warning; treat it as unvalidated. | StarPilot migrated its active channel/history. This branch has not been rebased across that migration. |
| [`frog`](https://github.com/spanconstant5/openpilot/tree/frog) | `installer.comma.ai/spanconstant5/frog` | Legacy FrogPilot experiment. Previous in-car testing did not complete bringup; do not treat it as the primary build. | FrogPilot force-rewrote its upstream history and no longer shares a merge base with this branch. Exact tip preserved as `archive/2026-11-22/frog-legacy`. |

The `master` branch is retained as a comparison baseline. The historical
`spangpt` default remains available only because changing GitHub's default
branch requires repository-settings access; it is not the recommended build.

## Supporting code

- [`spanconstant5/opendbc`](https://github.com/spanconstant5/opendbc) contains
  the build-specific vehicle, DBC, and Panda-safety changes. Its intentionally
  retained branches are `sun`, `op`, `star2025-kai-clean`,
  `corolla-tss3-signer-icbm`, `2025sop`, `toyotabsmhack`, and `master`.
- [`spanconstant5/sunnypilot`](https://github.com/spanconstant5/sunnypilot)
  remains available for upstream pull-request history. Only `master`, `sun`,
  and `corolla-tss3-runtime` remain as branches; installs should use the
  consolidated `spanconstant5/openpilot: sun` branch above.

## User-facing tools

- [`comma4-visualizer`](https://github.com/spanconstant5/comma4-visualizer) is
  the standalone Windows-friendly route replay and export application. Its
  README contains GUI use, build, privacy, performance, and export guidance.

## Research and firmware

- [`2025fwpatch`](https://github.com/spanconstant5/2025fwpatch) — fail-closed
  EPS firmware probing, patching, restoration, identity checks, and retained
  offline evidence.
- [`tss3-corolla-research`](https://github.com/spanconstant5/tss3-corolla-research)
  — the long-form Corolla SecOC signer research record. Treat historical bus
  topology statements as observations tied to their capture dates; the
  physical harness and relay investigation continued afterward.
- [`toyota-tss3-cruise-probe`](https://github.com/spanconstant5/toyota-tss3-cruise-probe)
  — shadow-first cruise-message research.
- [`toyota-tss3-nag-probe`](https://github.com/spanconstant5/toyota-tss3-nag-probe)
  — passive stock steering-nag capture tooling.
- [`toyota-tss3-dm-bridge`](https://github.com/spanconstant5/toyota-tss3-dm-bridge)
  — experimental driver-monitoring bridge, shadow-only by default.
- [`2025corolla-starpilot`](https://github.com/spanconstant5/2025corolla-starpilot)
  — historical StarPilot development repository. The consolidated `star`
  branch in `spanconstant5/openpilot` supersedes it for installs.

## What was archived

On 2026-11-22:

- 29 stale branches in `spanconstant5/openpilot` were converted to tags under
  `archive/branches/2026-11-22/` and then deleted.
- 68 remaining non-project branches in `spanconstant5/sunnypilot` were tagged
  under the same namespace and deleted. An additional 173 branches that were
  exact copies of sunnypilot upstream were deleted without tags because their
  source refs are still available upstream.
- 16 remaining non-project branches in `spanconstant5/opendbc` were tagged and
  deleted. An additional 162 exact copies of sunnypilot/OpenDBC upstream were
  deleted without tags.
- GitHub branch protection prevented deletion of
  `feature/dashcam-telemetry-v1` and `tskdash` in `spanconstant5/openpilot`.
  Both tips were archived as tags first. They can be removed after their branch
  protection rules are disabled.

No repository or documentation was permanently deleted by this cleanup.

## Restore an archived branch

For a branch that was converted to a tag:

```bash
git fetch origin --tags
git push origin \
  refs/tags/archive/branches/2026-11-22/BRANCH_NAME:refs/heads/BRANCH_NAME
```

For a build-level safety tag, substitute one of these tag names:

- `archive/2026-11-22/op-pre-refresh`
- `archive/2026-11-22/sun-pre-refresh`
- `archive/2026-11-22/star-pre-refresh`
- `archive/2026-11-22/frog-legacy`

For an exact upstream mirror that was removed without a tag, fetch or recreate
the branch from the corresponding upstream repository. The cleanup compared
both the branch name and commit hash before classifying a branch as an exact
mirror.

## Maintenance rule

Keep public branch names short and purposeful:

- `sun`, `op`, `star`, and `frog` for installable build lines;
- `master` for the upstream comparison line;
- narrowly named branches only for an active pull request or experiment.

Before deleting any future branch, create an `archive/branches/YYYY-MM-DD/...`
tag unless the branch is an exact upstream mirror. Update this page whenever a
build is validated in-car or its upstream base changes.
