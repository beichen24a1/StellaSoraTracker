param([switch]$SkipFrontend, [switch]$SkipEngine)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Create the project Python environment first.' }
    if (-not $SkipFrontend) {
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            if (-not (Test-Path -LiteralPath node_modules)) { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
        } finally { Pop-Location }
    }
    if (-not $SkipEngine) {
        $originalPath = $env:PATH
        try {
            $env:PATH = @((Split-Path -Parent $python), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join [IO.Path]::PathSeparator
            & $python -m PyInstaller --noconfirm --clean --onedir --console --name StellaSoraEngine --exclude-module PySide6 --exclude-module PyQt6 --exclude-module tkinter --distpath build/electron-engine --workpath build/electron-engine-work --specpath build launcher_engine.py
            if ($LASTEXITCODE -ne 0) { throw 'Python engine build failed' }
            & $python -m PyInstaller --noconfirm --clean StellaSoraUpdater.spec
            if ($LASTEXITCODE -ne 0) { throw 'Updater build failed' }
            & $python -m PyInstaller --noconfirm --clean StellaSoraLauncher.spec
            if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
        } finally { $env:PATH = $originalPath }
    }
    & $python tools/write_third_party_notices.py
    if ($LASTEXITCODE -ne 0) { throw 'Third-party notices generation failed' }
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        $env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
        $env:ELECTRON_BUILDER_CACHE = Join-Path $projectRoot 'build\electron-builder-cache'
        & npm.cmd run package:dir
        if ($LASTEXITCODE -ne 0) { throw 'Electron packaging failed' }
    } finally { Pop-Location }
    & $python tools/pack_electron_local.py
    if ($LASTEXITCODE -ne 0) { throw 'Local ZIP packaging failed' }
} finally { Pop-Location }
