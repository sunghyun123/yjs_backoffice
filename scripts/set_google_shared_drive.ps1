[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SharedDriveId,

    [string]$EnvPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $EnvPath) {
    $EnvPath = Join-Path $projectRoot ".env"
}
$EnvPath = [IO.Path]::GetFullPath($EnvPath)
if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    throw "Dashboard .env file not found."
}

$normalizedId = $SharedDriveId.Trim()
if ($normalizedId -notmatch '^[A-Za-z0-9_-]{10,128}$') {
    throw "Google Shared Drive ID has an invalid format."
}

$newLine = "GOOGLE_SHARED_DRIVE_ID=$normalizedId"
$sourceLines = [IO.File]::ReadAllLines($EnvPath, [Text.Encoding]::UTF8)
$outputLines = New-Object System.Collections.Generic.List[string]
$settingWritten = $false
foreach ($line in $sourceLines) {
    if ($line -match '^\s*GOOGLE_SHARED_DRIVE_ID\s*=') {
        if (-not $settingWritten) {
            $outputLines.Add($newLine)
            $settingWritten = $true
        }
        continue
    }
    $outputLines.Add($line)
}
if (-not $settingWritten) {
    $outputLines.Add($newLine)
}

if ($PSCmdlet.ShouldProcess($EnvPath, "update Google Shared Drive target")) {
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($EnvPath, $outputLines, $utf8NoBom)
    Write-Host "Google Shared Drive target updated."
}
