# NextWeb stop: kill listeners on 3020 / 8020 and close start-dev cmd windows

$ErrorActionPreference = "Continue"

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

$ApiPort = 8020
$WebPort = 3020
$ports = @($WebPort, $ApiPort)

$scriptTitles = @("NextWeb API", "NextWeb Web")
$scriptNames = @("dev:api", "dev:web")

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

function Stop-ProcessTree([int]$ProcId, [string]$Why) {
  if ($ProcId -le 0) { return $false }
  Write-Host "[NextWeb] Killing PID $ProcId (tree) — $Why"
  & taskkill.exe /F /T /PID $ProcId 2>$null | Out-Null
  return $true
}

function Get-NextWebCmdPids {
  $found = [System.Collections.Generic.HashSet[int]]::new()
  $rootNorm = $Root.TrimEnd('\')

  foreach ($p in @(Get-Process -Name cmd -ErrorAction SilentlyContinue)) {
    $title = $p.MainWindowTitle
    if (-not $title) { continue }
    foreach ($prefix in $scriptTitles) {
      if ($title.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        [void]$found.Add([int]$p.Id)
        break
      }
    }
  }

  try {
    $cmds = Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in @($cmds)) {
      $cl = $proc.CommandLine
      if (-not $cl) { continue }
      if ($cl -notlike "*$rootNorm*") { continue }
      $hit = $false
      foreach ($name in $scriptNames) {
        if ($cl -like "*$name*") { $hit = $true; break }
      }
      if ($hit -and $proc.ProcessId -gt 0) { [void]$found.Add([int]$proc.ProcessId) }
    }
  } catch { }

  return @($found)
}

Write-Host "[NextWeb] Stopping services on ports $($ports -join ' / ')..."

$killed = 0

foreach ($procId in @(Get-NextWebCmdPids)) {
  if (Stop-ProcessTree $procId "NextWeb cmd window") { $killed++ }
}

Start-Sleep -Milliseconds 800

foreach ($port in $ports) {
  $listenPids = Get-ListenPids $port
  if (-not $listenPids -or $listenPids.Count -eq 0) {
    Write-Host "[NextWeb] Port $port free"
    continue
  }
  foreach ($procId in $listenPids) {
    if (Stop-ProcessTree $procId "port $port") { $killed++ }
  }
}

Start-Sleep -Milliseconds 1000

foreach ($procId in @(Get-NextWebCmdPids)) {
  if (Stop-ProcessTree $procId "NextWeb cmd window (2nd)") { $killed++ }
}
foreach ($port in $ports) {
  $listenPids = Get-ListenPids $port
  if (-not $listenPids -or $listenPids.Count -eq 0) { continue }
  foreach ($procId in $listenPids) {
    if (Stop-ProcessTree $procId "port $port (2nd)") { $killed++ }
  }
}

Start-Sleep -Milliseconds 600

$still = @()
foreach ($port in $ports) {
  $listenPids = Get-ListenPids $port
  if ($listenPids -and $listenPids.Count -gt 0) { $still += $port }
}
$stillCmds = @(Get-NextWebCmdPids)

if ($still.Count -gt 0 -or $stillCmds.Count -gt 0) {
  if ($still.Count -gt 0) {
    Write-Host "[NextWeb] Still busy ports: $($still -join ', ')" -ForegroundColor Yellow
  }
  if ($stillCmds.Count -gt 0) {
    Write-Host "[NextWeb] Still open cmd PIDs: $($stillCmds -join ', ')" -ForegroundColor Yellow
  }
  exit 1
}

Write-Host "[NextWeb] Done. (killed $killed process tree(s); cmd windows closed)"
exit 0
