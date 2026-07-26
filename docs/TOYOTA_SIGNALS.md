# Toyota signal policy

The live HUD consumes public CarState fields only. Phase 3's recorder may additionally subscribe to
the existing read-only `can` service and ask the already-selected Toyota opendbc DBC to decode a
small allowlist. It never transmits CAN, guesses addresses, or changes vehicle-control behavior.

## Used in v0.1.0-alpha.1

| Display | Existing field | Meaning |
| --- | --- | --- |
| Throttle | deprecated analog gas when populated, otherwise `gasPressed` | driver input only |
| Brake | deprecated analog brake when populated, otherwise `brakePressed` | driver input only |
| TSS AEB | `stockAeb` | decoded Toyota pre-collision braking active |
| TSS cruise | `cruiseState.available/enabled` | decoded Toyota cruise availability/activity |
| RPM | deprecated `engineRpm` when positive | engine speed, hidden if never populated |

Driver input is orange and carries a small `! DRIVER`/override label. A stock AEB event is red and
labeled `TSS AEB`. Openpilot engagement remains separate from stock cruise state.

## Exact TODOs

1. Expose a reviewed source-tagged stock longitudinal command if opendbc can distinguish TSS
   acceleration and braking magnitude across supported Toyota platforms.
2. Expose hybrid battery state of charge with units, scaling, validity, and platform coverage.
3. Expose EV mode and signed hybrid power flow with explicit unavailable states.
4. Decide which additional lane/PCS states are sufficiently universal to label as TSS without
   overstating subsystem activity.
5. Add route-based opendbc tests for every new field before implementing a provider mapping.

Until those tasks are complete, provider methods return unavailable and the HUD hides the panel.
Contributors must document DBC messages, scaling, platform applicability, counter/checksum handling,
and replay tests in the opendbc change. Adding guessed addresses directly to this repository is not
accepted.

## Phase 3 allowlist

| Display | Reviewed DBC signal | Behavior |
| --- | --- | --- |
| RPM / engine running | `ENGINE_RPM.RPM`, `ENGINE_RPM.ENGINE_RUNNING` | hidden when stale or absent |
| EV mode | derived only from the fresh engine-running/RPM signal | `EV MODE` means the engine is off |
| Power flow | `GEAR_PACKET_HYBRID.FDRVREAL × vEgo` | signed wheel power; acceleration-based fallback is marked `EST` |
| LTA active | `EPS_STATUS.LTA_STATE == 5` | contributes to TSS status only while actively engaged |
| Radar cruise active | `cruiseState.enabled` | contributes to TSS status only while actively engaged |

`TSS ACTIVE · RADAR + LTA` is reserved for the highway-style state where both systems are engaged.
Radar-only and LTA-only activity are named explicitly. Ordinary manual city driving displays
`TSS READY` when the systems are available or `TSS OFF` when unavailable. Driver pedal/steering
override is a separate orange warning and does not change the TSS state.

No verified traction-battery SOC field for the 2025 Corolla Hybrid exists in this checkout, so the
battery value intentionally remains unavailable pending a route capture and reviewed DBC mapping.
