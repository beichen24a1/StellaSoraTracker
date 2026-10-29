# Prepare a source checkout without requiring Python virtualenv or npm knowledge.
param([Parameter(Mandatory = $true)][string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
    throw '请先安装 Node.js 22.12 或更高版本（建议官网 LTS，保留默认选项）：https://nodejs.org/zh-cn/download 。安装完成后重新双击“从源码启动.cmd”。'
}
$nodeVersion = & $node.Source --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.(\d+)') {
    throw '无法运行 Node.js，请从 https://nodejs.org/zh-cn/download 重新安装 LTS 后重试。'
}
if ([int]$Matches[1] -lt 22 -or ([int]$Matches[1] -eq 22 -and [int]$Matches[2] -lt 12)) {
    throw 'Node.js 版本过旧，需要 22.12 或更高版本。请从 https://nodejs.org/zh-cn/download 安装 LTS 后重新启动。'
}

$venv = Join-Path $ProjectRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (Test-Path -LiteralPath $venv) {
        throw '.venv 目录已存在，但没有可用的 Python。请先将该目录重命名为 .venv-old，再重新启动；不要移动 exports 数据目录。'
    }
    $launcher = $null
    $prefix = @()
    foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
        $candidate = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $candidate) { continue }
        $candidatePrefix = @()
        if ($name -eq 'py.exe') { $candidatePrefix = @('-3') }
        try {
            & $candidate.Source @candidatePrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $launcher = $candidate.Source
                $prefix = $candidatePrefix
                break
            }
        } catch { continue }
    }
    if (-not $launcher) {
        throw '请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/windows/ 。安装时勾选 Add python.exe to PATH，保留 Python Launcher，然后重新双击“从源码启动.cmd”。'
    }
    Write-Host '[1/4] 正在为本仓库创建独立 Python 环境……'
    & $launcher @prefix -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败，请查看上面的错误信息。' }
}
& $python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw '仓库的 .venv 无法运行，或 Python 低于 3.10。请将 .venv 重命名后重新启动。' }

$pythonStamp = Join-Path $venv '.stellasora-source-dependencies.sha256'
$pythonHash = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'pyproject.toml') -Algorithm SHA256).Hash
$preparePython = -not (Test-Path -LiteralPath $pythonStamp)
if (-not $preparePython) { $preparePython = ([IO.File]::ReadAllText($pythonStamp).Trim() -ne $pythonHash) }
if (-not $preparePython) {
    try {
        & $python -c 'import PIL, stellasora_toolkit.desktop_engine' 2>$null
        $preparePython = $LASTEXITCODE -ne 0
    } catch { $preparePython = $true }
}
if ($preparePython) {
    Write-Host '[2/4] 正在安装 Python 项目依赖，首次启动需要联网……'
    & $python -m pip --disable-pip-version-check install -e $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败。请确认网络可用，保留窗口中的错误信息，恢复网络后重新双击即可重试。' }
    & $python -c 'import PIL, stellasora_toolkit.desktop_engine'
    if ($LASTEXITCODE -ne 0) { throw 'Python 项目依赖验证失败，请保留上面的错误信息。' }
    [IO.File]::WriteAllText($pythonStamp, $pythonHash)
}
$env:STELLA_PYTHON = $python

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    $nodeStamp = Join-Path $PWD.Path 'node_modules\.stellasora-source-dependencies.sha256'
    $nodeHash = ((Get-FileHash -LiteralPath 'package.json','package-lock.json' -Algorithm SHA256).Hash -join ':')
    $prepareNode = -not (Test-Path -LiteralPath 'node_modules')
    if (-not $prepareNode) {
        if (Test-Path -LiteralPath $nodeStamp) {
            $prepareNode = ([IO.File]::ReadAllText($nodeStamp).Trim() -ne $nodeHash)
        } else {
            # Keep an existing healthy developer install, including a running Electron binary.
            & $npm.Source ls --depth=0 --silent *> $null
            $prepareNode = $LASTEXITCODE -ne 0
        }
    }
    if ($prepareNode) {
        Write-Host '[3/4] 正在安装界面依赖，首次下载可能需要几分钟，请不要关闭窗口……'
        & $npm.Source ci
        if ($LASTEXITCODE -ne 0) { throw '界面依赖安装失败。请检查网络；如提示文件被占用，先关闭本目录启动的源码版，再重新双击重试。' }
    }
    [IO.File]::WriteAllText($nodeStamp, $nodeHash)
} finally { Pop-Location }
