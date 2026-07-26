@echo off
setlocal
for %%I in ("%~dp0\..\..") do set "REPO_ROOT=%%~fI"
pushd "%REPO_ROOT%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m openpilot.tools.telemetry_viewer.viewer %*
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.11+ or create .venv in the repository.
    popd
    exit /b 1
  )
  py -3 -m openpilot.tools.telemetry_viewer.viewer %*
)
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
