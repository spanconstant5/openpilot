# Wi-Fi transfer window (test branch)

After the car turns off, the dashcam recorder immediately finalizes the active
telemetry segment. This test build then keeps the comma's network out of normal
power-save for 15 minutes, so a PC on the same Wi-Fi network can use the local
portal to copy recordings.

The display may turn off during the window. The comma must still have Wi-Fi
connected and ADB enabled for a PC to reach it.

The window is capped at 30 minutes. It does not override a low-voltage,
depleted-battery, or forced-shutdown protection. Turning ignition back on ends
the transfer window immediately.

To disable it on an advanced/test device, set
`DashcamTransferWindowMinutes` to `0`. Values from `1` through `30` select the
number of minutes; values above 30 are treated as 30.
