[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$UsersCsv,

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

$users = @()
foreach ($candidate in ($UsersCsv -split ",")) {
    $normalized = $candidate.Trim().ToLowerInvariant()
    if (-not $normalized) {
        continue
    }
    if ($normalized -notmatch '^[^\s,=]+$') {
        throw "Each Tailscale login must be a single value without spaces, commas, or equals signs."
    }
    if ($normalized -notin $users) {
        $users += $normalized
    }
}
if ($users.Count -eq 0) {
    throw "At least one Tailscale login is required."
}

$newLine = "APP_ALLOWED_TAILSCALE_USERS=" + ($users -join ",")
$sourceLines = [IO.File]::ReadAllLines($EnvPath, [Text.Encoding]::UTF8)
$outputLines = New-Object System.Collections.Generic.List[string]
$settingWritten = $false
foreach ($line in $sourceLines) {
    if ($line -match '^\s*APP_ALLOWED_TAILSCALE_USERS\s*=') {
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

if ($PSCmdlet.ShouldProcess($EnvPath, "update allowed Tailscale users")) {
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($EnvPath, $outputLines, $utf8NoBom)
    Write-Host "Updated Tailscale allowed user count: $($users.Count)"
}
