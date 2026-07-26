@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Dependencies.ps1"
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Review the message above.
  pause
  exit /b 1
)
echo.
echo TSKDash dependencies are ready.
pause
