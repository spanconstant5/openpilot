# Comma File Portal

Run `Open-CommaPortal.bat`, then open `http://127.0.0.1:8765` on the same Windows PC.

Enter the comma's private IP address. A MAC address also works only if the PC has already seen the
device on its local network and has an ARP entry for it. The portal connects through ADB on port
5555, lists timestamps and sizes for known telemetry/log/video files and EPS Telescope export
bundles, and copies a selected file
to `Documents\Comma Telemetry\Portal downloads`.

There is no three-day or other portal-side retention limit. Every matching recording file that is
still physically present on the comma is listed. The comma's own storage cleanup can still remove
older files when it needs space.

EPS Telescope bundles end in `.eps-telescope.zip`. They contain the JSON and Markdown report and
can include a VIN and ECU identifiers. Treat them as private vehicle data. Once copied to the PC,
you can attach the bundle to a private GitHub issue or store it wherever you prefer; no GitHub token
is kept on the comma.

The portal listens only on `127.0.0.1`, accepts only private IPv4 targets, never transmits CAN
messages, and cannot browse or execute arbitrary device paths.
