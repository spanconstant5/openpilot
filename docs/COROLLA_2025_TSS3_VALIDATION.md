# Corolla TSS3 validation gates

This is the evidence gate for the exact 2025 US Corolla Hybrid EPS
`8965F1208000 / 8A3111213000`. The retained 2023 US-built non-hybrid SE
package is useful for E210 geometry and topology comparison, but it is not
authority for the 2025 control messages.

## Current result

| Area | State | Evidence / next gate |
|---|---|---|
| RAM signer install | Transport proven; payload revoked | October 30 and 31 installations matched F181 and the pinned payload and passed their first Classical-CAN probes in 12.19 and 14.94 ms. The resident then stopped responding 8.091 and 7.846 s after install, so hash `72ffc3ee…` is rejected pending relocation. |
| Bench peer health | Inconclusive | All eight attempts had clear Brake `0x102D` fault bits and the same 8-byte `0x102F`; Kai's current Camry decoder requires 10 bytes. This is not a confirmed fault and is not a health pass. |
| Signed inactive `0x08A` | Offline/probe proven | Exact 28-byte inactive application and valid trailer are proven. The October 29 route proves native runtime signing but contains no engagement, so it cannot prove host `0x08A` publication. |
| Runtime signer preflight | Resident lifetime failed twice | Exact commit `9d9a220573` produced 382 and 369 valid bus-0 responses under continuous response-paced challenges. The last responses were 8.091 and 7.846 s after install; later Classical-CAN requests remained Panda-accepted with zero rejects. A relocated resident is required. |
| Vehicle receive topology | Route-replay proven | The full-rate Corolla stream is on Panda bus 2. CarState and Panda safety consume it there; the incomplete forwarded bus-0 TX-record stream is not used as a receive source. |
| Fingerprint recovery | Three-bus route proven | When FPv1 is ambiguous, recovery requires explicit Corolla identity authority (stored selection or prior exact EPS signer probe), at least 120 DLC-exact Corolla census matches on each mirrored vehicle plane (buses 0 and 2), no conflicting census DLC, and the complete retained CAN-FD ADAS census on bus 1. Topology alone cannot identify the car. |
| Lateral control | Implemented, road validation pending | Angle command uses the signed `0x08A`; 55-degree wheel-angle bound and measured-angle inactive check are enforced. |
| Longitudinal control | Disabled | Interface, controller, and Panda safety all keep both acceleration fields zero. IDs and limits are not yet accepted as Corolla-live evidence. |

## Automatic evidence

Every guided UI run persists its original artifacts below
`/data/tss3-oracle-runs/ui-bringup-*`. StarPilot also writes
`openpilot-bringup-summary.json`, classifying vehicle health as `healthy`,
`fault`, or `inconclusive` without turning an unsupported diagnostic layout
into a fault.

During normal control, the request transport writes compact lifecycle records
to the route log:

- first successful inactive signer preflight, which gates PCM engagement;
- first valid EPS signer response and latency;
- first Panda-accepted host `0x08A` publication;
- request, response, supersede, publication, acceptance, and rejection totals
  when the request plane releases;
- explicit authority failure reason.

This allows a parking-lot test to finish without live SSH. Preserve and upload
the `rlog.zst` afterward; video files are not needed for this analysis.

The October 23 route pair also established that forwarded stock traffic may be
split between bus 0 RX records and `src=0x80` TX receipts. Before the topology
fix this caused `canBusMissing`, `canError`, and `controlsMismatch`, so normal
control never issued a signer request. Replaying the native bus-2 stream after
the fix produces zero invalid Panda RX checks. A final parser invalid state at
the end of one short log was caused only by the recording ending 157 ms after
its last wheel-speed frame.

The October 26 installer archive contains four successful status-zero live
probes, including a 13.43 ms response immediately before the stationary route.
The route then exposed a deterministic runtime-only mismatch: every one of its
71 complete applications used an application sequence one behind its outer
carrier sequence. The aligned transport starts with the exact installer-proven
sequence-1 carrier and remains aligned through carrier wrap.

