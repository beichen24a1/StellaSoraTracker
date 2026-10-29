param([switch]$Offline, [string]$Output)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
& (Join-Path $projectRoot 'tools\prepare_source.ps1') -ProjectRoot $projectRoot
Push-Location (Join-Path $projectRoot 'frontend')
try {
    Write-Host '[4/4] Building the latest UI and starting Electron...'
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
    Write-Host '正在准备 Electron 运行环境，首次需要下载。已有缓存时会直接复用。'
    $downloadEnvironment = @{}
    foreach ($key in @('HTTPS_PROXY','ELECTRON_GET_USE_PROXY')) {
        $downloadEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
    }
    try {
        if (-not $env:HTTPS_PROXY -and -not $env:HTTP_PROXY) {
            # The Node downloader does not read Windows proxy settings by itself.
            $origin = [Uri]'https://github.com'
            $proxy = [Net.WebRequest]::GetSystemWebProxy().GetProxy($origin)
            if ($proxy -and $proxy.Authority -ne $origin.Authority) {
                $env:HTTPS_PROXY = $proxy.AbsoluteUri
                Write-Host 'Electron 下载将复用 Windows 已配置的系统代理。'
            }
        }
        if ($env:HTTPS_PROXY -or $env:HTTP_PROXY) { $env:ELECTRON_GET_USE_PROXY = '1' }
        & node .\node_modules\electron\install.js
        if ($LASTEXITCODE -ne 0) { throw 'Electron 运行环境准备失败，请检查网络或系统代理，恢复网络后重新双击即可重试。' }
    } finally {
        foreach ($key in $downloadEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $downloadEnvironment[$key], 'Process')
        }
    }
    $env:STELLA_PROFILE = Join-Path $projectRoot 'build\electron-preview-profile'
    if ($Output) { $env:STELLA_OUTPUT = [IO.Path]::GetFullPath($Output) }
    if ($Offline) { $env:STELLA_OFFLINE = '1' } else { Remove-Item Env:STELLA_OFFLINE -ErrorAction SilentlyContinue }
    & .\node_modules\.bin\electron.cmd .
    exit $LASTEXITCODE
} finally { Pop-Location }
