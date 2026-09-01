# Toyota TSK dashcam SKU channels

These profiles define independent, passive-only distribution channels for the Toyota TSK dashcam fork. They do not
enable steering, acceleration, braking, SecOC signing, key extraction, or a panda safety configuration.

## Distribution matrix

| Profile | Intended vehicle | Harness | Current evidence | Release state |
|---|---|---|---|---|
| `corolla-2025-hybrid-le-stock` | 2025 Corolla Hybrid LE | Stock Toyota B used in the supplied car | Real rlog verified `toyota_secoc_pt_generated` on panda bus 1 | Read-only alpha |
| `corolla-2025-hybrid-le-pinswap` | 2025 Corolla Hybrid LE | User-provided pin-swap | Photos and marked schematic only | Blocked |
| `camry-2025-2026-stock` | 2025-2026 Camry | Stock, exact connector not yet verified | No vehicle log or connector continuity table | Research only |
| `camry-2025-2026-pinswap` | 2025-2026 Camry | User-provided pin-swap candidate | No vehicle log or connector continuity table | Blocked |
| `rav4-2026-stock` | 2026 RAV4 | Stock, exact connector not yet verified | Not present in current upstream support table; no vehicle log | Research only |
| `rav4-2026-pinswap` | 2026 RAV4 | User-provided pin-swap candidate | Not present in current upstream support table; no vehicle log or continuity table | Blocked |

## Why release branches are used

The comma custom-software URL `installer.comma.ai/<owner>/<branch>` clones the owner's repository named `openpilot`.
Separate repository names would require a separate public installer service. Six release branches in
`spanconstant5/openpilot` therefore provide isolated SKU update channels while remaining directly installable.

Each release branch must contain its chosen profile as `sku/active.json`. The profile is recorded in drive metadata.
An unverified pin-swap profile is deliberately rejected if it attempts to select a CAN decoder.

## Pin-swap evidence boundary

The supplied marked image is a crop of comma's Toyota B harness drawing. The official drawing identifies the center
connector as Molex `501646-1800`, viewed from the wire side. The hand markings appear to call out four lower-row
cavities and four conductors, but they do not provide an unambiguous cavity-to-cavity table, connector direction, or
electrical function. Wire color is not accepted as a pin identity.

Before a pin-swap profile can move from `blocked` to `verified`, record all of the following:

1. connector part number and whether the view is mating-side or wire-side;
2. source cavity -> destination cavity for every moved terminal;
3. circuit function and expected panda bus for each moved terminal;
4. continuity measurements with the harness disconnected and vehicle powered off;
5. CAN-H/CAN-L pair resistance and polarity checks;
6. a passive CAN capture showing expected traffic on each panda bus;
7. review that the harness relay returns the vehicle to stock operation when the comma is absent.

Do not use the marked colors alone as installation instructions.
