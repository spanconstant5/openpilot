# macOS app layer

Run `Install-Dependencies.command` first. It installs Homebrew after confirmation when necessary,
uses Homebrew for Python 3.12, Android platform-tools, and FFmpeg, then creates `.venv` and installs
PySide6/PyInstaller. After setup, use `Import-TSKDash.command` and `View-TSKDash.command`.

Mark the `.command` files executable if Git did not preserve their mode. The Homebrew bootstrap uses
Homebrew's official installer and asks before running it.

`build_macos.sh` creates unsigned local PyInstaller output in `dist`. It does not publish or sign an
application. Gatekeeper may require Control-click → Open for an owner-built unsigned app.
