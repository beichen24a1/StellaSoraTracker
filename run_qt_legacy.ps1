param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try { & .\.venv\Scripts\python.exe -m stellasora_toolkit.gui @args; exit $LASTEXITCODE } finally { Pop-Location }
