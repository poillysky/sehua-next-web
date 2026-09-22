import type {
  EnrichMonitorInflight,
  EnrichMonitorSnapshot,
  ScrapLibraryEnrichQueueItem,
} from '@/lib/api';

export function formatMs(ms?: number): string {
  const n = Number(ms || 0);
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s`;
}

export function monitorSourceProgress(row: EnrichMonitorInflight): string {
  const timings = Array.isArray(row.sources) ? row.sources : [];
  if (!timings.length) return '';
  const finished = timings.filter((t) =>
    ['done', 'fail', 'skipped'].includes(String(t.status || '')),
  );
  const active =
    timings.find((t) => String(t.status || '') === 'running') ||
    timings.find((t) => String(t.status || '') === 'pending');
  const parts = [`${finished.length}/${timings.length}源`];
  if (active?.id) parts.push(`${String(active.id)}…`);
  return parts.join(' · ');
}

export function monitorRowDesc(row: EnrichMonitorInflight): string {
  const stall = String(row.stall?.label || '').trim();
  if (stall) return stall;
  const srcProg = monitorSourceProgress(row);
  const phase = String(row.phaseLabel || row.phase || '').trim();
  if (phase && srcProg) return `${phase} · ${srcProg}`;
  if (phase) return phase;
  if (srcProg) return srcProg;
  return formatMs(row.elapsedMs);
}

export function findQueueForMonitor(
  inf: EnrichMonitorInflight,
  rows: ScrapLibraryEnrichQueueItem[],
): ScrapLibraryEnrichQueueItem | null {
  const code = String(inf.code || '').trim().toUpperCase();
  const iid = String(inf.itemId || '').trim();
  return (
    rows.find(
      (r) =>
        (iid && String(r.itemId || '').trim() === iid) ||
        (code && String(r.code || '').trim().toUpperCase() === code),
    ) || null
  );
}

export function topStallKinds(mon?: EnrichMonitorSnapshot | null): string {
  const kinds = mon?.summary?.stallKinds || {};
  const entries = Object.entries(kinds)
    .map(([k, v]) => [k, Number(v || 0)] as const)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2);
  if (!entries.length) return '暂无卡顿统计';
  return entries.map(([k, n]) => `${k}×${n}`).join(' · ');
}
