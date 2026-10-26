[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WikiRoot,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [ValidateRange(60, 3600)]
    [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "Stop"
$resolvedWikiRoot = (Resolve-Path -LiteralPath $WikiRoot).Path
$resolvedPythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$wikiEnvPath = Join-Path $resolvedWikiRoot ".env"

if (-not (Test-Path -LiteralPath $wikiEnvPath -PathType Leaf)) {
    throw "Wiki index synchronization configuration was not found: $wikiEnvPath"
}

Set-Location -LiteralPath $resolvedWikiRoot
while ($true) {
    & $resolvedPythonPath -m app.sync
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ThinkWise index synchronization failed (exit code $LASTEXITCODE)." -ErrorAction Continue
    }
    Start-Sleep -Seconds $IntervalSeconds
}
