param(
    [string]$ProfileName = "Profile 2",
    [string]$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
)

$ErrorActionPreference = "Stop"
$portalUrls = @(
    "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    "https://www.jobkorea.co.kr/Corp/Person/Find"
)

if (-not (Test-Path -LiteralPath $ChromePath)) {
    throw "Chrome executable not found"
}

$profileRunning = Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" |
    Where-Object { $_.CommandLine -like "*--profile-directory=$ProfileName*" } |
    Select-Object -First 1

if ($profileRunning) {
    exit 0
}

# Chrome owns the persistent login data. Reopening the same profile preserves cookies
# and saved credentials; this task never deletes, copies, signs out, or resets it.
$arguments = @("--profile-directory=$ProfileName") + $portalUrls
Start-Process -FilePath $ChromePath -ArgumentList $arguments
