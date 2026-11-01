# 2025 Corolla Hybrid — StarPilot TSS 3.0 port

[![Corolla TSS3 checks](https://github.com/spanconstant5/2025corolla-starpilot/actions/workflows/corolla-tss3-ci.yml/badge.svg)](https://github.com/spanconstant5/2025corolla-starpilot/actions/workflows/corolla-tss3-ci.yml)

This repository is a StarPilot-based openpilot build for one target: the
Span/`spanconstant5` 2025 Toyota Corolla Hybrid with Toyota Safety Sense 3.0.
It carries the supplied Corolla control work into StarPilot while preserving
the narrow Panda transmit allowlist and the evidence boundaries around the
vehicle.

The RAM-resident signer transport is verified live on the target EPS, but the
current payload repeatedly loses residency within about eight seconds and is now
revoked. A relocated resident must pass stationary validation before this
integration can be road-qualified. Longitudinal control remains deliberately
disabled.

## Current status

| Area | Status | Basis |
|---|---|---|
| 2025 EPS identity | Verified | F181 `8965F1208000` + `8A3111213000`, serial `8965012N50E12H030731`, MCU `R7F701383` |
| EPS application transfer | Verified offline | The analyzed 2025 and 2023 high application regions are byte-identical from `0x17E00` upward |
| RAM-resident signer | Relocation required | Payload SHA-256 `72ffc3eebbec7966177c700a12e3d132f4a5bd03682e61f266bfea62815f8122` answers correctly but lost residency 7.846 and 8.091 s after install in consecutive captures; StarPilot rejects this hash. |
| Signer transport | Verified live | Four classic `0x777` frames and `0x7A9` response on Panda bus 0 |
| 100 Hz benchmark | Qualified with loss handling | 100 sent, 95 responses, 94.343 Hz effective, 25.366 ms maximum latency, max 7 outstanding; five isolated responses were dropped during high Panda RX-buffer overflow |
| Lateral command | Integrated, offline-tested | Signed host `0x08A`, Corolla 55-degree cap, 100 Hz scheduler and 90 ms signer watchdog |
| Longitudinal command | Disabled | Host application is constrained to zero acceleration pending separate Corolla validation |
| Panda safety | Debug-gated and tested | Exact Corolla signer carrier, admin, and signed-`0x08A` envelopes only |
| Automatic vehicle identification | Unresolved | Available moving traces are not uniquely joined to the 2025 F181 identity |
| Vehicle-specific tuning | Unresolved | Exact 2025 mass, steering ratio calibration, and driver-override threshold are not proved |

## Use the manual vehicle selection

Until a complete, unique fingerprint is available, select:

```text
Toyota Corolla Hybrid 2025 (TSS 3.0)
```

in StarPilot's vehicle settings and enable **Disable Fingerprinting**. This uses
StarPilot's existing `CarModel` override. The port does not add a partial
fingerprint that could silently identify another Toyota as this car.

## Reinstall the volatile signer on the comma

The verified request-signer kit must remain at `/data/tss3-oracle`. After a
full vehicle power cycle, turn the vehicle on, leave it in Park with the wheels
straight, and open:

```text
C3/C3X: StarPilot > Vehicle Settings > Corolla RAM Signer > INSTALL
C4:     Settings > Vehicle > Corolla RAM Signer > slide to install
```

The action is shown only for the manually selected Corolla TSS3 platform and
is enabled only while the car is on, stationary, in Park, and disengaged. It
verifies the exact Corolla target, host-runtime hash, authenticated-payload
hash, bus-0 request/response profile, and the installer's live-probe verdict.
It then cycles openpilot controls so Panda leaves diagnostic mode and reapplies
the Corolla safety configuration. The full JSON and terminal log are retained
under `/data/tss3-oracle-runs/ui-*`.

The equivalent SSH fallback remains:

```bash
cd /data/tss3-oracle
./tss3-request-signer doctor
./tss3-request-signer install /tmp/request-signer-install.json
cd /data/openpilot
python3 -c 'from openpilot.common.params import Params; Params().put_bool("OnroadCycleRequested", True)'
```

Wait for openpilot to cycle back onroad before testing; this last command makes
`pandad` leave diagnostic mode and reapply the Corolla safety configuration.

Do not drive or power the vehicle off during either install path. This loads
volatile EPS RAM only; it does not write persistent EPS firmware.

Automatic matching needs several full `rlog` segments from this exact car,
covering startup, standstill, forward driving, reverse, turn signals, doors,
braking, cruise transitions, and other infrequent messages. A `qlog` is too
sparse. Generate a review candidate offline with:

```bash
PYTHONPATH=.:opendbc_repo python tools/corolla_tss3_fingerprint.py \
  route-a--0--rlog.zst route-a--1--rlog.zst --bus 0
```

The tool unions every address below `0x800`, rejects changing DLCs, rejects
short captures, and reports whether the last segment still adds addresses. It
prints a candidate; it does not modify `fingerprints.py`. Add a candidate only
after it has converged and is distinguishable from other supported platforms.

## What changed

The port adds `TOYOTA_COROLLA_TSS3`, target-specific state parsing, the unified
TSS3 host-application DBC, a pipelined signer transport, and a Corolla-specific
Panda safety mode. The controller:

- builds the complete 28-byte host application at normal 100 Hz control cadence;
- sends it through four classic `0x777` frames on bus 0;
- matches the EPS `0x7A9` response by sequence and appends `FV4||MAC28`;
- publishes the resulting 32-byte signed `0x08A` on bus 0;
- supersedes a missing response when a later signer sequence arrives, without
  replaying stale actuator state;
- releases replacement ownership on disable, CAN invalidity, signer failure,
  or watchdog expiry.

The detailed field map, evidence pins, and implementation boundaries are in
[docs/COROLLA_2025_TSS3_PORT.md](docs/COROLLA_2025_TSS3_PORT.md).

## Safety boundaries

The experimental TSS3 Panda mode is available only when Panda is built with
`ALLOW_DEBUG`. Its transmit allowlist contains the exact eight-byte signer admin
and four-frame `0x777` request carrier on bus 0, plus 32-byte signed `0x08A`
on bus 0. Legacy `0x160`, `0x1A0`, older Toyota steering messages, and unrelated
addresses remain blocked.

Panda validates the complete host-application shape, requires zero acceleration
in both request fields, gates active lateral requests on controls state, limits
the Corolla request to 55 degrees, and applies angle-command rate checks using
the E210 wheelbase and steering ratio. Native `0x08A` forwarding resumes if host
publication disappears for 100 ms.

A production Panda build does not enable this experimental safety allowlist and
will reject the signer transport and host `0x08A`. That is intentional until the
remaining vehicle-level policy and validation work is complete.

## Known vehicle behavior

- Earlier source notes report both lateral and longitudinal control through the
  superseded camera-`0x160` experiment; this branch does not enable that path.
- The 100 Hz benchmark lost sequences 3, 20, 55, 80, and 91 while later replies
  continued. Its install log also reported `rx_buffer_overflow: 1733`, so Panda
  receive pressure remains a metric to investigate even though the bounded
  runtime pipeline tolerates isolated response loss.
- The shared DBC decodes retained turn-signal traffic, but its behavior still
  needs dynamic validation on this car before it is treated as authoritative.
- The Toyota hands-on-wheel warning appears to be enforced by a torque timeout.
  No verified CAN suppression was found; hands-on use remains required.
- The combined driver-torque signal on `0x030` is decoded. Its current 0.6 Nm
  steering-pressed threshold is inherited from the TSS3 integration and still
  needs dynamic Corolla validation.
- The platform uses the US-sedan E210 values of 3,060 lb, 2.70 m wheelbase,
  and 13.9 steering ratio. The wheelbase is corroborated by the 2023 US-built
  Corolla SE research package; the exact steering ratio still needs direct
  validation on the 2025 Hybrid.

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
pytest -q opendbc_repo/opendbc/car/toyota/tests/test_tss3_corolla.py
pytest -q opendbc_repo/opendbc/car/toyota/tests/test_tss3_transport.py
pytest -q opendbc_repo/opendbc/safety/tests/test_toyota_tss3.py
pytest -q tools/tests/test_corolla_tss3_fingerprint.py tools/tests/test_corolla_tss3_census.py
```

## Related repositories and provenance

- [spanconstant5/2025fwpatch](https://github.com/spanconstant5/2025fwpatch) is
  the separate EPS firmware patch project. Its 2025 dump verifier is complete,
  but its runtime flasher remains blocked for the 2025 secondary F181 until the
  retained payload and route are proved on that target.
- [kaikozlov/ghidra_rh850](https://github.com/kaikozlov/ghidra_rh850) is the
  evidence authority for the 2025 EPS identity and application comparison.
- This repository is based on
  [firestar5683/StarPilot](https://github.com/firestar5683/StarPilot) commit
  `823a5d5674ec6635b51dd989884dfbd661f90dc4` (StarPilot branch tip on
  2026-10-23).
- The supplied working control implementation originated from a sunnypilot
  port. Its measured behavior and limitations are retained in the port notes.

The StarPilot README from the port's original `ac3fb6a4` base is preserved at
[docs/STARPILOT_UPSTREAM_README.md](docs/STARPILOT_UPSTREAM_README.md) for
historical comparison. Existing license and third-party notice files remain
authoritative for inherited code.
