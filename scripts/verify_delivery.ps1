[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [string]$AllowedTailscaleUser = "",

    [switch]$RequireProduction
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $projectRoot ".env"

function Get-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key)

    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        return ""
    }
    $line = Get-Content -Encoding UTF8 -LiteralPath $envPath | Where-Object {
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

if (-not $AllowedTailscaleUser -and $RequireProduction) {
    $AllowedTailscaleUser = Get-DotEnvValue "APP_ALLOWED_TAILSCALE_USER"
    if (-not $AllowedTailscaleUser) {
        throw "APP_ALLOWED_TAILSCALE_USER is missing from the production .env file."
    }
}

$listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
$unsafeListener = $listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }
if ($unsafeListener) {
    throw "Port $Port is listening on a non-loopback address."
}

$headers = @{}
if ($AllowedTailscaleUser) {
    $headers["Tailscale-User-Login"] = $AllowedTailscaleUser
}

$baseUrl = "http://127.0.0.1:$Port"
$healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/api/health" -Headers $headers
if ($healthResponse.Headers["Cache-Control"] -ne "no-store") {
    throw "The Cache-Control=no-store security header is missing."
}
$health = $healthResponse.Content | ConvertFrom-Json
$dashboard = Invoke-RestMethod -Uri "$baseUrl/api/dashboard" -Headers $headers

if ($health.status -ne "ok" -or $dashboard.stale) {
    throw "The dashboard or its data source is not healthy."
}
if ($RequireProduction -and $health.demo_mode) {
    throw "The dashboard is still running in demo mode."
}
if ($dashboard.kpi.total_projects -lt 1) {
    throw "The project dataset is empty."
}

$activeMailAccounts = @()
if ($RequireProduction) {
    foreach ($mailName in @("DAOU", "GMAIL", "NAVER")) {
        if ((Get-DotEnvValue "MAIL_${mailName}_ENABLED") -eq "true") {
            $activeMailAccounts += $mailName.ToLowerInvariant()
        }
    }
    if ($activeMailAccounts.Count -lt 1) {
        throw "No production mail account is enabled."
    }
    $mailKeys = @($dashboard.mail.unread_by_account.PSObject.Properties.Name)
    $missingMailAccounts = @(
        $activeMailAccounts | Where-Object { $_ -notin $mailKeys }
    )
    if (
        -not $dashboard.mail.fetched_at -or
        $dashboard.mail.stale -or
        $missingMailAccounts.Count -gt 0
    ) {
        throw "One or more enabled mail accounts do not have a fresh snapshot."
    }
}

Write-Host (
    "Local delivery verification passed: {0} projects, source mode {1}, active mail accounts {2}" -f `
    $dashboard.kpi.total_projects, $health.source.mode, $activeMailAccounts.Count
)
