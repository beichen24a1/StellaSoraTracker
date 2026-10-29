@echo off
setlocal
rem Keep Windows PowerShell independent of a parent PowerShell 7 session.
set "PSModulePath="
set "ELECTRON_RUN_AS_NODE="
set "NODE_OPTIONS="
set "VITE_DEV_SERVER_URL="
cd /d "%~dp0"
if errorlevel 1 exit /b 1
echo Starting StellaSoraTracker from source...
echo The current UI will be built before opening the app.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "STELLA_LAUNCH_EXIT=%ERRORLEVEL%"
if not "%STELLA_LAUNCH_EXIT%"=="0" (
  echo.
  echo Source launch failed. Please read the error above.
  pause
)
exit /b %STELLA_LAUNCH_EXIT%
