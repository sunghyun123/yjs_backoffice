[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(60, 3600)]
    [int]$Seconds,

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

$newLine = "GOOGLE_REFRESH_SECONDS=$Seconds"
$sourceLines = [IO.File]::ReadAllLines($EnvPath, [Text.Encoding]::UTF8)
$outputLines = New-Object System.Collections.Generic.List[string]
$settingWritten = $false
foreach ($line in $sourceLines) {
    if ($line -match '^\s*GOOGLE_REFRESH_SECONDS\s*=') {
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

if ($PSCmdlet.ShouldProcess($EnvPath, "update Google refresh interval")) {
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($EnvPath, $outputLines, $utf8NoBom)
    Write-Host "Google refresh interval updated to $Seconds seconds."
}
