param([switch]$Enable)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$TaskName = "ValuehireFleetWorker"

if (-not (Test-Path -LiteralPath $Python)) { throw "Repository venv Python is missing" }

$required = @("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DISCORD_BOT_TOKEN")
$missing = @($required | Where-Object {
    -not [Environment]::GetEnvironmentVariable($_, "User") -and
    -not [Environment]::GetEnvironmentVariable($_, "Process")
})
if ($Enable -and $missing.Count -gt 0) {
    throw "Required user secret variables are missing; task was not enabled"
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"" +
    "Set-Location -LiteralPath '$Repo'; " +
    "`$env:VALUEHIRE_MACHINE='winpc'; " +
    "& '$Python' -m tools.multi_position_sourcing.fleet_worker`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
if ($Enable) { Enable-ScheduledTask -TaskName $TaskName | Out-Null }
else { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
