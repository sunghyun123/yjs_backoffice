[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$taskName = "YJS Management Dashboard"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $taskName
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    } while ($task.State -eq "Running" -and (Get-Date) -lt $deadline)
    if ($task.State -eq "Running") {
        throw "Dashboard task did not stop within 15 seconds."
    }
}

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 1
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -ne "Running") {
    throw "Dashboard task did not start."
}
Write-Host "Dashboard scheduled task restarted."
