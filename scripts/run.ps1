# Start the PS-16 backend on 127.0.0.1 (Windows PowerShell).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $isolatedPython = Join-Path $env:LOCALAPPDATA "ps16-backend-venv\Scripts\python.exe"
    if (Test-Path $isolatedPython) { $py = $isolatedPython }
}
if (-not (Test-Path $py)) { throw "No .venv found. See README: py -3.10 -m venv .venv" }
if (-not (Test-Path (Join-Path $root ".env"))) { Write-Warning "No .env; copy .env.example and fill in keys" }
Set-Location $root
& $py -m app.main
