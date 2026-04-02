param(
    [string]$RemoteAlias = "t3610",
    [switch]$ForceRestart,
    [switch]$SkipConfigUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectsRoot = Split-Path -Parent $scriptDir
$tunnelScript = Join-Path $projectsRoot "mcp-consulting-kit\scripts\start-claude-mcp-tunnel.ps1"

if (-not (Test-Path $tunnelScript)) {
    throw "Tunnel bootstrap script not found: $tunnelScript"
}

Write-Host "Starting remote MCP + llama tunnels via $RemoteAlias..." -ForegroundColor Cyan
& $tunnelScript -RemoteAlias $RemoteAlias -IncludeLlama -SkipLaunchClaude -ForceRestart:$ForceRestart -SkipConfigUpdate:$SkipConfigUpdate

Write-Host "Tunnel bootstrap complete." -ForegroundColor Green
