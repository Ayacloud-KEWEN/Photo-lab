# Starts LUMEN Studio (release build) for everyday use / trying it out.
#
# - First run: prepares the environment (scripts\setup.ps1) if needed.
# - Builds the optimized desktop app when it is missing or the source changed.
# - Starts it with the project's Python backend (backend\.venv); the bundled
#   backend executable for installers is a later packaging step.
#
# Usage: double-click the "... LUMEN Studio.cmd" launcher in the project folder, or
#   powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 [-Rebuild]
param([switch]$Rebuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $root "desktop"
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$exe = Join-Path $desktop "src-tauri\target\release\lumen-studio.exe"

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

# 1. Environment
if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $desktop "node_modules"))) {
    Write-Step "First run: preparing the development environment"
    & (Join-Path $PSScriptRoot "setup.ps1")
}

# 2. Build when the app is missing or any frontend/desktop source is newer than it.
$needsBuild = $Rebuild -or -not (Test-Path $exe)
if (-not $needsBuild) {
    $built = (Get-Item $exe).LastWriteTimeUtc
    $sources = @(
        Get-ChildItem (Join-Path $desktop "src"), (Join-Path $desktop "src-tauri\src") -Recurse -File
        Get-Item (Join-Path $desktop "src-tauri\tauri.conf.json"), (Join-Path $desktop "src-tauri\Cargo.toml"),
                 (Join-Path $desktop "package.json"), (Join-Path $desktop "index.html")
    )
    $newer = $sources | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1
    if ($newer) {
        Write-Host "Source changed since the last build: $($newer.Name)"
        $needsBuild = $true
    }
}
if ($needsBuild) {
    Write-Step "Building LUMEN Studio (the first build takes several minutes)"
    Push-Location $desktop
    # Build tools print progress and warnings on stderr; judge success by exit code only.
    $ErrorActionPreference = "Continue"
    try {
        npm run tauri build -- --no-bundle
        if ($LASTEXITCODE -ne 0) { throw "Build failed (exit code $LASTEXITCODE)" }
    } finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
}

# 3. Optional tools: the app runs without them, with reduced features.
foreach ($tool in "exiftool", "ffmpeg", "ffprobe") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Warning "$tool not found on PATH: photo metadata / video thumbnails will be limited."
    }
}

# 4. Start. The backend's Python comes from the project's virtual environment.
Write-Step "Starting LUMEN Studio"
$env:LUMEN_BACKEND_PYTHON = $python
# Quieter logs from the AI libraries (Windows cannot create the symlinks HF prefers).
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:TRANSFORMERS_VERBOSITY = "error"
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
