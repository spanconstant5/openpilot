# Linux app layer

Run `./install_dependencies.sh` first. On apt, dnf, or pacman systems it installs Python, Android
platform-tools, FFmpeg, and the Qt runtime libraries, then creates `.venv` and installs
PySide6/PyInstaller. Run `tskdash-import` to copy completed drives and `tskdash-viewer` to view them.

The script displays and uses the native package-manager commands and will request sudo when needed.
It stops without changing packages on unsupported distributions.

For a desktop-menu entry, place the launchers on `PATH` and copy `tskdash-viewer.desktop` to
`~/.local/share/applications`. `build_linux.sh` creates unsigned local PyInstaller output in `dist`;
it does not install or publish a package.
