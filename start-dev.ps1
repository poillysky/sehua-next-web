# NextWeb one-click start: API + Web
# ASCII only. Double-click start-dev.cmd to run.
#
# Params:
#   -NoBrowser    do not open Web after healthy
#   -NoKill       do not free ports before start
#   -WaitSec      health wait seconds (default 45)

param(
  [switch]$NoBrowser,
  [switch]$NoKill,
  [int]$WaitSec = 45
)

$ErrorActionPreference = "Continue"
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $Root

$ApiPort = 8020
$WebPort = 3020

function Write-Step([string]$msg) {
  Write-Host "[NextWeb] $msg"
}

function Write-Err([string]$msg) {
  Write-Host "[ERROR] $msg" -ForegroundColor Red
}

function Get-ListenPids([int]$Port) {
  $listenPids = [System.Collections.Generic.HashSet[int]]::new()
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in @($conns)) {
      if ($c.OwningProcess -and $c.OwningProcess -ne 0) { [void]$listenPids.Add([int]$c.OwningProcess) }
    }
  } catch { }

  if ($listenPids.Count -eq 0) {
    try {
      $lines = netstat -ano -p tcp 2>$null | Select-String ":$Port\s"
      foreach ($line in $lines) {
        if ($line -notmatch "LISTENING") { continue }
        if ($line -match "\s(\d+)\s*$") {
          $procId = [int]$Matches[1]
          if ($procId -gt 0) { [void]$listenPids.Add($procId) }
        }
      }
    } catch { }
  }
  return @($listenPids)
}

function Stop-PortListeners([int]$Port) {
  $listenPids = Get-ListenPids $Port
  if (-not $listenPids -or $listenPids.Count -eq 0) { return }
  foreach ($procId in $listenPids) {
    Write-Step "Port $Port in use, killing PID $procId (tree)"
    & taskkill.exe /F /T /PID $procId 2>$null | Out-Null
  }
}

function Stop-NextWebCmdWindows {
  foreach ($p in @(Get-Process -Name cmd -ErrorAction SilentlyContinue)) {
    $title = $p.MainWindowTitle
    if (-not $title) { continue }
    foreach ($prefix in @("NextWeb API", "NextWeb Web")) {
      if ($title.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Step "Closing cmd window: $title (PID $($p.Id))"
        & taskkill.exe /F /T /PID $p.Id 2>$null | Out-Null
        break
      }
    }
  }
}

function Test-PortFree([int]$Port) {
  $pids = Get-ListenPids $Port
  return (-not $pids -or $pids.Count -eq 0)
}

function Resolve-NpmCmd {
  $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $fallback = "C:\Program Files\nodejs\npm.cmd"
  if (Test-Path $fallback) { return $fallback }
  return $null
}

function Test-HttpOk([string]$Url) {
  try {
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.Method = "GET"
    $req.Timeout = 2000
    $req.ReadWriteTimeout = 2000
    $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
    $req.KeepAlive = $false
    $resp = $req.GetResponse()
    $code = [int]$resp.StatusCode
    $resp.Close()
    return ($code -ge 200 -and $code -lt 500)
  } catch {
    return $false
  }
}

function Start-ServiceWindow([string]$Title, [string]$NpmScript, [string]$NpmPath) {
  $nodeDir = Split-Path -Parent $NpmPath
  $inner = "title $Title && cd /d `"$Root`" && set `"PATH=$nodeDir;%PATH%`" && `"$NpmPath`" run $NpmScript"
  Start-Process -FilePath "cmd.exe" -ArgumentList "/k", $inner -WorkingDirectory $Root -WindowStyle Normal | Out-Null
}

function Write-StatusLine([string]$name, [string]$url, [bool]$ok) {
  $mark = if ($ok) { "OK" } else { "WAIT/FAIL" }
  $color = if ($ok) { "Green" } else { "Yellow" }
  Write-Host ("  {0,-7} {1,-36} [{2}]" -f $name, $url, $mark) -ForegroundColor $color
}

Write-Step "Root: $Root"

$python = Join-Path $Root "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  Write-Err "Missing $python"
  Write-Host "        Create venv / install deps for apps\api first."
  Read-Host "Press Enter to exit"
  exit 1
}

$npm = Resolve-NpmCmd
if (-not $npm) {
  Write-Err "npm.cmd not found in PATH"
  Read-Host "Press Enter to exit"
  exit 1
}
Write-Step "npm: $npm"

$webMods = Join-Path $Root "apps\web\node_modules"
if (-not (Test-Path $webMods)) {
  Write-Err "Missing apps\web\node_modules"
  Write-Host "        Run: npm install --prefix apps/web"
  Read-Host "Press Enter to exit"
  exit 1
}

$ports = @($ApiPort, $WebPort)

if (-not $NoKill) {
  Write-Step ("Freeing ports " + ($ports -join " / ") + " ...")
  Stop-NextWebCmdWindows
  foreach ($p in $ports) { Stop-PortListeners $p }
  Start-Sleep -Milliseconds 1200
  Stop-NextWebCmdWindows
  foreach ($p in $ports) { Stop-PortListeners $p }
  Start-Sleep -Milliseconds 800
  $busy = @()
  foreach ($p in $ports) {
    if (-not (Test-PortFree $p)) { $busy += $p }
  }
  if ($busy.Count -gt 0) {
    Write-Err ("Ports still busy: " + ($busy -join ", "))
    Read-Host "Press Enter to exit"
    exit 1
  }
}

Write-Step "Launching API ($ApiPort)..."
Start-ServiceWindow "NextWeb API :$ApiPort" "dev:api" $npm

Write-Step "Launching Web ($WebPort)..."
Start-ServiceWindow "NextWeb Web :$WebPort" "dev:web" $npm

Write-Host ""
Write-Step "Waiting for health (up to ${WaitSec}s)..."
$deadline = (Get-Date).AddSeconds($WaitSec)
$apiOk = $false
$webOk = $false
while ((Get-Date) -lt $deadline) {
  if (-not $apiOk) { $apiOk = Test-HttpOk "http://127.0.0.1:$ApiPort/health" }
  if (-not $webOk) { $webOk = Test-HttpOk "http://127.0.0.1:$WebPort" }
  if ($apiOk -and $webOk) { break }
  Start-Sleep -Milliseconds 400
}

Write-Host ""
Write-Step "Status:"
Write-StatusLine "API" "http://127.0.0.1:$ApiPort" $apiOk
Write-StatusLine "Web" "http://127.0.0.1:$WebPort" $webOk
Write-Host ""
Write-Step "Close service windows (or run stop-dev.cmd) to stop."

if (-not $NoBrowser -and $webOk) {
  Write-Step "Opening browser..."
  Start-Process "http://127.0.0.1:$WebPort" | Out-Null
} elseif (-not $webOk) {
  Write-Host "  Web not ready yet; open http://127.0.0.1:$WebPort manually." -ForegroundColor Yellow
}

if (-not $apiOk -or -not $webOk) {
  Write-Host "  Some services not healthy yet; check their console windows." -ForegroundColor Yellow
  exit 2
}

exit 0
