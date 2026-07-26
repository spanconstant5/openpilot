# Phase 3 Toyota hybrid build

Phase 3 is an unpublished owner-test build for a 2025 Corolla Hybrid. It extends the Phase 2 replay
branch without changing the public `tskdash` Phase 1 road-test branch or its release.

Included:

- compact engine RPM, engine/EV state, and signed hybrid wheel-power display;
- radar-cruise/LTA-specific TSS states that do not label ordinary manual driving active;
- offline route replay plus an explicit OpenStreetMap browser link;
- recorded openpilot model-path ribbon in replay and rendered exports;
- local H.264 MP4 export using FFmpeg;
- a shared cross-platform Python importer/viewer core, with thin OS launch/build branches.

The 2025 Corolla Hybrid is newer than the explicit Corolla coverage documented by this fork's
Toyota support table. All Phase 3 fields therefore fail closed: stale, missing, or inapplicable DBC
signals become unavailable. Hybrid battery SOC is not shown until a real route proves the message
and scaling and that mapping receives tests. This build performs no CAN transmission and makes no
change to openpilot safety or vehicle control.
