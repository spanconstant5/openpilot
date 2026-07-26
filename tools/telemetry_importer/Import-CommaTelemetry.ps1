param(
  [string]$Destination = "$env:USERPROFILE\Documents\Comma Telemetry",
  [string]$Adb = ""
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  $Launcher = Get-Command py -ErrorAction SilentlyContinue
  if (-not $Launcher) {
    throw "Python was not found. Install Python 3.11+ or create .venv in the repository."
  }
  $Python = $Launcher.Source
  $PythonArgs = @("-3")
} else {
  $PythonArgs = @()
}

$Arguments = @("-m", "openpilot.tools.telemetry_importer.importer", "--destination", $Destination)
if ($Adb) {
  $Arguments += @("--adb", $Adb)
}

Push-Location $RepositoryRoot
try {
  & $Python @PythonArgs @Arguments
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
