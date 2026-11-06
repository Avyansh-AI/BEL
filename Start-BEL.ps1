[CmdletBinding()]
param([string]$DataDirectory, [switch]$Background, [switch]$LocalDictation)
$ErrorActionPreference = 'Stop'
$belPython = Join-Path $PSScriptRoot 'sight\.venv\Scripts\pythonw.exe'
$belEntry = Join-Path $PSScriptRoot 'sight\scripts\bel_desktop.py'
if (-not (Test-Path -LiteralPath $belPython)) { throw 'Install the backend and optional desktop requirements; see sight/docs/BEL_SETUP.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) { throw 'Build frontend first: npm ci and npm run build in frontend.' }
if (-not $DataDirectory) {
    if ($env:BEL_DATA_DIR) { $DataDirectory = $env:BEL_DATA_DIR }
    elseif ($env:SIGHT_DATA_DIR) { $DataDirectory = $env:SIGHT_DATA_DIR }
    else { $DataDirectory = Join-Path $PSScriptRoot 'owner-data' }
}
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
if ($DataDirectory.Contains('"') -or $DataDirectory -eq [IO.Path]::GetPathRoot($DataDirectory)) { throw 'Select a data folder below the drive root.' }
$belArguments = @(('"' + $belEntry + '"'), '--data-directory', ('"' + $DataDirectory.TrimEnd('\') + '"'))
if ($Background) { $belArguments += '--background' }
if ($LocalDictation) { $belArguments += '--local-dictation' }
Start-Process -FilePath $belPython -ArgumentList $belArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
