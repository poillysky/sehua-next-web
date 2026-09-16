# ASCII-only watch loop to avoid PS encoding breakage
$ErrorActionPreference = 'Continue'
$out = 'e:\Project\sehua-next-web\.tmp_enrich_monitor.jsonl'
$cookieFile = 'e:\Project\sehua-next-web\.tmp_enrich_cookie.txt'
$uri = 'http://127.0.0.1:8020/scrap-library/embed/enrich/status'

while ($true) {
  Start-Sleep -Seconds 90
  try {
    $cookie = (Get-Content -LiteralPath $cookieFile -Raw -Encoding utf8).Trim()
    $st = Invoke-RestMethod -Uri $uri -Headers @{ Cookie = $cookie } -TimeoutSec 20
    $m = $st.data.monitor
    $qc = $st.data.queueCounts
    $phases = @{}
    foreach ($x in @($m.inflight)) {
      $p = [string]$x.phase
      if (-not $p) { $p = '?' }
      if (-not $phases.ContainsKey($p)) { $phases[$p] = 0 }
      $phases[$p]++
    }
    $rec = [ordered]@{
      ts = (Get-Date).ToString('s')
      running = [bool]$st.data.running
      halt = [string]$st.data.halt
      done = [int]$qc.done
      fail = [int]$qc.fail
      pending = [int]$qc.pending
      runningN = [int]$qc.running
      avgFetchMs = [int]($m.summary.avgFetchMs)
      stallingN = [int]($m.summary.stallingN)
      inflightN = [int]($m.summary.inflightN)
      itemWorkers = [int]$m.itemWorkers
      phases = $phases
    }
    $json = ($rec | ConvertTo-Json -Compress)
    Add-Content -LiteralPath $out -Value $json -Encoding utf8
    Write-Output ("AGENT_LOOP_TICK_enrich_watch " + $json)
    if (-not $st.data.running) {
      Write-Output 'AGENT_LOOP_TICK_enrich_watch {"done":true}'
      break
    }
  } catch {
    $msg = [string]$_.Exception.Message
    Write-Output ("AGENT_LOOP_TICK_enrich_watch error=" + $msg)
  }
}
