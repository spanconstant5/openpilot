# Known limitations for v0.1.0-alpha.1

- No comma 3, comma 3X, comma 4, or in-vehicle road test has been claimed yet.
- The comma 4 HUD is designed for the current 300x180 `mici` content rect but still needs daylight,
  night, thermal, and touch-interaction checks on real hardware.
- Regular stock TSS throttle and brake command magnitudes are not exposed by the generic CarState
  API. The bars show decoded driver input; Toyota stock AEB can mark Brake as `TSS AEB`. No value is
  invented for ordinary TSS acceleration/braking.
- Toyota hybrid battery charge, EV mode, and power flow are unavailable and therefore hidden.
- RPM and analog throttle/brake live under deprecated CarState fields and may be absent by vehicle.
- `TSS CRUISE ACTIVE` means Toyota's decoded adaptive-cruise state is enabled; it does not claim that
  every TSS feature is active.
- Video association uses the recorder receipt time for the encoder segment. Hardware tests must
  measure any fixed offset and boundary drift.
- Desktop HEVC decoding depends on Qt and the operating system codec backend.
- The importer uses file size for resumable copies, not a cryptographic checksum.
- Telemetry has no automatic retention/deletion policy in v1. Existing openpilot video retention is
  unchanged.
- The recorder adds local writes and CPU work. Its real device resource cost is unmeasured.
- Face orientation/probability and GPS are sensitive. No new driver-camera video is recorded, but
  imported telemetry still requires careful handling.
