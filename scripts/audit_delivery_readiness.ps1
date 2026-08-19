[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [string]$WikiRoot = "",

    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')]
    [string]$DeviceName = "yj-dashboard"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $WikiRoot) {
    $WikiRoot = Join-Path (Split-Path $projectRoot -Parent) "thinkwise-wiki"
}
$dashboardEnv = Join-Path $projectRoot ".env"
$wikiEnv = Join-Path $WikiRoot ".env"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dashboardData = Join-Path $projectRoot "data"
$wikiData = Join-Path $WikiRoot "data"
$script:failures = 0

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed
    )
    if ($Passed) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Name" -ForegroundColor Red
        $script:failures++
    }
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
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

function ConvertTo-AllowedTailscaleUsers {
    param([string[]]$Values)

    $users = @()
    foreach ($value in $Values) {
        foreach ($candidate in ([string]$value -split ",")) {
            $normalized = $candidate.Trim().ToLowerInvariant()
            if ($normalized -and $normalized -notin $users) {
                $users += $normalized
            }
        }
    }
    return $users
}

function Test-RestrictedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$RequireProtected
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    try {
        $acl = Get-Acl -LiteralPath $Path
        if ($RequireProtected -and -not $acl.AreAccessRulesProtected) {
            return $false
        }
        $allowedSids = @(
            "S-1-5-18",
            "S-1-5-32-544",
            [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        )
        $seen = @{}
        foreach ($rule in $acl.Access) {
            if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
                continue
            }
            $sid = $rule.IdentityReference.Translate(
                [Security.Principal.SecurityIdentifier]
            ).Value
            if ($sid -notin $allowedSids) {
                return $false
            }
            $seen[$sid] = $true
        }
        return ($allowedSids | Where-Object { -not $seen.ContainsKey($_) }).Count -eq 0
    } catch {
        return $false
    }
}

function Test-SecurityHeaders {
    param([Parameter(Mandatory = $true)]$Headers)
    return (
        $Headers["Cache-Control"] -eq "no-store" -and
        $Headers["X-Content-Type-Options"] -eq "nosniff" -and
        $Headers["X-Frame-Options"] -eq "DENY" -and
        $Headers["Referrer-Policy"] -eq "no-referrer" -and
        $Headers["Content-Security-Policy"] -match "default-src 'self'" -and
        $Headers["Strict-Transport-Security"] -eq "max-age=31536000" -and
        -not $Headers["Access-Control-Allow-Origin"]
    )
}

$requiredFiles = @($dashboardEnv, $wikiEnv, $pythonPath)
Add-Check "Required environment and Python files" (($requiredFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -eq 0)

$allowedUsers = @(ConvertTo-AllowedTailscaleUsers -Values @(
    (Get-DotEnvValue $dashboardEnv "APP_ALLOWED_TAILSCALE_USERS")
    (Get-DotEnvValue $dashboardEnv "APP_ALLOWED_TAILSCALE_USER")
))
$productionChecks = @(
    (Get-DotEnvValue $dashboardEnv "APP_ENV") -eq "production",
    (Get-DotEnvValue $dashboardEnv "APP_HOST") -eq "127.0.0.1",
    (Get-DotEnvValue $dashboardEnv "APP_DEMO_MODE") -eq "false",
    (Get-DotEnvValue $dashboardEnv "APP_TRUST_TAILSCALE_HEADERS") -eq "true",
    ($allowedUsers.Count -gt 0),
    [bool](Get-DotEnvValue $dashboardEnv "DB_USER"),
    [bool](Get-DotEnvValue $dashboardEnv "DB_PASSWORD")
)
Add-Check "Production, real-data, and identity settings" ($productionChecks -notcontains $false)

$indexPath = Get-DotEnvValue $dashboardEnv "THINKWISE_INDEX_PATH"
if ($indexPath -and -not [IO.Path]::IsPathRooted($indexPath)) {
    $indexPath = Join-Path $projectRoot $indexPath
}
$wikiIndexPath = Get-DotEnvValue $wikiEnv "INDEX_DB_PATH"
if (-not $wikiIndexPath) {
    $wikiIndexPath = Join-Path $WikiRoot "data\wiki_index.db"
} elseif (-not [IO.Path]::IsPathRooted($wikiIndexPath)) {
    $wikiIndexPath = Join-Path $WikiRoot $wikiIndexPath
}
$sharedIndexReady = $false
if ($indexPath -and $wikiIndexPath) {
    try {
        $dashboardIndexFullPath = [IO.Path]::GetFullPath($indexPath)
        $wikiIndexFullPath = [IO.Path]::GetFullPath($wikiIndexPath)
        $sharedIndexReady = (
            $dashboardIndexFullPath.Equals(
                $wikiIndexFullPath,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Test-Path -LiteralPath $dashboardIndexFullPath -PathType Leaf)
        )
    } catch {
        $sharedIndexReady = $false
    }
}
Add-Check "Dashboard and wiki share one work-log index" $sharedIndexReady

$mailPrefixes = @("DAOU", "GMAIL", "NAVER")
$allMailEnabled = $true
foreach ($mailPrefix in $mailPrefixes) {
    $mailUser = Get-DotEnvValue $dashboardEnv "MAIL_${mailPrefix}_USER"
    $mailSettings = @(
        (Get-DotEnvValue $dashboardEnv "MAIL_${mailPrefix}_ENABLED") -eq "true",
        [bool](Get-DotEnvValue $dashboardEnv "MAIL_${mailPrefix}_HOST"),
        [bool]$mailUser,
        [bool](Get-DotEnvValue $dashboardEnv "MAIL_${mailPrefix}_PASSWORD"),
        (Get-DotEnvValue $dashboardEnv "MAIL_${mailPrefix}_URL").StartsWith(
            "https://", [StringComparison]::OrdinalIgnoreCase
        )
    )
    if ($mailPrefix -eq "DAOU" -and $mailUser -notmatch "@") {
        $mailSettings += $false
    }
    if ($mailSettings -contains $false) {
        $allMailEnabled = $false
    }
}
Add-Check "All three mail account settings" $allMailEnabled

$pythonReady = $false
if (Test-Path -LiteralPath $pythonPath -PathType Leaf) {
    try {
        & $pythonPath -c "import sys; sys.path.insert(0, sys.argv[1]); import fastapi, pymysql, pydantic_settings, dotenv, uvicorn, app.main" $projectRoot 2>$null
        $dashboardImportReady = $LASTEXITCODE -eq 0
        & $pythonPath -c "import sys; sys.path.insert(0, sys.argv[1]); import app.sync" $WikiRoot 2>$null
        $wikiImportReady = $LASTEXITCODE -eq 0
        $pythonReady = $dashboardImportReady -and $wikiImportReady
    } catch {
        $pythonReady = $false
    }
}
Add-Check "Shared Python environment imports both applications" $pythonReady

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
$loopbackOnly = $listeners.Count -gt 0 -and (
    $listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }
).Count -eq 0
Add-Check "Loopback-only listener" $loopbackOnly

