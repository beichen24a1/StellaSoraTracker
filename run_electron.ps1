param([switch]$Offline, [string]$Output)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location (Join-Path $projectRoot 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
    & node .\node_modules\electron\install.js
    if ($LASTEXITCODE -ne 0) { throw 'Electron runtime installation failed' }
    $env:STELLA_PROFILE = Join-Path $projectRoot 'build\electron-preview-profile'
    if ($Output) { $env:STELLA_OUTPUT = [IO.Path]::GetFullPath($Output) }
    if ($Offline) { $env:STELLA_OFFLINE = '1' } else { Remove-Item Env:STELLA_OFFLINE -ErrorAction SilentlyContinue }
    & .\node_modules\.bin\electron.cmd .
    exit $LASTEXITCODE
} finally { Pop-Location }
