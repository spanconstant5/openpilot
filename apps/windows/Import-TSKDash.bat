@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m openpilot.tools.telemetry_importer.importer %*
) else (
  py -3 -m openpilot.tools.telemetry_importer.importer %*
)
if errorlevel 1 pause
