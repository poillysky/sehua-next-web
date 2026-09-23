import type {
  ScrapLibraryEnrichCurrent,
  ScrapLibraryEnrichJobStatus,
  ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import { displayHitSource } from './sourceMeta';

export type LiveTab = 'pending' | 'running' | 'done' | 'soft' | 'fail';

export const TAB_META: Array<{ id: LiveTab; label: string }> = [
  { id: 'pending', label: '未处理' },
  { id: 'running', label: '处理中' },
  { id: 'done', label: '成功' },
  { id: 'soft', label: '软成功' },
  { id: 'fail', label: '失败' },
];

export const QUEUE_PAGE_SIZE = 100;


export function formatQueueScanLabel(
  qs?: ScrapLibraryEnrichJobStatus['queueScan'] | null,
): string {
  if (!qs?.active) return '';
  const label = String(qs.label || '').trim();
  if (label) return label;
  const n = Number(qs.scanned || 0);
  const tot = Number(qs.total || 0);
  const head =
    tot > 0
      ? `扫描本地 · ${n.toLocaleString()}/${tot.toLocaleString()}`
      : `扫描本地 · ${n.toLocaleString()}`;
  const bits = [
    Number(qs.done || 0) > 0 ? `成功 ${Number(qs.done).toLocaleString()}` : '',
    Number(qs.soft || 0) > 0 ? `软成功 ${Number(qs.soft).toLocaleString()}` : '',
    Number(qs.fail || 0) > 0 ? `失败 ${Number(qs.fail).toLocaleString()}` : '',
  ].filter(Boolean);
  return bits.length ? `${head} · ${bits.join(' · ')}` : head;
}

const GAP_LABEL: Record<string, string> = {
  no_local: '封面',
  no_media: '外链',
  no_actress: '女优',
  no_studio: '片商',
  no_plot: '剧情',
  thin_title: '标题',
  no_zh_title: '中文标题',
};

function isSoftRemainError(err?: string) {
  const soft = String(err || '')
    .trim()
    .replace(/^(?:软成功|次成功)\s*·\s*/, '');
  if (!soft.startsWith('仍缺:')) return false;
  const parts = soft
    .slice('仍缺:'.length)
    .split(/[·,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
  // 有封面但无标题 → 软成功；女优/片商等不算 soft
  const softLabels = new Set(['标题']);
  return parts.length > 0 && parts.every((p) => softLabels.has(p));
}

export function normalizeSoftSuccessRow(
  row: ScrapLibraryEnrichQueueItem,
): ScrapLibraryEnrichQueueItem {
  if (rowStatus(row.status) !== 'fail' || !isSoftRemainError(row.error)) {
    return row;
  }
  const err = String(row.error || '').trim();
  return {
    ...row,
    status: 'done',
    partialOk: true,
    error:
      err.startsWith('软成功') || err.startsWith('次成功')
        ? err.replace(/^次成功/, '软成功')
        : `软成功 · ${err}`,
  };
}

export function isPartialOk(row?: {
  status?: string;
  partialOk?: boolean;
  error?: string;
  gaps?: string[];
  gapsAfter?: string[];
}) {
  if (!row) return false;
  const normalized =
    row.status === 'fail' && isSoftRemainError(row.error)
      ? { ...row, status: 'done' as const, partialOk: true }
      : row;
  if (normalized.status !== 'done') return false;
  const softGaps = new Set(['thin_title']);
  const after = [
    ...(Array.isArray(normalized.gapsAfter) ? normalized.gapsAfter : []),
    ...(Array.isArray(normalized.gaps) ? normalized.gaps : []),
  ]
    .map((g) => String(g || '').trim())
    .filter(Boolean);
  if (after.includes('no_local')) return false;
  const err = String(normalized.error || '').trim();
  // 有封面无标题 → 软成功（文案优先，避免 gapsAfter 混入女优等旧字段挡掉）
  if (isSoftRemainError(err)) return true;
  if (after.some((g) => softGaps.has(g))) return true;
  // 旧「只缺女优/片商」软成功 → 按成功展示
  if (err.startsWith('软成功') || err.startsWith('次成功')) {
    return false;
  }
  return false;
}

export function statusLabel(s?: string, row?: ScrapLibraryEnrichQueueItem) {
  if (s === 'running') return '处理中';
  if (s === 'done') return isPartialOk(row) ? '软成功' : '成功';
  if (s === 'fail') return '失败';
  return '未处理';
}

export function rowStatus(s?: string): 'pending' | 'running' | 'done' | 'fail' {
  if (s === 'running' || s === 'done' || s === 'fail') return s;
  return 'pending';
}

export function statusTone(
  s?: string,
  row?: ScrapLibraryEnrichQueueItem,
): 'pending' | 'running' | 'ok' | 'warn' | 'fail' {
  if (s === 'running') return 'running';
  if (s === 'done') return isPartialOk(row) ? 'warn' : 'ok';
  if (s === 'fail') return 'fail';
  return 'pending';
}

export function gapsText(gaps?: string[]) {
  const parts = (gaps || [])
    .map((g) => GAP_LABEL[g] || g)
    .filter(Boolean);
  return parts.length ? parts.join(' · ') : '';
}

function liveSourceProgress(row: ScrapLibraryEnrichQueueItem): string {
  const timings = Array.isArray(row.sourceTimings) ? row.sourceTimings : [];
  if (!timings.length) return '';
  const finished = timings.filter((t) =>
    ['done', 'fail', 'skipped'].includes(String(t.status || '')),
  );
  const ok = finished.filter((t) => Boolean(t.ok));
  const lastOk = ok.length ? ok[ok.length - 1] : null;
  const active =
    timings.find((t) => String(t.status || '') === 'running') ||
    timings.find((t) => String(t.status || '') === 'pending');
  const parts = [`${finished.length}/${timings.length}源`];
  if (lastOk?.id) parts.push(String(lastOk.id));
  else if (active?.id) parts.push(`${String(active.id)}…`);
  return parts.join(' · ');
}

function fieldCompletenessText(row: ScrapLibraryEnrichQueueItem): string {
  const fields = Array.isArray(row.fields) ? row.fields : [];
  if (!fields.length) return '';
  const coverOk =
    row.posterDownloaded === true ||
    fields.some(
      (f) =>
        Boolean(f) &&
        (f.id === 'poster' || String(f.label || '') === '封面') &&
        f.ok === true,
    );
  const missing = fields.filter((f) => {
    if (!f || f.ok !== false) return false;
    // 已落盘/字段已齐时忽略陈旧「缺封面」
    if (
      coverOk &&
      (f.id === 'poster' || String(f.label || '') === '封面')
    ) {
      return false;
    }
    return true;
  });
  if (!missing.length) return '字段齐全';
  const labels = missing
    .map((f) => String(f.label || f.id || '').trim())
    .filter(Boolean);
  if (!labels.length) return `缺 ${missing.length} 项`;
  const head = labels.slice(0, 4).join(' · ');
  return labels.length > 4
    ? `缺 ${head} 等${labels.length}项`
    : `缺 ${head}`;
}

export function queueRowDesc(row: ScrapLibraryEnrichQueueItem): string {
  const err = String(row.error || '').trim();
  if (row.status === 'fail' && err) return err;

  if (row.status === 'done') {
    if (isPartialOk(row)) {
      if (
        err.startsWith('软成功') ||
        err.startsWith('次成功') ||
        err.includes('仍缺')
      ) {
        return err.replace(/^次成功/, '软成功');
      }
      const soft = gapsText(row.gapsAfter || row.gaps || []);
      return soft ? `软成功 · 仍缺:${soft}` : '软成功';
    }
    const completeness = fieldCompletenessText(row);
    if (completeness) {
      if (completeness === '字段齐全') return '字段齐全 · 封面齐全';
      return completeness;
    }
    // 扫描写入（scan / local_scan）无 fields/标题时勿展示 source 字面量
    const srcRaw = String(row.source || '').trim();
    if (!srcRaw || srcRaw === 'local_scan' || srcRaw === 'scan') {
      return '字段齐全 · 封面齐全';
    }
    const title = String(row.detailTitle || '').trim();
    const src = displayHitSource(row.source);
    if (title && src) return `${src} · ${title}`;
    if (title) return title;
    if (src) return src;
    return '字段齐全 · 封面齐全';
  }

  if (row.status === 'running') {
    const stall = String(row.stallLabel || '').trim();
    if (stall) return stall;
    const live = liveSourceProgress(row);
    if (live) return live;
    return '拉取中…';
  }

  const gaps = gapsText(row.gaps);
  if (gaps) return gaps;

  const title = String(row.detailTitle || '').trim();
  const src = displayHitSource(row.source);
  if (title && src) return `${src} · ${title}`;
  if (title) return title;
  if (src) return src;

  if (err) return err;
  if (row.status === 'pending') return '待处理';
  return '';
}

export const LOG_CAP = 200;

/** 本会话已进过日志页的分区：再进只读队列表，不自动全量扫描 */
export const enrichLiveBootstrapped = new Set<string>();

export function pendingTotalStorageKey(regionId: string) {
  return `enrich-live-pending-total:${regionId}`;
}

export function readCachedPendingTotal(regionId: string): number {
  try {
    const n = Number(sessionStorage.getItem(pendingTotalStorageKey(regionId)) || 0);
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function writeCachedPendingTotal(regionId: string, n: number) {
  try {
    if (n > 0) sessionStorage.setItem(pendingTotalStorageKey(regionId), String(n));
  } catch {
    /* ignore */
  }
}

export function mergeLogLines(base: string[], extra: string[]) {
  const out = [...base];
  for (const line of extra) {
    if (!line) continue;
    if (out.length && out[out.length - 1] === line) continue;
    out.push(line);
  }
  return out.slice(-LOG_CAP);
}

export function rowKey(row: ScrapLibraryEnrichQueueItem) {
  // 稳定键：SSE 快照与库表翻页必须对上，勿用 logId 优先（否则同号两套身份来回闪）
  const iid = String(row.itemId || '').trim();
  if (iid) return `id:${iid}`;
  const code = String(row.code || '').trim().toUpperCase();
  if (code) return `code:${code}`;
  if (row.logId) return `log:${row.logId}`;
  return `idx:${row.index ?? ''}`;
}

/** 合并队列行：保留已有字段，用新行覆盖有值字段 */
function mergeQueueRow(
  prev: ScrapLibraryEnrichQueueItem,
  next: ScrapLibraryEnrichQueueItem,
): ScrapLibraryEnrichQueueItem {
  return {
    ...prev,
    ...next,
    logId: next.logId || prev.logId,
    gaps: next.gaps?.length ? next.gaps : prev.gaps,
    gapsAfter: next.gapsAfter?.length ? next.gapsAfter : prev.gapsAfter,
    fields: next.fields?.length ? next.fields : prev.fields,
  };
}

export function detailFromRow(
  row: ScrapLibraryEnrichQueueItem,
  current?: ScrapLibraryEnrichCurrent | null,
): ScrapLibraryEnrichCurrent {
  const same =
    current &&
    ((row.itemId && current.itemId === row.itemId) ||
      (row.code &&
        current.code &&
        row.code.toUpperCase() === current.code.toUpperCase()));
  if (same && current) {
    return {
      ...current,
      code: current.code || row.code,
      itemId: current.itemId || row.itemId,
      gaps: current.gaps?.length ? current.gaps : row.gaps,
      status: current.status || row.status,
      error: current.error || row.error,
      source: current.source || row.source,
      fetchMs:
        typeof current.fetchMs === 'number' ? current.fetchMs : row.fetchMs,
      coverMs:
        typeof current.coverMs === 'number' ? current.coverMs : row.coverMs,
      actressMs:
        typeof current.actressMs === 'number'
          ? current.actressMs
          : row.actressMs,
      vectorMs:
        typeof current.vectorMs === 'number' ? current.vectorMs : row.vectorMs,
      totalMs:
        typeof current.totalMs === 'number' ? current.totalMs : row.totalMs,
      detailTitle: current.detailTitle || row.detailTitle,
      vectorSynced:
        typeof current.vectorSynced === 'boolean'
          ? current.vectorSynced
          : row.vectorSynced,
      vectorSkipped:
        typeof current.vectorSkipped === 'boolean'
          ? current.vectorSkipped
          : row.vectorSkipped,
      vectorError: current.vectorError || row.vectorError,
      sourceTimings: current.sourceTimings?.length
        ? current.sourceTimings
        : row.sourceTimings,
      fields: current.fields?.length ? current.fields : row.fields,
    };
  }
  return {
    code: row.code,
    itemId: row.itemId,
    gaps: row.gaps,
    status: row.status,
    index: row.index,
    error: row.error,
    source: row.source,
    fetchMs: row.fetchMs,
    coverMs: row.coverMs,
    actressMs: row.actressMs,
    vectorMs: row.vectorMs,
    totalMs: row.totalMs,
    detailTitle: row.detailTitle,
    actors: row.actors,
    nfoChanged: row.nfoChanged,
    posterDownloaded: row.posterDownloaded,
    vectorSynced: row.vectorSynced,
    vectorSkipped: row.vectorSkipped,
    vectorError: row.vectorError,
    relPath: row.relPath || row.rel_path,
    sourceTimings: row.sourceTimings,
    fields: row.fields,
    wouldFill: row.wouldFill,
  };
}
