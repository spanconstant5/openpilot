# Linux app layer

Install Python 3.12, Android platform-tools, FFmpeg, and the viewer requirements. Run
`tskdash-import` to copy completed drives and `tskdash-viewer` to view them.

For a desktop-menu entry, place the launchers on `PATH` and copy `tskdash-viewer.desktop` to
`~/.local/share/applications`. `build_linux.sh` creates unsigned local PyInstaller output in `dist`;
it does not install or publish a package.
