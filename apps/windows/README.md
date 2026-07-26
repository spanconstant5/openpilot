# Windows app layer

1. Install Python 3.12, Android platform-tools (ADB), FFmpeg, and the viewer requirements.
2. Double-click `Import-TSKDash.bat` to copy completed drives from one USB-connected comma.
3. Double-click `View-TSKDash.bat` and choose an imported drive folder.

`Build-Windows.ps1` creates unsigned local PyInstaller applications in `dist`. It does not publish,
sign, or install anything. Windows may show a SmartScreen warning for an unsigned local build.