The next post-install pair at commit
`0e3b5bf1d21d5efe91b8e5379abb48bcbd14abc3` ruled out sequence alignment as the
remaining cause. Across both logs, Panda accepted all 224 aligned `0x777`
frames forming 56 complete applications, with zero rejected publications and
zero nonzero longitudinal fields, but the EPS returned no `0x7A9`. In the log
that directly followed installation, the first runtime request began 10.296 s
after the successful installer probe: about 4.9 s was spent reaching recovered
fingerprint and another 5.4 s waiting for controls initialization. The vehicle
also moved at up to 1.048 m/s and changed gears, so this pair is diagnostic
evidence and not a stationary validation pass.

The next stationary route at clean commit
`4d8c1700bfc0c57861178b143d3823c3d694b3d4` proved that the controls-startup
bridge ran as designed but still started too late. The car remained in Park at
zero speed. Panda accepted all 28 frames forming seven aligned applications,
with zero rejections, zero sequence mismatches, and zero nonzero longitudinal
fields; the EPS returned no `0x7A9`. The first request began 3.466 s after the
successful installer probe. There were no Panda faults, invalid RX checks, TX
blocks, `canError`, `canBusMissing`, or `controlsMismatch` events.

For the next attempt, a persisted Corolla TSS3 selection still bypasses
VIN/firmware queries that have produced no usable identity on this car, while
final identity still requires the complete three-bus live census. The inactive
transport now starts after `card` observes the mirrored 32-byte native `0x08A`
plane on buses 0 and 2, continues through the fingerprint census, and remains
the sole startup sender while the Corolla parsers warm up. On the first valid
CarState, the normal Toyota interface takes over preflight. Every phase uses the
same byte-exact inactive application. None can arm replacement ownership or
publish host `0x08A`, and both longitudinal fields remain zero.

Two later post-install captures at clean commit
`26b862f9976492775e8faaa9b8012caf62262e0d` began 0.620-0.657 s after separate
successful installer probes. Fingerprint recovery repeatedly selected
`TOYOTA_COROLLA_TSS3`, and Panda accepted the delivered aligned `0x777` frames
with zero rejections, sequence mismatches, or nonzero longitudinal fields.
There was still no `0x7A9` or host `0x08A`. Both captures show why: the helper's
sequence-1 publication was generated before the `sendcan` subscriber was ready
and never reached Panda, while the one-second retry delivered sequence 2 only
at 2.169-2.231 s after install. After recovery, `card` then repeatedly crashed
because its parser path supplies raw CAN tuples while the helper expected
attribute-bearing `CanData` values. The startup-only transport now accepts both
forms and retries an unanswered challenge every 100 ms until the first valid
response. It remains inactive, never emits host `0x08A` or an ownership admin
frame, and returns to the one-second cadence once signer liveness is proved.

The October 26 follow-up at clean commit
`23560df8176e251b9009e47a957aa99e58f78d21` proved those tuple and retry fixes
and isolated the remaining miss to process startup. Two installer runs passed
the exact Corolla F181, payload, and live signer probe in 11.10 ms and 9.19 ms.
The corresponding routes recovered `TOYOTA_COROLLA_TSS3`, entered Toyota safety
without a `card` crash, and recorded 596 accepted `0x777` frames with zero
rejections, application/carrier sequence mismatches, or nonzero longitudinal
fields. Neither route received `0x7A9` or published host `0x08A`. In the fully
stationary Park route, the first accepted runtime request still arrived 1.725 s
after the installer completed; in the second route the first generated
application was dropped during subscriber startup and sequence 2 arrived
1.267 s after install. The second vehicle moved at up to 0.419 m/s and is not a
stationary pass.

