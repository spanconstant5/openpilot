param(
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Python) {
  $venvPython = Join-Path $repository ".venv\Scripts\python.exe"
  $Python = if (Test-Path $venvPython) { $venvPython } else { (Get-Command python).Source }
}

Push-Location $repository
try {
  & $Python -m pip install "PySide6>=6.7,<7" pyinstaller
  & $Python -m PyInstaller --noconfirm --clean --windowed --name TSKDashViewer `
    --paths $repository "openpilot\tools\telemetry_viewer\viewer.py"
  & $Python -m PyInstaller --noconfirm --clean --console --name TSKDashImporter `
    --paths $repository "openpilot\tools\telemetry_importer\importer.py"
  Write-Host "Unsigned local builds are in $repository\dist"
} finally {
  Pop-Location
}
