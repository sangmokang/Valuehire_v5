param([switch]$Enable)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$TaskName = "ValuehireFleetWorker"
$InteractiveUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Runner = Join-Path $PSScriptRoot "run-fleet-worker.ps1"

if (-not (Test-Path -LiteralPath $Python)) { throw "Repository venv Python is missing" }
if (-not (Test-Path -LiteralPath $Runner)) { throw "Windows fleet worker runner is missing" }

function Test-ConfiguredValue([string]$Name) {
    if ([Environment]::GetEnvironmentVariable($Name, "User") -or
        [Environment]::GetEnvironmentVariable($Name, "Process")) {
        return $true
    }
    foreach ($fileName in @(".env.local", ".env")) {
        $envFile = Join-Path $Repo $fileName
        if (Test-Path -LiteralPath $envFile) {
            $match = Get-Content -LiteralPath $envFile | Where-Object {
                $_ -match ("^\s*" + [regex]::Escape($Name) + "\s*=\s*\S+")
            } | Select-Object -First 1
            if ($match) { return $true }
        }
    }
    return $false
}

$queueReady = (Test-ConfiguredValue "NEXT_PUBLIC_SUPABASE_URL") -and
    (Test-ConfiguredValue "SUPABASE_SERVICE_ROLE_KEY")
$reportReady = (Test-ConfiguredValue "DISCORD_BOT_TOKEN") -or
    (Test-ConfiguredValue "DISCORD_WEBHOOK_URL_OPS_HEALTH")
if ($Enable -and (-not $queueReady -or -not $reportReady)) {
    throw "Queue credentials or a Discord report route are missing; task was not enabled"
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $InteractiveUser
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $InteractiveUser -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
if ($Enable) { Enable-ScheduledTask -TaskName $TaskName | Out-Null }
else { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
# The old fixed-period browser refresher violates the durable 3-7 minute profile pacing
# contract. Fleet/portal workers own browser timing; keep this legacy task disabled.
if ($Enable -and (Get-ScheduledTask -TaskName "ValuehirePortalKeepAlive" -ErrorAction SilentlyContinue)) {
    Disable-ScheduledTask -TaskName "ValuehirePortalKeepAlive" | Out-Null
}
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
