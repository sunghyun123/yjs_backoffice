[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [string]$AllowedTailscaleUser = "",

    [switch]$RequireProduction
)

$ErrorActionPreference = "Stop"
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
