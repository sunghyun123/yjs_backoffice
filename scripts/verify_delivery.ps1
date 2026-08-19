[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [string]$AllowedTailscaleUser = "",

    [switch]$RequireProduction
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $AllowedTailscaleUser -and $RequireProduction) {
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        $line = Get-Content -Encoding UTF8 -LiteralPath $envPath | Where-Object {
            $_ -match "^\s*APP_ALLOWED_TAILSCALE_USER\s*="
        } | Select-Object -Last 1
        if ($line) {
            $AllowedTailscaleUser = ($line -split "=", 2)[1].Trim()
            if (
                $AllowedTailscaleUser.Length -ge 2 -and
                (($AllowedTailscaleUser.StartsWith('"') -and $AllowedTailscaleUser.EndsWith('"')) -or
                 ($AllowedTailscaleUser.StartsWith("'") -and $AllowedTailscaleUser.EndsWith("'")))
            ) {
                $AllowedTailscaleUser = $AllowedTailscaleUser.Substring(
                    1, $AllowedTailscaleUser.Length - 2
                )
            }
        }
    }
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

Write-Host (
    "Local delivery verification passed: {0} projects, source mode {1}" -f `
    $dashboard.kpi.total_projects, $health.source.mode
)