The guided UI creates a private, tokenized `/tmp` startup lease before launching
the installer. Manager starts a lightweight card launcher while the car is still
off. It binds the normal `can` and `sendcan` messaging sockets, then explicitly
acknowledges readiness to the UI. The external installer is not launched unless
that exact per-run acknowledgement arrives. Full `card` imports, realtime setup,
fingerprinting, and safety initialization remain strictly on-road. This gives
native pandad's restarted `sendcan` subscriber time to connect to the already
bound publisher without running the controls stack offroad. A failed installer
clears the lease immediately. A proven install retains it until `card` has
identified the exact Corolla, observed valid CAN, and seen the manager's on-road
transition. The ordinary `ControlsReady` path remains solely responsible for
selecting Toyota safety. This does not require NRTD, does not share direct Panda
ownership, and does not relax fingerprint, signer, safety, or longitudinal
gates.

The October 27 installer again passed the exact live signer probe on its first
attempt in 10.31 ms, with four accepted frames and zero rejects. Its following
61.692-second route was stationary in Park and recovered
`TOYOTA_COROLLA_TSS3`; Panda transitioned from ELM327 to Toyota safety param
53321 with no faults. It accepted 312 `0x777` fragments with zero rejects, and
all 75 complete logged applications had aligned carrier/application sequences
and zero in both longitudinal fields. There was no `0x7A9` response or host
`0x08A`. The first accepted runtime fragment arrived 1.115 s after the installer
completed, and the route recorded three startup `controlsMismatch` samples.
Most importantly, `initData` proves this run was still clean commit
`23560df8176e251b9009e47a957aa99e58f78d21`, so it did not exercise the
prewarmed-card change at `e08f46fe6a89f016054011a5dbcd85a4413a55fb`.

Starting with `tss3-openpilot-bringup-summary-v2`, every guided UI archive
records the active openpilot version, commit, branch, remote, dirty state, and
whether this build requested and received acknowledgement from the startup
bridge. This makes deployment provenance available in the small installer
archive instead of requiring a later qlog/rlog to discover that the wrong tree
was installed.

The first button attempt intended to validate
`94f33572becdd635827f4a68ab920ad078c4fb5e` caused the comma device to reboot
before it could write a route. The only new button-time action was starting the
entire heavy `card` process offroad. That design has been removed. The
replacement launcher performs only messaging-socket and token-file
coordination offroad, reports an exact readiness token, and fails closed without
starting the external tool if it is not ready within four seconds. The full
card process cannot start until `IsOnroad` is true. The token file is the single
source of truth because deployed builds use a tracked prebuilt ARM Params module;
adding a source-only Params key otherwise produces `UnknownKeyName` on-device.

The first button attempt on `e92c5cb6cc2142f91235d121307f70a89caf8f50`
confirmed that exact mismatch: the UI contained the failure and displayed
`Could not prepare Corolla signer handoff — UnknownKeyName` before launching the
installer. No vehicle route was expected from that rejected attempt. The next
build removes the bridge key from Params completely; the same per-run token now
drives manager prewarm, launcher acknowledgement, cancellation cleanup, and the
final valid-CAN handoff.

The guided runs from `1f5c255447ecffaf3c1d412fd3756920a2f8a82c` through
`5784933a8c1a277492819d782ae999ad63756c8d` establish a more specific failure.
Every boot-catch install used Python Panda, matched the Corolla F181 and payload,
and returned a first-attempt `0x777` to `0x7A9` response in 10.26--16.18 ms.
Normal runtime then published hundreds of accepted, sequence-aligned `0x777`
fragments with zero rejects and zero in both longitudinal fields, but received no
`0x7A9` and therefore published no host `0x08A`. The latest two guarded
application-programming attempts reached their complete stationary interlock and
were rejected with NRC `0x22`; those attempts did not address the runtime
transport difference.

Source comparison with the working standalone path identified that difference.
Python Panda initializes every bus with `canfd_auto=false`, preserving the
eight-byte signer request as Classical CAN. Native `pandad` initialized every bus
with `canfd_auto=true`; after this Corolla's 32-byte bus-0 traffic enabled FD,
Panda promoted the eight-byte `0x777` request to CAN-FD. The send receipts prove
acceptance by Panda safety, not the wire format seen by the EPS. The EPS resident
was therefore never proven to have expired; the runtime request format was wrong.

