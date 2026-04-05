[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$DisableDellTelemetryServices,
    [string]$LogRoot = "$env:USERPROFILE\Desktop"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sessionDir = Join-Path $LogRoot "pc-performance-repair-$timestamp"
$null = New-Item -ItemType Directory -Path $sessionDir -Force
$logFile = Join-Path $sessionDir "repair.log"
$summaryFile = Join-Path $sessionDir "summary.txt"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    $line | Add-Content -Path $logFile -Encoding ASCII
    Write-Host $line
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [switch]$ContinueOnError
    )

    Write-Log ""
    Write-Log "=== $Name ==="

    if ($DryRun) {
        Write-Log "DRY RUN: skipped execution"
        return $true
    }

    try {
        & $Action
        Write-Log "OK: $Name"
        return $true
    }
    catch {
        Write-Log "ERROR: $Name -> $($_.Exception.Message)"
        if (-not $ContinueOnError) {
            throw
        }
        return $false
    }
}

function Invoke-CmdLogged {
    param([string]$CommandLine)
    Write-Log "Running: $CommandLine"
    $output = cmd.exe /c $CommandLine 2>&1
    foreach ($line in $output) {
        Write-Log "  $line"
    }
    Write-Log "ExitCode: $LASTEXITCODE"
    return $LASTEXITCODE
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-TopProcessSnapshot {
    param([string]$Label)

    Write-Log "$Label - Top memory processes"
    Get-Process |
        Sort-Object WS -Descending |
        Select-Object -First 12 ProcessName, Id, @{N = "WS_GB"; E = { [math]::Round($_.WS / 1GB, 2) } }, @{N = "PM_GB"; E = { [math]::Round($_.PM / 1GB, 2) } }, CPU |
        Format-Table -AutoSize |
        Out-String -Width 220 |
        ForEach-Object { $_.TrimEnd() } |
        ForEach-Object { if ($_ -ne "") { Write-Log "  $_" } }
}

$summary = New-Object System.Collections.Generic.List[string]
$summary.Add("Session directory: $sessionDir")
$summary.Add("DryRun: $DryRun")
$summary.Add("DisableDellTelemetryServices: $DisableDellTelemetryServices")

Write-Log "PC performance repair script started"
Write-Log "Session directory: $sessionDir"
Write-Log "DryRun=$DryRun DisableDellTelemetryServices=$DisableDellTelemetryServices"

$admin = Test-Admin
Write-Log "IsAdmin=$admin"
if (-not $admin -and -not $DryRun) {
    Write-Log "This script must be run in an elevated PowerShell session."
    Write-Log "Open PowerShell as Administrator, then run:"
    Write-Log "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    $summary.Add("Blocked: not running as admin")
    $summary | Set-Content -Path $summaryFile -Encoding ASCII
    exit 1
}

Invoke-Step -Name "Baseline snapshots" -ContinueOnError {
    Write-TopProcessSnapshot -Label "Before repairs"

    Write-Log "winmgmt service state"
    Get-Service winmgmt, RpcSs, DcomLaunch, EventLog |
        Select-Object Name, Status, StartType |
        Format-Table -AutoSize |
        Out-String -Width 220 |
        ForEach-Object { $_.TrimEnd() } |
        ForEach-Object { if ($_ -ne "") { Write-Log "  $_" } }

    $verifyExit = Invoke-CmdLogged "winmgmt /verifyrepository"
    $summary.Add("Initial verifyrepository exit code: $verifyExit")
}

if ($DisableDellTelemetryServices) {
    Invoke-Step -Name "Disable Dell telemetry services (optional)" -ContinueOnError {
        $serviceNames = @("DellTechHub", "SupportAssistAgent", "DellClientManagementService")
        foreach ($name in $serviceNames) {
            $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
            if ($null -eq $svc) {
                Write-Log "Service not found: $name"
                continue
            }

            Write-Log "Setting startup type Manual for $name"
            Set-Service -Name $name -StartupType Manual

            if ($svc.Status -eq "Running") {
                Write-Log "Stopping service: $name"
                Stop-Service -Name $name -Force -ErrorAction Continue
            }
        }
    }
}

Invoke-Step -Name "Restart WMI service" -ContinueOnError {
    $stopExit = Invoke-CmdLogged "net stop winmgmt /y"
    $startExit = Invoke-CmdLogged "net start winmgmt"
    $summary.Add("net stop winmgmt exit code: $stopExit")
    $summary.Add("net start winmgmt exit code: $startExit")
}

Invoke-Step -Name "Salvage WMI repository" -ContinueOnError {
    $salvageExit = Invoke-CmdLogged "winmgmt /salvagerepository"
    $summary.Add("salvagerepository exit code: $salvageExit")
}

Invoke-Step -Name "Verify WMI repository after salvage" -ContinueOnError {
    $verifyExitAfter = Invoke-CmdLogged "winmgmt /verifyrepository"
    $summary.Add("Post-salvage verifyrepository exit code: $verifyExitAfter")
}

Invoke-Step -Name "Timed CIM probe (20s)" -ContinueOnError {
    $job = Start-Job -ScriptBlock {
        Get-CimInstance Win32_OperatingSystem | Select-Object CSName, Version, LastBootUpTime
    }

    if (Wait-Job $job -Timeout 20) {
        $result = Receive-Job $job
        foreach ($line in ($result | Format-List | Out-String -Width 220).Split([Environment]::NewLine)) {
            if ($line.Trim() -ne "") {
                Write-Log "  $line"
            }
        }
        $summary.Add("CIM probe: success")
    }
    else {
        Write-Log "CIM probe timed out after 20 seconds"
        $summary.Add("CIM probe: timeout")
    }

    Remove-Job $job -Force -ErrorAction SilentlyContinue
}

Invoke-Step -Name "Collect recent WMI and DWM warnings (2h)" -ContinueOnError {
    $start = (Get-Date).AddHours(-2)

    Write-Log "WMI Activity errors"
    Get-WinEvent -FilterHashtable @{ LogName = "Microsoft-Windows-WMI-Activity/Operational"; StartTime = $start; Level = 2 } -MaxEvents 30 |
        Select-Object TimeCreated, Id, Message |
        Format-List |
        Out-String -Width 220 |
        ForEach-Object { $_.TrimEnd() } |
        ForEach-Object { if ($_ -ne "") { Write-Log "  $_" } }

    Write-Log "Application warnings for Dwminit"
    Get-WinEvent -FilterHashtable @{ LogName = "Application"; StartTime = $start } -MaxEvents 600 |
        Where-Object { $_.ProviderName -eq "Dwminit" -and $_.LevelDisplayName -in @("Warning", "Error") } |
        Select-Object -First 20 TimeCreated, Id, LevelDisplayName, Message |
        Format-List |
        Out-String -Width 220 |
        ForEach-Object { $_.TrimEnd() } |
        ForEach-Object { if ($_ -ne "") { Write-Log "  $_" } }
}

Invoke-Step -Name "Post-repair snapshot" -ContinueOnError {
    Write-TopProcessSnapshot -Label "After repairs"
}

$summary.Add("Log file: $logFile")
$summary.Add("Recommended next step: reboot after script completion")
$summary | Set-Content -Path $summaryFile -Encoding ASCII

Write-Log ""
Write-Log "Repair run completed"
Write-Log "Summary file: $summaryFile"
Write-Log "Recommended next step: reboot the PC, then re-check responsiveness."
