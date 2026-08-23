# Upstream provenance

The probe primitives and RH850 payload are loaded from the
[lochuan/eps-telescope](https://github.com/lochuan/eps-telescope) Git submodule
in `upstream/`. The exact upstream commit is pinned by this repository.

The comma integration adds:

- a touchscreen settings panel;
- a manager-owned Panda handoff with automatic recovery;
- stationary, Park, and disengagement gates;
- safer mode separation so UDS and Security modes never enter the programming
  session;
- a pinned payload digest check; and
- on-device report storage and summaries.

The upstream repository did not contain a license file when checked on
2026-08-23. Its files are therefore not copied into this repository; the Git
submodule links to and checks out the original repository directly. Preserve
this provenance notice and obtain the author's permission before copying or
redistributing those files separately.