For Toyota safety with `TSS3_SIGNER`, `pandad` now disables automatic FD
promotion on every Panda bus and explicitly sets each outgoing packet's format:
payloads of eight bytes or less use Classical CAN and larger payloads use CAN-FD.
Other vehicles retain automatic FD behavior. Initial fingerprinting also starts
with automatic promotion disabled, matching Python Panda. The speculative
post-start reinstall, brake gates, and extended operator timeout are removed;
the supported sequence is again vehicle OFF, arm UI bringup, then brake + POWER
normally. Runtime validation must still prove `0x777`, `0x7A9`, payload-matched
host `0x08A`, zero rejected publications, and zero in both longitudinal fields.

The October 28 guided archive exercises the exact clean deployed framing tree
`1c2a4ac69bfa8437ec9722fabecefb99dca3ed6d` twice. Both runs record branch
`star2025`, the expected remote, and an acknowledged startup bridge. Each
matched EPS F181 `8965F1208000 / 8A3111213000`, payload SHA-256
`72ffc3eebbec7966177c700a12e3d132f4a5bd03682e61f266bfea62815f8122`, and
Panda `DEV-9250dab8-DEBUG` with a firmware signature match. Both boot-catch
requests explicitly record `fd=false`, four accepted and zero rejected TX
receipts, and a first-attempt status-zero `0x7A9` response in 12.81 ms and
11.04 ms. This proves the installer side of the deployed tree. It does not yet
exercise the new native-`pandad` packet framing because the archive contains no
qlog or rlog.

Both runs also repeat the same peer-health boundary: Brake `0x102D` failure
bits are clear, while DID `0x102F` returns the stable eight-byte value
`0700000000000000` that the Camry-oriented ten-byte decoder rejects as
unsupported. The UI therefore preserves the proven signer install but correctly
keeps vehicle health inconclusive; the unsupported layout is neither promoted
to a fault nor treated as a health pass. The next required evidence is the
stationary qlog/rlog from this commit or a descendant with no runtime changes.

The later October 28 archive from the same clean source commit closes that
provenance question and exposes a deployment failure. Its installer again
matched the exact F181 pair and payload, transmitted four explicit Classical-CAN
`0x777` frames with four accepts and zero rejects, and received status-zero
`0x7A9` on the first attempt in 9.23 ms. Across the two following routes, Panda
accepted 436 runtime `0x777` fragments forming 106 aligned applications, with
zero rejected publications, zero carrier/application sequence mismatches, and
zero in both longitudinal fields. Neither route received `0x7A9` or published a
payload-matched host `0x08A`. The longer route moved at up to 1.952 m/s; the
shorter route changed gears and recorded `canBusMissing`, `canError`, and
`controlsMismatch`, so neither is a stationary validation pass.

The tracked `prebuilt` marker explains why those routes did not actually run the
new native framing code. It suppresses the on-device source build, and the
tracked ARM `selfdrive/pandad/pandad` was last rebuilt at
`fedb206c6046af078cc5472ae99b338b9636f7bb`, before the packet-local FD and
startup-auto-FD changes. `initData` correctly described the checked-out source
commit, but could not prove the provenance of that stale executable. The ARM
binary has now been rebuilt from the exact current transport tree. Its SHA-256
is `571b3744c77cf7c28bfd139a6418437c2fe697f5110c23bf04d8e9cb14fd73bd`;
disassembly confirms startup disables auto-FD on all three buses, Toyota safety
keeps it disabled when the TSS3 signer bit is set, and packet packing sets FD
only for payloads longer than eight bytes. A prebuilt-policy test now rejects a
clean checkout whose tracked pandad predates its transport sources.

The October 29 guided archive and route finally exercise that rebuilt native
binary at clean commit `02c3d231351658220063a8edd81737e78fe110d4`.
Fingerprinting selected exact, non-fuzzy `TOYOTA_COROLLA_TSS3`; Panda entered
Toyota safety param 53321 with no faults or invalid RX checks. The post-install
stationary route remained in Park at zero speed and recorded no `canError`,
`canBusMissing`, or `controlsMismatch`. Panda accepted all 248 Classical-CAN
`0x777` fragments, forming 62 aligned applications, with zero rejects and zero
in both longitudinal fields. Eight status-zero responses appeared on bus 0 and
were mirrored on bus 2. This proves the source and deployed binary framing fix.

