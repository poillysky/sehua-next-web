import type {
  PrefixCatalogLocalIndexProgress,
  ScrapLibraryQualityStats,
} from '@/lib/api';

/** 刮削相关任务互斥：任一忙则锁按钮 */
export function scrapeJobsLocked(p: {
  strmBusy: boolean;
  localIndexBusy: boolean;
  catalogBusy: boolean;
  scrapBusy: boolean;
  enrichBusy: boolean;
  actressOptBusy: boolean;
  nfoOptBusy: boolean;
  actressAvatarBusy: boolean;
}): boolean {
  return (
    p.strmBusy ||
    p.localIndexBusy ||
    p.catalogBusy ||
    p.scrapBusy ||
    p.enrichBusy ||
    p.actressOptBusy ||
    p.nfoOptBusy ||
    p.actressAvatarBusy
  );
}

export function normalizeEnrichFillMode(
  raw: string | undefined,
): 'incremental' | 'refresh_weak' | 'overwrite' {
  if (raw === 'overwrite') return 'overwrite';
  if (raw === 'refresh_weak') return 'refresh_weak';
  return 'incremental';
}

/** 六区开关互斥：任一时刻至多一个区为「开」。onId=null 表示六个区全关。 */
export function applyExclusiveRegion(
  rows: { id: string; label: string; enabled: boolean }[],
  onId: string | null,
): { id: string; label: string; enabled: boolean }[] {
  return rows.map((r) => ({ ...r, enabled: Boolean(onId) && r.id === onId }));
}

/** 与 applyExclusiveRegion 同口径的落库值：只留 onId 为 true。 */
export function exclusiveRegionsEnabled(
  current: Record<string, boolean> | undefined,
  onId: string | null,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const rid of Object.keys(current || {})) out[rid] = rid === onId;
  if (onId && !(onId in out)) out[onId] = true;
  return out;
}

export function strmStoppedHint(st: {
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  result?: unknown;
  error?: string | null;
}): string | null {
  if (st.error || st.result) return null;
  const stage = st.progress?.stage || '';
  const stopped =
    st.phase === 'interrupted' ||
    stage === 'write' ||
    stage === 'prepare' ||
    stage === 'prune';
  if (!stopped) return null;
  const done = st.progress?.done;
  const total = st.progress?.total;
  const where =
    done != null && total != null
      ? ` · 已写 ${done.toLocaleString()}/${total.toLocaleString()}`
      : '';
  return `本地同步已中断${where}，再点一次会跳过已有文件继续`;
}

export function formatQualityDetail(stats?: ScrapLibraryQualityStats | null) {
  if (!stats) {
    return {
      total: 0,
      done: 0,
      remain: 0,
      embedTotal: 0,
      shells: 0,
      rows: [] as Array<{ label: string; value: number }>,
    };
  }
  const total = Math.max(0, stats.total ?? 0);
  const remain = Math.max(0, stats.incomplete ?? 0);
  const done = Math.max(0, total - remain);
  const embedTotal = Math.max(0, stats.embedTotal ?? total);
  const shells = Math.max(0, stats.shells ?? 0);
  const c = stats.counts || {};
  const rows: Array<{ label: string; value: number }> = [
    { label: '空壳（仅骨架、待刮削）', value: shells },
    { label: '缺封面', value: c.no_local ?? 0 },
    { label: '缺外链', value: c.no_media ?? 0 },
    { label: '缺女优', value: c.no_actress ?? 0 },
    { label: '缺片商', value: c.no_studio ?? 0 },
    { label: '缺剧情', value: c.no_plot ?? 0 },
    { label: '标题过薄', value: c.thin_title ?? 0 },
  ];
  return { total, done, remain, embedTotal, shells, rows };
}

export function formatCatalogRegionDesc(reg: {
  prefix_count: number;
  scrap_prefix_count?: number;
  code_count: number;
}) {
  const scrap = Math.max(0, Number(reg.scrap_prefix_count) || 0);
  return `${reg.prefix_count} 前缀 · ${scrap} 有片 · ${reg.code_count} 番号`;
}
