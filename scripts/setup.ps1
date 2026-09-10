param([string]$Python = $env:SPATIAL_PYTHON)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    if ($Python) { & $Python -m venv .venv }
    else { py -3.12 -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
}
& .venv/Scripts/python.exe -m pip install --index-url https://pypi.org/simple -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .venv/Scripts/python.exe scripts/setup_assets.py
if ($LASTEXITCODE -ne 0) { throw 'HRTF setup failed.' }
& .venv/Scripts/python.exe scripts/setup_recorded.py
if ($LASTEXITCODE -ne 0) { throw 'Foley setup failed.' }
