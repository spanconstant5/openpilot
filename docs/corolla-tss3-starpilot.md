# 2025 Corolla TSS3 StarPilot integration

This branch starts from StarPilot stable `404ef33a969c05297d8068fdf49b2c70e23e6697`
and keeps Galaxy, Model Manager, and Model Laboratory unchanged. The vehicle
port adds only the 2025 Corolla TSS3 control/signing path.

## Proven vehicle topology

- Corolla chassis/PT, steering-wheel buttons, signer requests, and signed
  `CONTROL_REQUEST` (`0x08A`) use Panda bus 2.
- Radar uses bus 1.
- The bundled volatile RAM signer is target-bound to EPS firmware
  `8965F1208000` and payload SHA-256
  `6234bb5bd496a82fabb32c27b56b3db0f1907b5bf6482e4c19f8835153ff69fc`.
- The safety layer accepts a signed `0x08A` only after approving the exact
  unsigned request sent to the resident signer. It falls back to the stock FRC
  request if publication stops.

The original successful openpilot milestone was reached at approximately
3,400 miles on the comma device and 21,100 miles on the car.

## Bringup

The signer is bundled in the checkout; no separate Cyberduck/SSH installation
is required. After an EPS power loss, open **Developer → TSS3 Signer Bringup**
while the car is fully off and in Park. Press ARM, then start the car normally
only when the page instructs you to. Keep the car in Park until verification
finishes.

The Developer control remains visible when the vehicle is not recognized. In
that state it displays `CHECK HARNESS` and is disabled. `KIT MISSING` indicates
that the bundled signer files failed their availability check.

## Driving models

The signer is independent of model inference. Galaxy can continue to download
and select StarPilot community models, and Model Laboratory can compare them,
without changing the Corolla signer or Panda safety policy.

This first StarPilot port intentionally does not add an automatic startup
catcher or ICBM. Manual signer bringup is the smaller auditable integration;
automatic loading and cruise-button speed management should be added only
after stationary bringup and route validation on this branch.
