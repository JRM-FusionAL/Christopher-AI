# ================================
# PulseAudio for Windows Installer
# Using pgaskin/pulseaudio-win32
# ================================

$ErrorActionPreference = "Stop"

Write-Host "=== PulseAudio for Windows Installer ===" -ForegroundColor Cyan

# --- Target directory ---
$target = "C:\PulseAudio"
if (!(Test-Path $target)) {
    Write-Host "Creating $target..."
    New-Item -ItemType Directory -Path $target | Out-Null
}

# --- Download PulseAudio-win32 release list ---
Write-Host "Fetching PulseAudio releases..."

$releaseApi = "https://api.github.com/repos/pgaskin/pulseaudio-win32/releases"
$releases = Invoke-RestMethod -Uri $releaseApi

if (-not $releases) {
    throw "No releases found for pgaskin/pulseaudio-win32."
}

# Pick the newest release with a ZIP asset
$asset = $releases[0].assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1

if (-not $asset) {
    throw "No ZIP assets found in the latest release."
}

$zipPath = "$env:TEMP\pulseaudio.zip"
Write-Host "Downloading $($asset.name)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

Write-Host "Extracting..."
Expand-Archive -Path $zipPath -DestinationPath $target -Force

# --- Write config.pa ---
Write-Host "Writing config.pa..."
@"
### PulseAudio minimal config for WSL2
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1
load-module module-esound-protocol-tcp auth-ip-acl=127.0.0.1
daemonize = no
set-default-sink 0
"@ | Set-Content "$target\config.pa"

# --- Write daemon.conf ---
Write-Host "Writing daemon.conf..."
@"
daemonize = no
fail = yes
high-priority = yes
nice-level = -11
realtime-scheduling = no
exit-idle-time = -1
"@ | Set-Content "$target\daemon.conf"

# --- Write start script ---
Write-Host "Creating start-pulseaudio.cmd..."
@"
@echo off
title PulseAudio for WSL2
cd /d %~dp0
echo Starting PulseAudio...
pulseaudio.exe -F config.pa -n
"@ | Set-Content "$target\start-pulseaudio.cmd"

# --- Add to PATH if missing ---
$path = [Environment]::GetEnvironmentVariable("Path", "User")
if ($path -notlike "*C:\PulseAudio*") {
    Write-Host "Adding C:\PulseAudio to PATH..."
    [Environment]::SetEnvironmentVariable("Path", "$path;C:\PulseAudio", "User")
}

Write-Host "PulseAudio installation complete!" -ForegroundColor Green
Write-Host "Run C:\PulseAudio\start-pulseaudio.cmd before using WSL2 audio."