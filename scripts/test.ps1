# Runs every check: backend lint/types/tests, frontend types/tests, Rust lint.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\test.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Step($title, [scriptblock]$block) {
    Write-Host "==> $title" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$title failed" }
}

Push-Location (Join-Path $root "backend")
try {
    $py = ".\.venv\Scripts\python.exe"
    Step "backend: ruff" { & $py -m ruff check . }
    Step "backend: mypy" { & $py -m mypy }
    Step "backend: pytest" { & $py -m pytest }
} finally { Pop-Location }

Push-Location (Join-Path $root "desktop")
try {
    Step "desktop: typecheck" { npm run typecheck }
    Step "desktop: vitest" { npm test }
} finally { Pop-Location }

Push-Location (Join-Path $root "desktop\src-tauri")
try {
    Step "tauri: clippy" { cargo clippy --all-targets -- -D warnings }
} finally { Pop-Location }

Write-Host "==> All checks passed" -ForegroundColor Green
