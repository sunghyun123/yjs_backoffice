[CmdletBinding()]
param(
    [string]$WikiRoot = "",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $WikiRoot) {
    $WikiRoot = Join-Path (Split-Path $projectRoot -Parent) "thinkwise-wiki"
}
$WikiRoot = (Resolve-Path -LiteralPath $WikiRoot).Path

$dashboardPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dashboardEnv = Join-Path $projectRoot ".env"
$wikiEnv = Join-Path $WikiRoot ".env"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    $line = Get-Content -Encoding UTF8 -LiteralPath $Path | Where-Object {
        $_ -match "^\s*$([regex]::Escape($Key))\s*="
    } | Select-Object -Last 1
    if (-not $line) {
        return ""
    }
    $value = ($line -split "=", 2)[1].Trim()
    if (
        $value.Length -ge 2 -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")))
    ) {
        return $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Resolve-ConfigPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $candidate = if ([IO.Path]::IsPathRooted($Value)) {
        $Value
    } else {
        Join-Path $Root $Value
    }
    return [IO.Path]::GetFullPath($candidate)
}

foreach ($requiredFile in @($dashboardPython, $dashboardEnv, $wikiEnv)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required file not found: $requiredFile"
    }
}

$dashboardEnvText = Get-Content -Raw -Encoding UTF8 -LiteralPath $dashboardEnv
$requiredProductionSettings = @(
    "(?m)^APP_ENV=production\s*$",
    "(?m)^APP_HOST=127\.0\.0\.1\s*$",
    "(?m)^APP_DEMO_MODE=false\s*$",
    "(?m)^APP_TRUST_TAILSCALE_HEADERS=true\s*$",
    "(?m)^APP_ALLOWED_TAILSCALE_USER=\S+\s*$"
)
foreach ($pattern in $requiredProductionSettings) {
    if ($dashboardEnvText -notmatch $pattern) {
        throw "Required production settings are missing from .env. See the delivery checklist."
    }
}

$dashboardIndexValue = Get-DotEnvValue $dashboardEnv "THINKWISE_INDEX_PATH"
if (-not $dashboardIndexValue) {
    throw "THINKWISE_INDEX_PATH is missing from the dashboard .env."
}
$wikiIndexValue = Get-DotEnvValue $wikiEnv "INDEX_DB_PATH"
if (-not $wikiIndexValue) {
    $wikiIndexValue = "data\wiki_index.db"
}
$dashboardIndexPath = Resolve-ConfigPath $projectRoot $dashboardIndexValue
$wikiIndexPath = Resolve-ConfigPath $WikiRoot $wikiIndexValue
if (-not $dashboardIndexPath.Equals($wikiIndexPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Dashboard and wiki are configured to use different work-log index files."
}
if (-not (Test-Path -LiteralPath $dashboardIndexPath -PathType Leaf)) {
    throw "Shared work-log index not found. Run the initial wiki sync first."
}

$powerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$dashboardRunner = Join-Path $PSScriptRoot "run_dashboard.ps1"
$syncRunner = Join-Path $PSScriptRoot "run_thinkwise_index_sync.ps1"

$dashboardArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $dashboardRunner
$syncArguments = (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" ' +
    '-WikiRoot "{1}" -PythonPath "{2}" -IntervalSeconds 60'
) -f $syncRunner, $WikiRoot, $dashboardPython

$dashboardAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument $dashboardArguments
$syncAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument $syncArguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$dashboardTaskName = "YJS Management Dashboard"
$syncTaskName = "YJS ThinkWise Shared Index Sync"

Register-ScheduledTask `
    -TaskName $dashboardTaskName `
    -Action $dashboardAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $taskPrincipal `
    -Force | Out-Null
Register-ScheduledTask `
    -TaskName $syncTaskName `
    -Action $syncAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $taskPrincipal `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $syncTaskName
    Start-ScheduledTask -TaskName $dashboardTaskName
}

Write-Host "Startup tasks registered: $syncTaskName, $dashboardTaskName"
