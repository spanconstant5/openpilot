# Toyota signal policy

This project does not parse CAN in the HUD or telemetry process. Toyota values must first be decoded,
reviewed, and tested in opendbc, then exposed through CarState. The UI provider in
`openpilot/selfdrive/ui/onroad/dashcam_provider.py` only consumes those public fields.

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
