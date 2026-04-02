param(
    [string]$TaskName = "Christopher-Remote-Tunnel",
    [string]$RemoteAlias = "t3610",
    [string]$RunAsUser = $env:USERNAME,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupScript = Join-Path $scriptDir "start-remote-tunnels.ps1"

if (-not (Test-Path $startupScript)) {
    throw "Missing startup script: $startupScript"
}

function Invoke-Schtasks {
    param(
        [string[]]$SchtasksArgs,
        [switch]$AllowFailure
    )

    $result = (& schtasks.exe @SchtasksArgs 2>&1 | ForEach-Object { $_.ToString() }) -join "`r`n"
    $code = $LASTEXITCODE

    if (($code -ne 0) -and (-not $AllowFailure)) {
        throw "schtasks.exe failed (exit $code): $result"
    }

    return $result
}

if ($Uninstall) {
    Invoke-Schtasks -SchtasksArgs @("/Delete", "/TN", $TaskName, "/F") -AllowFailure | Out-Null
    Write-Host "Removed task (if existed): $TaskName"
    exit 0
}

$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startupScript`" -RemoteAlias $RemoteAlias"

$deleteResult = Invoke-Schtasks -SchtasksArgs @("/Delete", "/TN", $TaskName, "/F") -AllowFailure
if ($deleteResult) {
    Write-Host $deleteResult
}

$createResult = Invoke-Schtasks -SchtasksArgs @("/Create", "/TN", $TaskName, "/SC", "ONLOGON", "/RU", $RunAsUser, "/TR", $taskCommand, "/F")
if ($createResult) {
    Write-Host $createResult
}

Write-Host "Installed task: $TaskName"
Write-Host "Trigger: At logon"
Write-Host "Action: $taskCommand"
Write-Host ""
Write-Host "Quick checks:"
Write-Host "  schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "  schtasks /Run /TN `"$TaskName`""
