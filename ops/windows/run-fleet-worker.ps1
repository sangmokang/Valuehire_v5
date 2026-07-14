$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $Repo "artifacts\fleet"
$LogPath = Join-Path $LogDirectory "winpc-worker.log"

if (-not (Test-Path -LiteralPath $Python)) { throw "Repository venv Python is missing" }

# Keep repository .env out of global Python import paths. Only this Windows worker
# receives the exact queue/report variables it needs, with .env.local taking priority.
$allowed = @(
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DISCORD_BOT_TOKEN",
    "DISCORD_WEBHOOK_URL_OPS_HEALTH",
    "FLEET_REPORT_CHANNEL",
    "VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT"
)
foreach ($fileName in @(".env.local", ".env")) {
    $envFile = Join-Path $Repo $fileName
    if (-not (Test-Path -LiteralPath $envFile)) { continue }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        if ($line -notmatch "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") { continue }
        $name = $matches[1]
        if ($allowed -notcontains $name -or (Test-Path "Env:$name")) { continue }
        $value = $matches[2].Trim().Trim('"').Trim("'")
        if ($value) { Set-Item -Path "Env:$name" -Value $value }
    }
}

$env:VALUEHIRE_MACHINE = "winpc"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Set-Location -LiteralPath $Repo
# Windows PowerShell wraps native stderr as ErrorRecord. Fleet auth/network errors are
# deliberately fail-soft and must reach the worker's own retry loop instead of stopping
# this wrapper after the first diagnostic line.
$ErrorActionPreference = "Continue"
& $Python -m tools.multi_position_sourcing.fleet_worker *>> $LogPath
exit $LASTEXITCODE