It also exposes the next boundary. The first bus-0 response arrived 0.641 s
after the install completed and the last arrived at 7.732 s; sequence 7 and all
later one-second challenges were accepted by Panda but received no response.
In route time, that final response was at 7.124 s, Panda changed from ELM327 to
Toyota safety param 53321 at 7.354 s, and sequence 7 was not sent until 8.131 s.
The correlation does not establish whether the resident expired independently
or the safety transition exposed a remaining transport difference. The
response-paced preflight removes that one-second observation gap on the next
run.
The route never left Park, cruise main remained unavailable, `CarControl` was
never enabled, and Panda `controlsAllowed` remained false. Consequently no host
`0x08A` was expected or published; this route cannot validate handoff. The
Corolla resident's retained 100 Hz benchmark is the only sustained-liveness
proof, while the inherited one-second Camry probe cadence has now failed on the
vehicle. Corolla preflight therefore keeps exactly one inactive request in
flight and replaces it immediately after a valid response, bounded by the
100 Hz controller. A missing response still times out and falls back to bounded
retry. This changes neither ownership nor actuation: preflight emits no admin
arm or host `0x08A`, and both longitudinal fields remain zero.

The later October 29 archive validates that response-paced behavior on exact,
clean commit `9d9a2205734bfafd32c41c0c52b22166fdb6e265`. Its 2.954 s route
formed 143 aligned inactive applications and recorded 142 status-zero
responses on bus 0, mirrored on bus 2. Panda accepted 568 request fragments;
the only four rejects were one complete final challenge at 2.914 s, after
`deviceState.started` changed false at 2.880 s. The route therefore ended on an
ordinary offroad transition, not an OS reboot. It remained stationary in Park,
with exact non-fuzzy Corolla fingerprinting, no CAN timeout, no Panda fault or
invalid RX check, no enabled/active control, no host `0x08A`, and zero in both
longitudinal fields. Panda remained in ELM327 safety for the entire short route,
so this capture still does not test the Toyota-safety handoff or the earlier
eight-second lifetime boundary. Its route timestamps also precede the first
installer run saved in the same archive; that installer ran about 14 seconds
after the route ended and passed its first live probe in 9.92 ms. A second
installer run passed in 12.59 ms without a monotonic-clock restart.

The offline evidence report now records `deviceState.started` transitions,
Panda safety transitions, and separate accepted/rejected `0x777` receipt
timelines. This prevents shutdown rejects from being mistaken for an onroad
transport failure and makes the next safety-handoff boundary directly visible.

The October 30 post-install route resolves that boundary. Route logging began
0.604 s after the install completed. Response-paced preflight received 382
status-zero responses on bus 0, mirrored on bus 2; the last response was at
route offset 7.488 s, or 8.091 s after installation. Panda did not enter Toyota
safety param 53321 until route offset 7.575 s, 87.5 ms later. All 1,744 request
fragments were accepted, with zero rejects, and requests continued through
route offset 60.737 s without another response. Continuous challenges therefore
do not retain the resident, and neither CAN-FD promotion nor Toyota safety
rejection explains the loss. The external payload places its resident at
`0xFEBFF9F0`, inside Corolla application RAM; it must be relocated and rebuilt.
StarPilot now rejects the proven-expiring payload hash until a replacement is
reviewed and pinned.

This was not a stationary route despite the validation gate: it reached
12.868 m/s and selected Drive and Reverse. Openpilot remained disabled with no
active lateral or longitudinal control, published no host `0x08A`, recorded no
Panda faults or invalid RX checks, and kept both longitudinal fields and
actuator acceleration zero. No moving-road authority is established by this
capture.

