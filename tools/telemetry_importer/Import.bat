@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Import-CommaTelemetry.ps1" %*
exit /b %ERRORLEVEL%
