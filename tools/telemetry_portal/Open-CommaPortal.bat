@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m openpilot.tools.telemetry_portal.server %*
) else (
  py -3 -m openpilot.tools.telemetry_portal.server %*
)
if errorlevel 1 pause
