# T+0 Monitor - Stop Script
# Read PID file and gracefully terminate the monitor process
# Usage: powershell -ExecutionPolicy Bypass -File t0_stop.ps1

$ErrorActionPreference = "SilentlyContinue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFilePath = Join-Path $scriptDir "data\t0-monitor.pid"
$logFilePath = Join-Path $scriptDir "data\t0-monitor.log"

function Write-Log {
    param([string]$msg)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $msg"
    Write-Host $line
    try {
        Add-Content -Path $logFilePath -Value $line -Encoding UTF8
    } catch {
        # Ignore log write failures
    }
}

# Check PID file
if (-not (Test-Path $pidFilePath)) {
    Write-Log "PID file not found, searching by process name..."

    $procs = Get-WmiObject Win32_Process | Where-Object {
        $_.CommandLine -like "*t0_monitor*" -and $_.Name -like "python*"
    }

    if ($procs) {
        foreach ($proc in $procs) {
            Write-Log "Found process PID:$($proc.ProcessId)"
            Stop-Process -Id $proc.ProcessId -Force
            Write-Log "Terminated process PID:$($proc.ProcessId)"
        }
    } else {
        Write-Log "No running T+0 monitor process found"
    }
    exit 0
}

# Read PID
$targetPid = (Get-Content $pidFilePath -Raw).Trim()

if ([string]::IsNullOrEmpty($targetPid)) {
    Write-Log "PID file is empty, cleaning up"
    Remove-Item $pidFilePath -Force
    exit 0
}

# Check if process exists
$running = Get-Process -Id $targetPid -ErrorAction SilentlyContinue

if ($running) {
    Write-Log "Terminating T+0 monitor process PID:$targetPid ..."
    Stop-Process -Id $targetPid -Force
    Start-Sleep -Milliseconds 500

    $stillRunning = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if ($stillRunning) {
        Write-Log "Process did not terminate gracefully, force kill"
        Stop-Process -Id $targetPid -Force
    } else {
        Write-Log "T+0 monitor process terminated (PID:$targetPid)"
    }
} else {
    Write-Log "Process PID:$targetPid no longer exists, cleaning PID file"
}

# Clean up PID file
Remove-Item $pidFilePath -Force -ErrorAction SilentlyContinue
Write-Log "PID file cleaned up"