[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Dashboard Python virtual environment was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Production configuration file was not found: $envPath"
}

Set-Location -LiteralPath $projectRoot
& $pythonPath run.py
exit $LASTEXITCODE
