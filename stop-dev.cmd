@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Optional: stop-dev.cmd -SkipScrape

echo [NextWeb] Stopping via PowerShell...
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-dev.ps1" %*
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo [ERROR] stop-dev.ps1 failed. code=%EC%
  pause
  exit /b %EC%
)
exit /b 0
