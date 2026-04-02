param(
    [string]$RemoteAlias = "t3610",
    [switch]$SkipRemote,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-HttpHealth {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSec = 4
    )

    try {
        $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec $TimeoutSec -UseBasicParsing
        return [PSCustomObject]@{
            Name = $Name
            Url = $Url
            Status = [int]$resp.StatusCode
            Healthy = ([int]$resp.StatusCode -eq 200)
            Detail = "OK"
        }
    }
    catch {
        $status = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode.value__
        }
        return [PSCustomObject]@{
            Name = $Name
            Url = $Url
            Status = $status
            Healthy = $false
            Detail = $_.Exception.Message
        }
    }
}

$localChecks = @(
    @{ Name = "Tunnel FusionAL"; Url = "http://localhost:18009/health" },
    @{ Name = "Tunnel BI"; Url = "http://localhost:18101/health" },
    @{ Name = "Tunnel API"; Url = "http://localhost:18102/health" },
    @{ Name = "Tunnel Content"; Url = "http://localhost:18103/health" },
    @{ Name = "Tunnel Intel"; Url = "http://localhost:18104/health" },
    @{ Name = "Tunnel llama"; Url = "http://localhost:18080/health" }
)

$localResults = foreach ($check in $localChecks) {
    Test-HttpHealth -Name $check.Name -Url $check.Url
}

if (-not $Quiet) {
    Write-Host ""
    Write-Host "=== Local Tunnel Health ===" -ForegroundColor Cyan
    $localResults | Select-Object Name, Status, Healthy, Url | Format-Table -AutoSize
}

$kbRoot = ""
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    $kbLine = Select-String -Path $envPath -Pattern '^KNOWLEDGE_BASE_ROOT=' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($kbLine) {
        $kbRoot = ($kbLine.Line -split '=', 2)[1].Trim()
    }
}

$kbStatus = [PSCustomObject]@{
    KbRoot = $kbRoot
    Status = "NOT_CONFIGURED"
    StatusFile = ""
    PrioritiesFile = ""
}

if (-not [string]::IsNullOrWhiteSpace($kbRoot)) {
    $expandedKb = [Environment]::ExpandEnvironmentVariables($kbRoot)
    $statusFile = Join-Path $expandedKb "00-CURRENT-STATUS\STATUS.md"
    $prioritiesFile = Join-Path $expandedKb "00-CURRENT-STATUS\PRIORITIES.md"

    $hasStatus = Test-Path $statusFile
    $hasPriorities = Test-Path $prioritiesFile

    $kbStatus = [PSCustomObject]@{
        KbRoot = $expandedKb
        Status = if ($hasStatus -and $hasPriorities) { "READY" } else { "MISSING_FILES" }
        StatusFile = if ($hasStatus) { "OK" } else { "MISSING" }
        PrioritiesFile = if ($hasPriorities) { "OK" } else { "MISSING" }
    }
}

if (-not $Quiet) {
    Write-Host ""
    Write-Host "=== Knowledge Base Context ===" -ForegroundColor Cyan
    $kbStatus | Format-List
}

if (-not $SkipRemote) {
    Write-Host ""
    Write-Host "=== Remote Quick Status ($RemoteAlias) ===" -ForegroundColor Cyan
    $remoteCmd = "echo -n '8101:'; curl -fsS --max-time 4 http://127.0.0.1:8101/health >/dev/null 2>/dev/null && echo OK || echo DOWN; echo -n '8102:'; curl -fsS --max-time 4 http://127.0.0.1:8102/health >/dev/null 2>/dev/null && echo OK || echo DOWN; echo -n '8103:'; curl -fsS --max-time 4 http://127.0.0.1:8103/health >/dev/null 2>/dev/null && echo OK || echo DOWN; echo -n '8104:'; curl -fsS --max-time 4 http://127.0.0.1:8104/health >/dev/null 2>/dev/null && echo OK || echo DOWN; echo -n '8089:'; curl -fsS --max-time 4 http://127.0.0.1:8089/health >/dev/null 2>/dev/null && echo OK || echo DOWN; echo -n '8080:'; curl -fsS --max-time 4 http://127.0.0.1:8080/health >/dev/null 2>/dev/null && echo OK || echo DOWN"
    try {
        ssh $RemoteAlias "bash -lc \"$remoteCmd\""
    }
    catch {
        Write-Host "Remote check failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

$down = @($localResults | Where-Object { -not $_.Healthy })
if ($down.Count -gt 0) {
    Write-Host ""
    Write-Host "Stack status: DEGRADED" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Stack status: HEALTHY" -ForegroundColor Green
exit 0
