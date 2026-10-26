[CmdletBinding()]
param(
    [string]$WikiRoot = ""
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

$dashboardEnv = Join-Path $projectRoot ".env"
$wikiEnv = Join-Path $WikiRoot ".env"
$dashboardData = Join-Path $projectRoot "data"
$wikiData = Join-Path $WikiRoot "data"

foreach ($envFile in @($dashboardEnv, $wikiEnv)) {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Configuration file required for ACL hardening was not found: $envFile"
    }
}
foreach ($dataDirectory in @($dashboardData, $wikiData)) {
    if (-not (Test-Path -LiteralPath $dataDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $dataDirectory | Out-Null
    }
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to apply an ACL outside an approved repository: $resolvedPath"
    }
}

Assert-ChildPath -Path $dashboardEnv -Root $projectRoot
Assert-ChildPath -Path $dashboardData -Root $projectRoot
Assert-ChildPath -Path $wikiEnv -Root $WikiRoot
Assert-ChildPath -Path $wikiData -Root $WikiRoot

$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$administratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")

function Set-RestrictedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][Security.AccessControl.FileSystemRights]$SystemRights,
        [switch]$Directory
    )

    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }

    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    $propagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $rules = @(
        [Security.AccessControl.FileSystemAccessRule]::new(
            $systemSid, $SystemRights, $inheritance, $propagation, $allow
        )
        [Security.AccessControl.FileSystemAccessRule]::new(
            $administratorsSid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        )
        [Security.AccessControl.FileSystemAccessRule]::new(
            $currentSid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        )
    )
    foreach ($rule in $rules) {
        [void]$acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

foreach ($envFile in @($dashboardEnv, $wikiEnv)) {
    Set-RestrictedAcl -Path $envFile -SystemRights Read
}
foreach ($dataDirectory in @($dashboardData, $wikiData)) {
    Set-RestrictedAcl -Path $dataDirectory -SystemRights Modify -Directory
    Get-ChildItem -LiteralPath $dataDirectory -Force -Recurse | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to apply an ACL through a reparse point: $($_.FullName)"
        }
        Assert-ChildPath -Path $_.FullName -Root $dataDirectory
        if ($_.PSIsContainer) {
            Set-RestrictedAcl -Path $_.FullName -SystemRights Modify -Directory
        } else {
            Set-RestrictedAcl -Path $_.FullName -SystemRights Modify
        }
    }
}

Write-Host "Runtime secret and SQLite ACL hardening completed."
