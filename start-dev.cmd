@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Optional flags forwarded to PowerShell, e.g.:
REM   start-dev.cmd -SkipScrape
REM   start-dev.cmd -NoBrowser
REM   start-dev.cmd -SkipScrape -NoBrowser

echo [NextWeb] Starting via PowerShell...
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1" %*
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" if not "%EC%"=="2" (
  echo.
  echo [ERROR] start-dev.ps1 failed. code=%EC%
  pause
  exit /b %EC%
)
if "%EC%"=="2" (
  echo.
  echo [NextWeb] Launched, but some health checks timed out. See service windows.
  timeout /t 4 /nobreak >nul
  exit /b 0
)
exit /b 0
