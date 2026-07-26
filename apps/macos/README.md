# macOS app layer

Install Python 3.12, Android platform-tools, FFmpeg, and the viewer requirements. Mark the `.command`
files executable if Git did not preserve their mode, then use `Import-TSKDash.command` and
`View-TSKDash.command`.

`build_macos.sh` creates unsigned local PyInstaller output in `dist`. It does not publish or sign an
application. Gatekeeper may require Control-click → Open for an owner-built unsigned app.
