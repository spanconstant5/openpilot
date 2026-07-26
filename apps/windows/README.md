# Windows app layer

1. Double-click `Install-Dependencies.bat`. It uses WinGet to install Python 3.12, Android
   platform-tools (ADB), and FFmpeg, then creates `.venv` and installs PySide6/PyInstaller.
2. Double-click `Import-TSKDash.bat` to copy completed drives from one USB-connected comma.
3. Double-click `View-TSKDash.bat` and choose an imported drive folder.

The dependency script uses only named WinGet packages and stops on an installation error. Run
`Install-Dependencies.ps1 -SkipSystemPackages` if the system packages are already managed another
way and only the local Python environment should be created.

For comma 3X/four USB import, enable ADB in Developer Settings, power the comma through port 2, and
connect a data-capable cable from the PC to port 1. If USB ADB is not visible, the importer
automatically tries comma's documented network endpoint `192.168.43.1:5555`; connect the PC to the
comma network/tether for that fallback.

`Build-Windows.ps1` creates unsigned local PyInstaller applications in `dist`. It does not publish,
sign, or install anything. Windows may show a SmartScreen warning for an unsigned local build.