The October 31 capture independently repeats the result with the same revoked
payload and old clean runtime commit `9d9a220573`. Logging began 0.602 s after
installation. It recorded 369 status-zero bus-0 responses, mirrored on bus 2;
the last was 7.846 s after install. Panda changed to Toyota safety at 7.935 s
after install, again about 89 ms later. Panda accepted all 1,692 request
fragments with zero rejects and continued accepting them through route offset
61.489 s, but the signer never answered again. The route reached 10.392 m/s and
selected Drive, Reverse, and Neutral despite the stationary gate. Openpilot was
never engageable or enabled, Panda never allowed controls, no host `0x08A` was
published, and every longitudinal field remained zero. This repeat adds no
authority and confirms that testing must stop until the revoked kit is replaced.

The installer summaries on the earlier runs marked clean builds dirty because
persisted `GitDiff` included runtime-selected theme symlinks. Route `initData`
was authoritative. Summaries now use the same build metadata as `initData` so
runtime theme selection does not mislabel an exact deployment.

Run the offline report with:

```bash
python3 tools/corolla_tss3_route_evidence.py /path/to/rlog.zst \
  --output /tmp/corolla-tss3-evidence.json
```

The report separates native `0x08A`, candidate `0x160`, signer `0x7A9`, host
`sendcan` publications, `0x777` and `0x08A` TX receipts, payload-matched host
acceptance, and the transport lifecycle records. It also reconstructs complete
four-frame Corolla signer applications and independently checks both redundant
longitudinal fields for zero. It also requires each application's six-bit
`REQUEST_SEQUENCE` to equal the low six bits of the outer carrier sequence; the
first runtime preflight therefore reproduces the installer's proven sequence-1
request byte for byte. Forwarded stock `0x08A` also produces TX receipts and is
never counted as host acceptance without a matching `sendcan` frame. The report
also lists which bytes changed in native candidate frames. Schema v3 adds exact
first/last traffic offsets, deployed commit identity, fingerprint provenance,
CarParams safety configuration, gear and speed, engagement state, on-road
events, Panda safety transitions, faults, and invalid RX-check counts.

## In-car gate order

1. Install the volatile signer from OFF using the guided UI startup catcher.
   Do not move the car until the live signer probe has passed and the vehicle
   has returned to READY without affirmative Brake/EPS fault bits.
2. With the service brake firmly held, select Drive, release the parking brake,
   close all doors, enable cruise main, and engage/disengage once without allowing
   the car to move. Before the engagement edge, require a
   `preflight_signer_live` record from the startup handoff; otherwise PCM engagement remains blocked. Park
   is not an engageable gear and cannot exercise the normal request plane.
   Require a `signer_response_live` record, a `host_08a_active` record, accepted
   `0x777` and `0x08A` publications, zero rejected publications, and zero nonzero
   longitudinal fields in both reconstructed signer applications and host
   publications. Also require zero carrier/application sequence mismatches.
3. With a spotter on private, controlled pavement, validate low-speed lateral
   tracking and driver override. Stop on any cluster fault, screen instability,
   request-plane authority failure, or missing signed-publication cadence.
4. Only after the stationary and low-speed route passes, compare requested
   steering angle, measured angle, Panda acceptance, signer latency, and
   superseded generations over a longer lateral route.

## Longitudinal research gate

Do not enable longitudinal from the 2023 `0x160` path or from the current
Camry-derived `0x08A` envelope by assumption. First collect a stock-ACC rlog on
this exact car that includes transitions through cruise off, armed, active,
acceleration, deceleration, driver gas, driver brake, standstill, and resume.
For native `0x08A` and any live `0x160`, establish:

- producing ECU, destination bus, DLC, cadence, and counter/freshness fields;
- requested-acceleration encoding, scale, sign, inactive value, and redundant
  field relationship;
- request/allocation IDs and all fixed or state-dependent envelope bytes;
- pedal disengagement behavior, standstill/resume behavior, and stock bounds;
- whether changing an application field still yields a valid signer response;
- Panda limits for acceleration, jerk, gas/brake disagreement, request
  redundancy, controls-allowed state, and message timeout.

Until those items are established, `openpilotLongitudinalControl` remains
false, CarController always requests zero acceleration, and Panda independently
rejects a nonzero value in either redundant acceleration field.
