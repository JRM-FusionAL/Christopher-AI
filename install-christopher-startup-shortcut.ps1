param(
    [string]$RemoteAlias = "t3610",
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$startupDir = [Environment]::GetFolderPath("Startup")
$launcherPath = Join-Path $startupDir "Start-Christopher-Remote-Tunnels.cmd"
$scriptPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "start-remote-tunnels.ps1"

if ($Remove) {
    if (Test-Path $launcherPath) {
        Remove-Item $launcherPath -Force
        Write-Host "Removed startup launcher: $launcherPath"
    }
    else {
        Write-Host "Startup launcher not present: $launcherPath"
    }
    exit 0
}

if (-not (Test-Path $scriptPath)) {
    throw "Required script missing: $scriptPath"
}

$cmdContent = "@echo off`r`n" +
              "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" -RemoteAlias $RemoteAlias -SkipConfigUpdate >nul 2>&1`r`n"

Set-Content -Path $launcherPath -Value $cmdContent -Encoding ASCII

Write-Host "Installed startup launcher: $launcherPath"
Write-Host "Runs at login for current user and starts remote MCP+llama tunnels."
