param([switch]$Offline, [string]$Wheelhouse, [string]$BrowserCache)
$ErrorActionPreference = "Stop"
$sightRoot = Split-Path -Parent $PSScriptRoot
$sightIndexArgs = @()
# Explicit relative paths belong to the caller, before entering the source tree.
if ($Offline) {
    if (-not $Wheelhouse) { $Wheelhouse = Join-Path (Split-Path -Parent $sightRoot) 'offline\wheels' }
    if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) { throw 'Offline installation requires the provisioned, hash-verified wheel directory.' }
    $sightIndexArgs = @('--no-index', '--find-links', (Resolve-Path -LiteralPath $Wheelhouse).Path)
}
if ($BrowserCache) {
    if (-not (Test-Path -LiteralPath $BrowserCache -PathType Container)) { throw 'BrowserCache must be a provisioned browser directory.' }
    $BrowserCache = (Resolve-Path -LiteralPath $BrowserCache).Path
}
Push-Location -LiteralPath $sightRoot
try {
    if ($BrowserCache) { $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCache }
    $sightPython = Join-Path $sightRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $sightPython)) {
        py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Python 3.12 venv creation failed" }
    }
    & $sightPython -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes @sightIndexArgs -r requirements-bootstrap.lock
    if ($LASTEXITCODE -ne 0) { throw "Hash-verified installer bootstrap failed" }
    & $sightPython -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes @sightIndexArgs -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Hash-verified dependency installation failed" }
    & $sightPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
    if ($Offline) {
        & $sightPython -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); exists=Path(p.chromium.executable_path).is_file(); p.stop(); raise SystemExit(0 if exists else 1)"
        if ($LASTEXITCODE -ne 0) { throw 'Chromium is not provisioned. Supply a matching BrowserCache or install it online before going offline.' }
    } else {
        & $sightPython -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "Browser test prerequisite installation failed" }
    }
    & $sightPython -m sight_core.cli doctor
    $sightExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $sightExit