$apiReady = $false
$mailReady = $false
$backupReady = $false
if ($loopbackOnly -and $allowedUsers.Count -gt 0) {
    try {
        $headers = @{ "Tailscale-User-Login" = $allowedUsers[0] }
        $baseUrl = "http://127.0.0.1:$Port"
        $allAllowedUsersAccepted = $true
        foreach ($allowedUser in $allowedUsers) {
            $identityResponse = Invoke-WebRequest -UseBasicParsing `
                -Uri "$baseUrl/api/health" `
                -Headers @{ "Tailscale-User-Login" = $allowedUser } `
                -TimeoutSec 5
            if (
                $identityResponse.StatusCode -ne 200 -or
                -not (Test-SecurityHeaders $identityResponse.Headers)
            ) {
                $allAllowedUsersAccepted = $false
            }
        }
        $unauthorizedStatus = 0
        $unauthorizedHeaders = $null
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/api/health" -TimeoutSec 5 | Out-Null
            $unauthorizedStatus = 200
        } catch {
            $unauthorizedStatus = [int]$_.Exception.Response.StatusCode
            $unauthorizedHeaders = $_.Exception.Response.Headers
        }
        $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/api/health" -Headers $headers -TimeoutSec 5
        $pageResponse = Invoke-WebRequest -UseBasicParsing -Uri $baseUrl -Headers $headers -TimeoutSec 5
        $health = $healthResponse.Content | ConvertFrom-Json
        $dashboard = Invoke-RestMethod -Uri "$baseUrl/api/dashboard" -Headers $headers -TimeoutSec 5
        $statusTotal = @(
            "active", "slowing", "idle", "dormant", "running", "done", "hold"
        ) | ForEach-Object { [int]$dashboard.kpi.$_ } | Measure-Object -Sum
        $apiReady = (
            $allAllowedUsersAccepted -and
            $unauthorizedStatus -eq 403 -and
            (Test-SecurityHeaders $unauthorizedHeaders) -and
            $health.status -eq "ok" -and
            -not $health.demo_mode -and
            $health.source.healthy -and
            -not $dashboard.stale -and
            $dashboard.kpi.total_projects -gt 0 -and
            $dashboard.projects.Count -eq $dashboard.kpi.total_projects -and
            $statusTotal.Sum -eq $dashboard.kpi.total_projects -and
            (Test-SecurityHeaders $healthResponse.Headers) -and
            (Test-SecurityHeaders $pageResponse.Headers)
        )
        $mailAccountKeys = @(
            $dashboard.mail.unread_by_account.PSObject.Properties.Name
        )
        $mailCountSum = @(
            $dashboard.mail.unread_by_account.PSObject.Properties.Value
        ) | Measure-Object -Sum
        $mailReady = (
            $allMailEnabled -and
            $dashboard.mail.fetched_at -and
            -not $dashboard.mail.stale -and
            (@("daou", "gmail", "naver") | Where-Object { $_ -notin $mailAccountKeys }).Count -eq 0 -and
            $mailCountSum.Sum -eq $dashboard.mail.unread_total
        )
    } catch {
        $apiReady = $false
        $mailReady = $false
    }
}
Add-Check "Real-data API, unauthorized rejection, and security headers" $apiReady
Add-Check "Fresh snapshot from all three mail accounts" $mailReady

$today = Get-Date -Format "yyyy-MM-dd"
$backupPath = Join-Path $dashboardData "backups\dashboard-$today.db"
if ($pythonReady -and (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
    try {
        & $pythonPath -c "import sqlite3,sys; from pathlib import Path; uri=Path(sys.argv[1]).resolve().as_uri()+'?mode=ro'; c=sqlite3.connect(uri,uri=True); c.execute('SELECT COUNT(*) FROM project_mark').fetchone(); c.execute('SELECT COUNT(*) FROM setting').fetchone(); c.close()" $backupPath 2>$null
        $backupReady = $LASTEXITCODE -eq 0
    } catch {
        $backupReady = $false
    }
}
Add-Check "Today's SQLite backup can be queried" $backupReady

$taskReady = $false
try {
    $dashboardTask = Get-ScheduledTask -TaskName "YJS Management Dashboard" -ErrorAction Stop
    $syncTask = Get-ScheduledTask -TaskName "YJS ThinkWise Shared Index Sync" -ErrorAction Stop
    $taskReady = (
        $dashboardTask.State -eq "Running" -and
        $syncTask.State -eq "Running" -and
        $dashboardTask.Principal.UserId -eq "SYSTEM" -and
        $syncTask.Principal.UserId -eq "SYSTEM" -and
        $dashboardTask.Actions.Arguments -match "run_dashboard\.ps1" -and
        $syncTask.Actions.Arguments -match "run_thinkwise_index_sync\.ps1"
    )
} catch {
    $taskReady = $false
}
Add-Check "Both startup tasks are running" $taskReady

$aclRootsReady = (
    (Test-RestrictedAcl $dashboardEnv -RequireProtected) -and
    (Test-RestrictedAcl $wikiEnv -RequireProtected) -and
    (Test-RestrictedAcl $dashboardData -RequireProtected) -and
    (Test-RestrictedAcl $wikiData -RequireProtected)
)
$dataChildren = @(
    Get-ChildItem -LiteralPath $dashboardData, $wikiData -Force -Recurse -ErrorAction SilentlyContinue
)
$aclChildrenReady = ($dataChildren | Where-Object {
    ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    -not (Test-RestrictedAcl $_.FullName)
}).Count -eq 0
$aclReady = $aclRootsReady -and $aclChildrenReady
Add-Check "Restricted secret and SQLite ACLs" $aclReady

$tailscaleReady = $false
$deviceNameReady = $false
$serveReady = $false
$funnelDisabled = $false
$tailscaleCommand = Get-Command tailscale.exe -ErrorAction SilentlyContinue
$tailscalePath = if ($tailscaleCommand) {
    $tailscaleCommand.Source
} else {
    $fallback = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) { $fallback } else { "" }
}
if ($tailscalePath) {
    try {
        $tailscaleStatus = (& $tailscalePath status --json | ConvertFrom-Json)
        $tailscaleReady = $tailscaleStatus.BackendState -eq "Running"
        $dnsName = [string]$tailscaleStatus.Self.DNSName
        $deviceNameReady = $dnsName.TrimEnd('.').Split('.')[0] -eq $DeviceName
        $serveStatus = (& $tailscalePath serve status) -join "`n"
        $serveReady = (
            $serveStatus -match "https://" -and
            $serveStatus -match [regex]::Escape("127.0.0.1:$Port")
        )
        $funnelStatus = (& $tailscalePath funnel status) -join "`n"
        # Recent Tailscale versions also list private Serve routes here.
        # Funnel is public only when the CLI explicitly reports internet availability.
        $funnelDisabled = $funnelStatus -notmatch "Available on the internet"
    } catch {
        $tailscaleReady = $false
        $deviceNameReady = $false
        $serveReady = $false
        $funnelDisabled = $false
    }
}
Add-Check "Tailscale connected" $tailscaleReady
Add-Check "Non-sensitive Tailscale machine name" $deviceNameReady
Add-Check "Serve localhost HTTPS proxy" $serveReady
Add-Check "No public Funnel route" $funnelDisabled

if ($script:failures -gt 0) {
    Write-Host "Delivery readiness audit failed: $script:failures item(s)" -ForegroundColor Red
    exit 1
}
Write-Host "All automatable delivery readiness checks passed." -ForegroundColor Green
