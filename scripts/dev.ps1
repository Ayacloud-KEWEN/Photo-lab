# Runs LUMEN Studio in development mode (Vite + Tauri; Tauri starts the Python backend).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $root "desktop")
try {
    npm run tauri dev
} finally { Pop-Location }
