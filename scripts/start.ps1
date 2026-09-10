$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup.ps1 first to install Python dependencies.' }
$taskReady = $false
try {
    $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 2
    $taskReady = $null -ne $taskStatus.profiles
} catch {}
if (-not $taskReady) {
    $taskData = Join-Path $taskRoot 'data'
    New-Item -ItemType Directory -Path $taskData -Force | Out-Null
    Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','studio.app:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskData 'server-output.log') -RedirectStandardError (Join-Path $taskData 'server-error.log') | Out-Null
    for ($taskAttempt=0; $taskAttempt -lt 60; $taskAttempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 2
            if ($null -ne $taskStatus.profiles) { $taskReady=$true; break }
        } catch {}
    }
}
if (-not $taskReady) { throw 'Server did not start. See data/server-error.log.' }
Start-Process 'http://127.0.0.1:8765'
