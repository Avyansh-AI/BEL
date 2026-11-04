$ErrorActionPreference = 'Stop'
$belPython = Join-Path $PSScriptRoot 'sight\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $belPython)) { throw 'Install the pinned requirements first.' }
Push-Location (Join-Path $PSScriptRoot 'sight')
try {
    & $belPython -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend regression tests failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
