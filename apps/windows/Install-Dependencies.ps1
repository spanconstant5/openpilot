param(
  [switch]$SkipSystemPackages
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $SkipSystemPackages) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "WinGet is required. Install or update 'App Installer' from the Microsoft Store, then run this script again."
  }
  $packages = @(
    "Python.Python.3.12",
    "Google.PlatformTools",
    "Gyan.FFmpeg"
  )
  foreach ($package in $packages) {
    Write-Host "Installing $package..."
    winget install --id $package --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
      throw "WinGet could not install $package (exit code $LASTEXITCODE)."
    }
  }
}

$pythonCandidates = @(
  (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
  (Join-Path $env:ProgramFiles "Python312\python.exe"),
  (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
)
$python = $pythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $python) {
  throw "Python 3.12 was installed but is not visible yet. Open a new terminal and rerun this script."
}

$venv = Join-Path $repository ".venv"
& $python -m venv $venv
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $repository "tools\telemetry_viewer\requirements.txt") pyinstaller

Write-Host ""
Write-Host "Dependency installation complete."
Write-Host "ADB and FFmpeg may require a new terminal before their PATH entries become visible."
