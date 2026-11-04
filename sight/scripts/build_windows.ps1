[CmdletBinding()]
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $sourceRoot -Parent
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot '.cache\windows-release' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$cacheRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.cache')) + [IO.Path]::DirectorySeparatorChar
if (-not $OutputDirectory.StartsWith($cacheRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must be a directory inside this checkout .cache; copy the verified release elsewhere afterwards.'
}
$python = Join-Path $sourceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install the pinned backend and optional desktop requirements first.' }
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'frontend\dist\index.html'))) { throw 'Build frontend first: npm ci; npm run build' }
Push-Location $sourceRoot
try {
    function Get-BelSourceManifest {
        $paths = @((Join-Path $sourceRoot 'sight_core'), (Join-Path $sourceRoot 'packaging'), (Join-Path $repoRoot 'frontend\dist'))
        $rows = foreach ($path in $paths) {
            Get-ChildItem -LiteralPath $path -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' } | ForEach-Object {
                [ordered]@{path=[IO.Path]::GetRelativePath($repoRoot,$_.FullName); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
            }
        }
        return ($rows | Sort-Object { $_.path } | ConvertTo-Json -Depth 4 -Compress)
    }
    $sourceBefore = Get-BelSourceManifest
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed' }
    # An interrupted incremental build can cache an old hidden worker after the
    # source changed mid-analysis. Use a new isolated work tree for every build.
    $buildWork = Join-Path $repoRoot ('.cache\builds\' + [Guid]::NewGuid().ToString('N'))
    & $python -m PyInstaller --noconfirm --distpath $OutputDirectory --workpath $buildWork (Join-Path $sourceRoot 'packaging\BEL.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
    if ((Get-BelSourceManifest) -cne $sourceBefore) { throw 'Source changed during packaging. This artifact is not qualified; rebuild from a stable source tree.' }
    $releaseRoot = Join-Path $OutputDirectory 'BEL'
    & $python (Join-Path $PSScriptRoot 'verify_frozen_source.py') $releaseRoot
    if ($LASTEXITCODE -ne 0) { throw 'Packaged Python code differs from the current source' }
    $manifest = Get-ChildItem -LiteralPath $releaseRoot -File -Recurse | ForEach-Object {
        [ordered]@{path=[IO.Path]::GetRelativePath($releaseRoot, $_.FullName); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    [ordered]@{format=1; product='BEL'; platform='Windows x64'; sources=($sourceBefore | ConvertFrom-Json); files=@($manifest)} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'BEL-manifest.json') -Encoding utf8
    Write-Output "Built $releaseRoot\BEL.exe. Keep BEL-worker.exe and _internal beside it."
} finally { Pop-Location }
