param(
    [string]$RemoteAlias = "t3610",
    [switch]$Voice,
    [switch]$SkipTunnelBootstrap,
    [switch]$SkipConfigUpdate,
    [switch]$NoKb
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$thisDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectsRoot = Split-Path -Parent $thisDir
$tunnelScript = Join-Path $projectsRoot "mcp-consulting-kit\scripts\start-claude-mcp-tunnel.ps1"
$healthScript = Join-Path $projectsRoot "mcp-consulting-kit\scripts\check-claude-mcp-health.ps1"

if (-not (Test-Path $tunnelScript)) {
    throw "Tunnel script not found: $tunnelScript"
}
if (-not (Test-Path $healthScript)) {
    throw "Health script not found: $healthScript"
}

if (-not $SkipTunnelBootstrap) {
    Write-Host "Bootstrapping remote MCP + llama tunnels..." -ForegroundColor Cyan
    & $tunnelScript -RemoteAlias $RemoteAlias -SkipLaunchClaude -IncludeLlama -SkipConfigUpdate:$SkipConfigUpdate
}

Write-Host "Validating tunneled MCP health..." -ForegroundColor Cyan
& $healthScript -UseTunnelPorts -Attempts 2

Write-Host "Validating tunneled llama health..." -ForegroundColor Cyan
$llama = Invoke-WebRequest -Uri "http://localhost:18080/health" -Method Get -TimeoutSec 6 -UseBasicParsing
if ([int]$llama.StatusCode -ne 200) {
    throw "Llama health check failed on localhost:18080 (status $([int]$llama.StatusCode))."
}

Push-Location $thisDir
try {
    if ($Voice) {
        if ($NoKb) {
            python christopher.py --voice --no-kb
        }
        else {
            python christopher.py --voice
        }
    }
    else {
        if ($NoKb) {
            python christopher.py --chat --no-kb
        }
        else {
            python christopher.py --chat
        }
    }
}
finally {
    Pop-Location
}
