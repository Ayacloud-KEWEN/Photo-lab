# Prepares a development environment: Python venv + backend deps, frontend deps.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Backend: creating virtual environment" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try {
    if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
} finally { Pop-Location }

Write-Host "==> Desktop: installing npm packages" -ForegroundColor Cyan
Push-Location (Join-Path $root "desktop")
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
} finally { Pop-Location }

Write-Host "==> Done. Start the app with: scripts\dev.ps1" -ForegroundColor Green
