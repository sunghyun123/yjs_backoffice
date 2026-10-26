[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')]
    [string]$DeviceName = "yj-dashboard"
)

$ErrorActionPreference = "Stop"
$tailscaleCommand = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $tailscaleCommand) {
    $fallback = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) {
        $tailscalePath = $fallback
    } else {
        throw "Tailscale is not installed. Install it, sign in, and try again."
    }
} else {
    $tailscalePath = $tailscaleCommand.Source
}

$status = (& $tailscalePath status --json | ConvertFrom-Json)
if ($status.BackendState -ne "Running") {
    throw "Tailscale is not connected. Current state: $($status.BackendState)"
}

$listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $listeners) {
    throw "No dashboard is listening on 127.0.0.1:$Port."
}
$unsafeListener = $listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }
if ($unsafeListener) {
    throw "The dashboard is exposed on a non-loopback address. Fix the binding before configuring Serve."
}

$funnelStatus = (& $tailscalePath funnel status) -join "`n"
if ($funnelStatus -match "Available on the internet") {
    throw "A public Tailscale Funnel route is active. Disable it before configuring the dashboard."
}

& $tailscalePath set "--hostname=$DeviceName"
if ($LASTEXITCODE -ne 0) {
    throw "Tailscale machine-name configuration failed."
}

$target = "http://127.0.0.1:$Port"
& $tailscalePath serve --bg $target
if ($LASTEXITCODE -ne 0) {
    throw "Tailscale Serve configuration failed."
}

Write-Host "Tailscale machine name and Serve configured. Verify the HTTPS URL and proxy target below."
& $tailscalePath serve status
