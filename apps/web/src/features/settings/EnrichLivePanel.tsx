'use client';

import { startTransition, useEffect, useRef, useState, type ReactNode } from 'react';
import { Activity, CheckCircle2, ChevronRight, CircleAlert, Inbox, LoaderCircle, Search, X } from 'lucide-react';
import {
  pauseScrapLibraryEnrich,
  clearScrapLibraryEnrichLogs,
  subscribeScrapLibraryEnrichStatus,
  getScrapLibraryEnrichLogs,
  getScrapLibraryEnrichQueueLog,
  getScrapLibraryEnrichLocalCovers,
  scanScrapLibraryEnrichQueue,
  retryScrapLibraryEnrichFails,
  retryScrapLibraryEnrichSofts,
  enrichScrapLibraryItem,
  listScrapLibraryEmbedItems,
  scrapLibraryCoverUrl,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichFieldRow,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
  type EnrichMonitorInflight,
  type EnrichMonitorSnapshot,
} from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
type LiveTab = 'pending' | 'running' | 'done' | 'soft' | 'fail';

const TAB_META: Array<{ id: LiveTab; label: string }> = [
  { id: 'pending', label: '未处理' },
  { id: 'running', label: '处理中' },
  { id: 'done', label: '成功' },
  { id: 'soft', label: '软成功' },
  { id: 'fail', label: '失败' },
];

const QUEUE_PAGE_SIZE = 100;

const SOURCE_DISPLAY: Record<string, string> = {
  mdcx_c_number: '色花堂',
  local_code_title: '色花堂',
};

function sourceIconMeta(source: string): {
  id: string;
  label: string;
  hue: number;
} {
  const id = String(source || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_');
  let hue = 210;
  for (let i = 0; i < id.length; i += 1) hue = (hue + id.charCodeAt(i) * 17) % 360;
  return {
    id,
    label: SOURCE_DISPLAY[id] || id || '—',
    hue,
  };
}

function FieldSourceIcon({ source }: { source?: string }) {
  const meta = sourceIconMeta(String(source || ''));
  if (!meta.id) return null;
  return (
    <span
      className="enrich-live__field-src"
      title={meta.label}
      style={
        {
          ['--enrich-src-hue' as string]: String(meta.hue),
        } as Record<string, string>
      }
    >
      {meta.label}
    </span>
  );
}

function formatQueueScanLabel(
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

function EnrichTabIdle({
  tone = 'neutral',
  waiting = false,
  title,
  desc,
  icon,
}: {
  tone?: 'neutral' | 'ok' | 'fail';
  waiting?: boolean;
  title: string;
  desc: string;
  icon: ReactNode;
}) {
  return (
    <div
      className={cn(
        'enrich-live__idle',
        waiting && 'enrich-live__idle--wait',
        tone === 'ok' && 'enrich-live__idle--ok',
        tone === 'fail' && 'enrich-live__idle--fail',
      )}
    >
      <span className="enrich-live__idle-mark" aria-hidden>
        {icon}
      </span>
      <p className="enrich-live__idle-title">{title}</p>
      <p className="enrich-live__idle-desc">{desc}</p>
    </div>
  );
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
  // 女优 / 片商算软成功（中文标题不再挡）
  const softLabels = new Set(['女优', '片商']);
  return parts.length > 0 && parts.every((p) => softLabels.has(p));
}

function normalizeSoftSuccessRow(
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

function isPartialOk(row?: {
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
  const softGaps = new Set(['no_actress', 'no_studio']);
  const after = normalized.gapsAfter;
  if (Array.isArray(after) && after.length) {
    // 有 gapsAfter 时只认软缺口
    return after.some((g) => softGaps.has(String(g || '')));
  }
  const err = String(normalized.error || '').trim();
  if (err.startsWith('软成功') || err.startsWith('次成功') || isSoftRemainError(err)) {
    return isSoftRemainError(err);
  }
  // 旧数据只有 partialOk、无 gaps/文案：保持软成功徽标，避免整页跳动
  return Boolean(normalized.partialOk);
}

function statusLabel(s?: string, row?: ScrapLibraryEnrichQueueItem) {
  if (s === 'running') return '处理中';
  if (s === 'done') return isPartialOk(row) ? '软成功' : '成功';
  if (s === 'fail') return '失败';
  return '未处理';
}

function rowStatus(s?: string): 'pending' | 'running' | 'done' | 'fail' {
  if (s === 'running' || s === 'done' || s === 'fail') return s;
  return 'pending';
}

function statusTone(
  s?: string,
  row?: ScrapLibraryEnrichQueueItem,
): 'pending' | 'running' | 'ok' | 'warn' | 'fail' {
  if (s === 'running') return 'running';
  if (s === 'done') return isPartialOk(row) ? 'warn' : 'ok';
  if (s === 'fail') return 'fail';
  return 'pending';
}

function gapsText(gaps?: string[]) {
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

function formatMs(ms?: number): string {
  const n = Number(ms || 0);
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s`;
}

function monitorSourceProgress(row: EnrichMonitorInflight): string {
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

function monitorRowDesc(row: EnrichMonitorInflight): string {
  const stall = String(row.stall?.label || '').trim();
  if (stall) return stall;
  const srcProg = monitorSourceProgress(row);
  const phase = String(row.phaseLabel || row.phase || '').trim();
  if (phase && srcProg) return `${phase} · ${srcProg}`;
  if (phase) return phase;
  if (srcProg) return srcProg;
  return formatMs(row.elapsedMs);
}

function findQueueForMonitor(
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

function topStallKinds(mon?: EnrichMonitorSnapshot | null): string {
  const kinds = mon?.summary?.stallKinds || {};
  const entries = Object.entries(kinds)
    .map(([k, v]) => [k, Number(v || 0)] as const)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2);
  if (!entries.length) return '暂无卡顿统计';
  return entries.map(([k, n]) => `${k}×${n}`).join(' · ');
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

function queueRowDesc(row: ScrapLibraryEnrichQueueItem): string {
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
    // local_scan 无 fields/标题时勿展示 source 字面量
    const srcRaw = String(row.source || '').trim();
    if (!srcRaw || srcRaw === 'local_scan') {
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

const LOG_CAP = 200;

/** 本会话已进过日志页的分区：再进只读队列表，不自动全量扫描 */
const enrichLiveBootstrapped = new Set<string>();

function pendingTotalStorageKey(regionId: string) {
  return `enrich-live-pending-total:${regionId}`;
}

function readCachedPendingTotal(regionId: string): number {
  try {
    const n = Number(sessionStorage.getItem(pendingTotalStorageKey(regionId)) || 0);
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

function writeCachedPendingTotal(regionId: string, n: number) {
  try {
    if (n > 0) sessionStorage.setItem(pendingTotalStorageKey(regionId), String(n));
  } catch {
    /* ignore */
  }
}

function mergeLogLines(base: string[], extra: string[]) {
  const out = [...base];
  for (const line of extra) {
    if (!line) continue;
    if (out.length && out[out.length - 1] === line) continue;
    out.push(line);
  }
  return out.slice(-LOG_CAP);
}

function rowKey(row: ScrapLibraryEnrichQueueItem) {
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

function detailFromRow(
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

/** 详情竖框约 240px，2x 用 480 即可；过大 w 会逼后端现场压图变慢 */
const ENRICH_POSTER_W = 480;
const ENRICH_SHOT_W = 320;

function localCoverSrc(api?: string, mtime?: number, w = ENRICH_POSTER_W) {
  const raw = String(api || '').trim();
  if (!raw) return '';
  const url = scrapLibraryCoverUrl(
    { posterApi: raw, thumbApi: '', coverUrl: '' },
    { w, prefer: 'poster', rp: false },
  );
  if (!url) return '';
  if (!mtime) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_t=${mtime}`;
}

function EnrichItemDetail({
  detail,
  regionId,
}: {
  detail: ScrapLibraryEnrichCurrent;
  regionId: string;
}) {
  const timingsRaw = detail.sourceTimings || [];
  const timings = [...timingsRaw].sort((a, b) => {
    const rank = (t: (typeof timingsRaw)[number]) => {
      const st = String(t.status || '');
      if (st === 'done' || t.ok) return 0;
      if (st === 'fail' || t.error) return 1;
      if (st === 'skipped') return 3;
      return 2;
    };
    const d = rank(a) - rank(b);
    if (d !== 0) return d;
    return Number(b.ms || 0) - Number(a.ms || 0);
  });
  const maxSrcMs = timings.reduce(
    (m, t) => Math.max(m, Number(t.ms || 0)),
    0,
  );
  const fields = ensurePosterField(detail.fields || [], {
    posterDownloaded: detail.posterDownloaded,
  });
  const wallMs =
    typeof detail.fetchMs === 'number' ? detail.fetchMs : null;
  const totalMs =
    typeof detail.totalMs === 'number' ? detail.totalMs : null;
  const coverMs =
    typeof detail.coverMs === 'number' ? detail.coverMs : null;
  const vectorMs =
    typeof detail.vectorMs === 'number' ? detail.vectorMs : null;
  const actressMs =
    typeof detail.actressMs === 'number' ? detail.actressMs : null;
  const timingParts = [
    wallMs != null ? `拉源 ${wallMs}ms` : '',
    coverMs != null ? `封面 ${coverMs}ms` : '',
    vectorMs != null ? `向量 ${vectorMs}ms` : '',
    actressMs != null ? `女优 ${actressMs}ms` : '',
  ].filter(Boolean);

  const [localCovers, setLocalCovers] = useState<{
    ready: boolean;
    folder: string;
    poster: string;
    extras: Array<{ key: string; label: string; url: string }>;
  }>({ ready: false, folder: '', poster: '', extras: [] });
  /** 原图横/竖：横图不进 2:3 竖框裁切 */
  const [posterLandscape, setPosterLandscape] = useState(false);

  useEffect(() => {
    const code = String(detail.code || '').trim();
    const iid = String(detail.itemId || detail.relPath || '').trim();
    if (!code && !iid) {
      setLocalCovers({ ready: true, folder: '', poster: '', extras: [] });
      setPosterLandscape(false);
      return;
    }
    let alive = true;
    setPosterLandscape(false);
    setLocalCovers((prev) => ({ ...prev, ready: false }));
    void (async () => {
      try {
        const data = await getScrapLibraryEnrichLocalCovers({
          region: regionId,
          code,
          itemId: iid,
        });
        if (!alive) return;
        const files = Array.isArray(data.files) ? data.files : [];
        const posterFile =
          files.find((f) => f.kind === 'poster') ||
          (data.posterApi ? { posterApi: data.posterApi, mtime: 0 } : null);
        const poster = localCoverSrc(
          posterFile?.posterApi,
          posterFile?.mtime,
          ENRICH_POSTER_W,
        );
        const extras: Array<{ key: string; label: string; url: string }> = [];
        const labels: Record<string, string> = {
          thumb: '横图',
          fanart: '剧照',
        };
        for (const f of files) {
          if (f.kind === 'poster') continue;
          const url = localCoverSrc(f.posterApi, f.mtime, ENRICH_SHOT_W);
          if (!url || url === poster) continue;
          extras.push({
            key: String(f.kind || f.name || extras.length),
            label: labels[String(f.kind || '')] || String(f.name || '图'),
            url,
          });
        }
        setLocalCovers({
          ready: true,
          folder: String(data.folder || ''),
          poster,
          extras,
        });
      } catch {
        if (!alive) return;
        setLocalCovers({ ready: true, folder: '', poster: '', extras: [] });
      }
    })();
    return () => {
      alive = false;
    };
  }, [detail.code, detail.itemId, detail.relPath, regionId]);

  const showPoster = localCovers.poster;
  const extraShots = localCovers.extras;
  const coverHint = !showPoster
    ? localCovers.ready
      ? localCovers.folder
        ? '目录无 poster.jpg'
        : '未找到本地番号目录'
      : '读取本地封面…'
    : '';

  useEffect(() => {
    setPosterLandscape(false);
  }, [showPoster]);

  return (
    <div className="enrich-live__detail">
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">番号</span>
            <span className="settings-kv__val allow-select">
              {detail.code || '—'}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span className="settings-kv__val">
              {statusLabel(detail.status, detail)}
              {typeof detail.index === 'number' &&
              typeof detail.total === 'number'
                ? ` · ${detail.index + 1}/${detail.total}`
                : totalMs != null
                  ? ` · 总耗时 ${totalMs}ms`
                  : wallMs != null
                    ? ` · 拉源 ${wallMs}ms`
                    : ''}
            </span>
          </div>
        </li>
        {(totalMs != null || timingParts.length > 0) && (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">耗时</span>
              <span className="settings-kv__val">
                {totalMs != null ? `合计 ${totalMs}ms` : '合计 —'}
                {timingParts.length ? ` · ${timingParts.join(' · ')}` : ''}
              </span>
            </div>
          </li>
        )}
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">缺口</span>
            <span className="settings-kv__val">
              {gapsText(detail.gaps) || '—'}
            </span>
          </div>
        </li>
        {detail.detailTitle ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">标题</span>
              <span className="settings-kv__val allow-select">
                {detail.detailTitle}
              </span>
            </div>
          </li>
        ) : null}
        {detail.source && displayHitSource(detail.source) ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">命中源</span>
              <span className="settings-kv__val">
                {displayHitSource(detail.source)}
                {wallMs != null ? ` · 拉源 ${wallMs}ms` : ''}
                {maxSrcMs > 0 ? ` · 最慢源 ${maxSrcMs}ms` : ''}
              </span>
            </div>
          </li>
        ) : null}
        {typeof detail.posterDownloaded === 'boolean' ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">封面下载</span>
              <span className="settings-kv__val">
                {detail.posterDownloaded ? '已落盘' : '未落盘'}
                {coverMs != null ? ` · ${coverMs}ms` : ''}
              </span>
            </div>
          </li>
        ) : null}
        {detail.status === 'done' ||
        detail.status === 'fail' ||
        typeof detail.vectorSynced === 'boolean' ||
        detail.vectorSkipped ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">向量</span>
              <span className="settings-kv__val">
                {detail.vectorSkipped
                  ? '本步跳过（仅本地）'
                  : detail.vectorSynced
                    ? '已同步'
                    : detail.vectorError
                      ? `未同步 · ${detail.vectorError}`
                      : detail.status === 'running'
                        ? '同步中…'
                        : '未同步'}
                {!detail.vectorSkipped && vectorMs != null
                  ? ` · ${vectorMs}ms`
                  : ''}
                {!detail.vectorSkipped && actressMs != null
                  ? ` · 女优 ${actressMs}ms`
                  : ''}
              </span>
            </div>
          </li>
        ) : null}
        {detail.error ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">错误</span>
              <span className="settings-kv__val">{detail.error}</span>
            </div>
          </li>
        ) : null}
      </ul>

      <p className="settings-group-label">刮削图片</p>
      <div className="enrich-live__covers">
        {showPoster ? (
          <div
            className={cn(
              'enrich-live__cover enrich-live__cover--poster',
              posterLandscape && 'enrich-live__cover--landscape',
            )}
          >
            <SoftImg
              src={showPoster}
              alt={detail.code || 'poster'}
              className="enrich-live__cover-img"
              onLoad={(e) => {
                const el = e.currentTarget;
                const w = el.naturalWidth || 0;
                const h = el.naturalHeight || 0;
                setPosterLandscape(w > 0 && h > 0 && w > h);
              }}
            />
          </div>
        ) : (
          <div className="enrich-live__cover enrich-live__cover--empty">
            <span className="enrich-live__cover-empty-text">{coverHint}</span>
          </div>
        )}
        {localCovers.folder ? (
          <p className="enrich-live__cover-path allow-select">{localCovers.folder}</p>
        ) : null}
        {extraShots.length > 0 ? (
          <div className="enrich-live__cover-row">
            {extraShots.map((shot) => (
              <div key={shot.key} className="enrich-live__cover enrich-live__cover--shot">
                <SoftImg
                  src={shot.url}
                  alt={shot.label}
                  className="enrich-live__cover-img"
                />
                <span className="enrich-live__cover-cap">{shot.label}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <p className="settings-group-label">字段情况</p>
      <ul className="settings-group">
        {fields.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                {detail.status === 'running'
                  ? '拉取中…'
                  : '暂无字段结果（旧任务可能未保留）'}
              </span>
            </div>
          </li>
        ) : (
          fields.map((f) => {
            const srcLabel = String(f.source || '').trim();
            const rawVal = f.ok ? f.value || '有' : '无';
            const isPoster = f.id === 'poster' || f.label === '封面';
            const val =
              isPoster && f.ok && /^https?:\/\//i.test(String(f.value || ''))
                ? '有链接'
                : rawVal;
            return (
              <li key={f.id || f.label}>
                <div
                  className={cn(
                    'settings-kv enrich-live__field-kv',
                    !f.ok && 'enrich-live__field-kv--miss',
                  )}
                >
                  <span className="settings-kv__key enrich-live__field-key">
                    <span className="enrich-live__field-label">
                      {f.ok ? '✓ ' : '· '}
                      {f.label || f.id}
                    </span>
                    <FieldSourceIcon source={srcLabel} />
                  </span>
                  <span className="settings-kv__val enrich-live__field-val allow-select">
                    {val}
                  </span>
                </div>
              </li>
            );
          })
        )}
      </ul>

      <p className="settings-group-label">
        源耗时
        {timings.length > 0 ? ` · ${timings.length}` : ''}
        {wallMs != null ? ` · 拉源墙钟 ${wallMs}ms` : ''}
        {maxSrcMs > 0 ? ` · 最慢 ${maxSrcMs}ms` : ''}
      </p>
      <ul className="settings-group">
        {timings.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                {String(detail.source || '').trim() === 'local_scan'
                  ? '本地扫描分类，无各站刮削耗时；重刮后会写入番号目录 SONE-999.log'
                  : '暂无源耗时（刮削后写入番号目录 {番号}.log，清空·扫描可回读）'}
              </span>
            </div>
          </li>
        ) : (
          timings.map((t, i) => {
            const tone =
              t.status === 'done' || t.ok
                ? 'done'
                : t.status === 'fail' || t.error
                  ? 'fail'
                  : t.status === 'skipped'
                    ? 'skip'
                    : 'pending';
            return (
              <li key={`${t.id || i}-${t.ms || 0}`}>
                <div className="settings-kv">
                  <span className="settings-kv__key">
                    <span
                      className={cn(
                        'enrich-live__src-mark',
                        `enrich-live__src-mark--${tone}`,
                      )}
                    />
                    {t.id || '源'}
                  </span>
                  <span className="settings-kv__val">
                    {typeof t.ms === 'number' ? `${t.ms}ms` : '—'}
                    {t.poster ? ' · 封面' : ''}
                    {typeof t.actors === 'number' && t.actors > 0
                      ? ` · 女优${t.actors}`
                      : ''}
                    {t.error ? ` · ${t.error}` : ''}
                  </span>
                </div>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}

function fieldsFromSourceText(src: string): ScrapLibraryEnrichFieldRow[] {
  const text = String(src || '');
  const pick = (id: string, label: string, re: RegExp) => {
    const m = text.match(re);
    const val = (m?.[1] || '').trim();
    return { id, label, ok: Boolean(val), value: val || undefined };
  };
  return [
    pick('title', '标题', /^标题：(.+)$/m),
    pick('actors', '女优', /^女优：(.+)$/m),
    pick('studio', '片商', /^片商：(.+)$/m),
    pick('overview', '剧情', /^剧情：(.+)$/m),
  ];
}

function displayHitSource(source?: string): string {
  const s = String(source || '').trim();
  if (!s || s === 'log_recover' || s === 'recover' || s === 'local_scan') {
    return '';
  }
  return s;
}

function ensurePosterField(
  fields: ScrapLibraryEnrichFieldRow[],
  opts?: { posterDownloaded?: boolean },
): ScrapLibraryEnrichFieldRow[] {
  const posterDownloaded = opts?.posterDownloaded;
  const list = [...(fields || [])];
  const idx = list.findIndex(
    (f) => f.id === 'poster' || f.label === '封面',
  );
  const fallback: ScrapLibraryEnrichFieldRow = {
    id: 'poster',
    label: '封面',
    ok: Boolean(posterDownloaded),
    value: posterDownloaded ? '已落盘' : '无',
  };
  if (idx >= 0) {
    const cur = list[idx];
    const ok =
      typeof posterDownloaded === 'boolean'
        ? posterDownloaded || Boolean(cur.ok)
        : Boolean(cur.ok);
    list[idx] = {
      ...cur,
      id: 'poster',
      label: cur.label || '封面',
      ok,
      value:
        cur.value ||
        (ok ? (posterDownloaded ? '已落盘' : '有') : '无'),
      source: cur.source,
    };
    return list;
  }
  const titleIdx = list.findIndex(
    (f) => f.id === 'title' || f.label === '标题',
  );
  if (titleIdx >= 0) {
    list.splice(titleIdx + 1, 0, fallback);
    return list;
  }
  return [fallback, ...list];
}

export function EnrichLivePanel({
  regionId,
  label,
  onBack,
  onStatus,
  initialStatus = null,
  initialLogs = [],
}: {
  regionId: string;
  label: string;
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  /** 列表页已有状态，进场即展示，避免空白闪一下 */
  initialStatus?: ScrapLibraryEnrichJobStatus | null;
  initialLogs?: string[];
}) {
  const [tab, setTab] = useState<LiveTab>('pending');
  const [tabTouched, setTabTouched] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [dbDetail, setDbDetail] = useState<ScrapLibraryEnrichCurrent | null>(
    null,
  );
  const [st, setSt] = useState<ScrapLibraryEnrichJobStatus | null>(
    initialStatus,
  );
  const [persistedLogs, setPersistedLogs] = useState<string[]>(() =>
    Array.isArray(initialLogs) ? initialLogs.slice(-LOG_CAP) : [],
  );
  const [msg, setMsg] = useState('');
  const [stopping, setStopping] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [rescraping, setRescraping] = useState(false);
  const [hydrated, setHydrated] = useState(Boolean(initialStatus));

  const [logsCleared, setLogsCleared] = useState(false);
  const [queueScanning, setQueueScanning] = useState(false);
  const [retryingFails, setRetryingFails] = useState(false);
  const [retryingSofts, setRetryingSofts] = useState(false);
  const [codeQuery, setCodeQuery] = useState('');
  const [searchCode, setSearchCode] = useState('');
  const [searchItems, setSearchItems] = useState<ScrapLibraryEnrichQueueItem[]>(
    [],
  );
  const [searching, setSearching] = useState(false);
  const sessionLiveRef = useRef(false);
  const queueScanDoneRef = useRef(false);
  const searchActiveRef = useRef(false);
  searchActiveRef.current = Boolean(searchCode);
  const [queueItems, setQueueItems] = useState<ScrapLibraryEnrichQueueItem[]>(
    [],
  );
  const [queueCounts, setQueueCounts] = useState({
    pending: 0,
    running: 0,
    done: 0,
    soft: 0,
    fail: 0,
  });
  /** 各 tab 库内可翻页行数；角标用 queueCounts 全量 */
  const [listTotals, setListTotals] = useState<Partial<Record<LiveTab, number>>>(
    {},
  );
  const [queuePage, setQueuePage] = useState(1);
  const [queuePaging, setQueuePaging] = useState(false);
  const queuePageRef = useRef(1);
  queuePageRef.current = queuePage;
  /** 切 tab / 翻页拉库期间，禁止 SSE 用工作队列重排列表 */
  const queueHydratingRef = useRef(false);
  /** 成功/软成功/失败：角标上涨时防抖回读库表（按 updated_at），勿用工作队列插旧号 */
  const resultTabReloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const resultTabCountRef = useRef({ soft: 0, done: 0, fail: 0 });
  const queuePaneRef = useRef<HTMLDivElement | null>(null);
  /** 缺口总数（可大于列表条数）；tab 切换读表时仍保留 */
  const pendingTotalRef = useRef(0);
  /** 各 tab 仅缓存第 1 页，避免翻页结果污染回切 */
  const tabCacheRef = useRef<Partial<Record<LiveTab, ScrapLibraryEnrichQueueItem[]>>>(
    {},
  );
  /**
   * 成功类 tab 已从库表 hydrate 过：扫描 SSE 的 samples*（按扫序多为 AARM）
   * 不得再盖掉库表按 updated_at 的真列表。
   */
  const tabDbLoadedRef = useRef<Partial<Record<LiveTab, boolean>>>({});
  const loadSeqRef = useRef(0);
  const tabRef = useRef<LiveTab>(tab);
  tabRef.current = tab;

  function applyQueuePayload(data: {
    counts?: {
      pending?: number;
      running?: number;
      done?: number;
      soft?: number;
      fail?: number;
    };
    items?: ScrapLibraryEnrichQueueItem[];
    pendingTotal?: number;
    scannedN?: number;
    /** 库内可翻页行数；角标与分类全量对齐 */
    total?: number;
    localDone?: number;
    localSoft?: number;
    localFail?: number;
    /** 写入哪个 tab 的缓存；默认当前 tab */
    cacheTab?: LiveTab;
    /** 切 tab 只刷列表时勿改角标，避免数字跟着 tab 跳 */
    updateCounts?: boolean;
    /** 列表页码；仅第 1 页写入 tab 缓存 */
    page?: number;
  }) {
    const counts = data.counts || {
      pending: 0,
      running: 0,
      done: 0,
      soft: 0,
      fail: 0,
    };
    const hinted = Number(
      data.pendingTotal ?? data.scannedN ?? 0,
    );
    const shouldUpdateCounts = data.updateCounts !== false;
    if (shouldUpdateCounts) {
      const pendingFromServer = Number(counts.pending || 0);
      // 扫描回包带 pendingTotal（全量）；普通读表只有样例行数
      const pending = hinted > 0 ? hinted : pendingFromServer;
      if (pending > 0) {
        pendingTotalRef.current = pending;
        writeCachedPendingTotal(regionId, pending);
      } else {
        pendingTotalRef.current = 0;
        try {
          sessionStorage.removeItem(pendingTotalStorageKey(regionId));
        } catch {
          /* ignore */
        }
      }
      const noMid =
        !st?.running ||
        st?.halt === 'pause' ||
        st?.halt === 'stop' ||
        st?.phase === 'paused' ||
        st?.phase === 'stopped';
      setQueueCounts({
        pending: noMid
          ? pending + Number(counts.running || 0)
          : pending,
        running: noMid ? 0 : Number(counts.running || 0),
        done: Number(
          data.localDone ?? counts.done ?? 0,
        ),
        soft: Number(data.localSoft ?? counts.soft ?? 0),
        fail: Number(data.localFail ?? counts.fail ?? 0),
      });
      // 扫描全量分类写入后，列表可翻页总数与角标对齐（含未处理）
      const doneN = Number(data.localDone ?? counts.done ?? 0);
      const softN = Number(data.localSoft ?? counts.soft ?? 0);
      const failN = Number(data.localFail ?? counts.fail ?? 0);
      setListTotals((prev) => ({
        ...prev,
        ...(pending > 0 ? { pending } : {}),
        ...(doneN > 0 ? { done: doneN } : {}),
        soft: softN,
        ...(failN > 0 ? { fail: failN } : {}),
      }));
    } else {
      // 切 tab 读表：仍同步成功/软成功/失败角标（允许 soft 下降）
      const doneN = Number(counts.done || 0);
      const softN = Number(counts.soft || 0);
      const failN = Number(counts.fail || 0);
      if (doneN > 0 || softN >= 0 || failN > 0) {
        setQueueCounts((prev) => ({
          ...prev,
          done: doneN > 0 ? doneN : Number(prev.done || 0),
          soft: softN,
          fail: failN > 0 ? failN : Number(prev.fail || 0),
        }));
        setListTotals((prev) => ({
          ...prev,
          ...(doneN > 0 ? { done: doneN } : {}),
          soft: softN,
          ...(failN > 0 ? { fail: failN } : {}),
        }));
      }
    }
    const curTab = data.cacheTab || tabRef.current;
    if (typeof data.total === 'number' && Number.isFinite(data.total)) {
      const listed = Math.max(0, Math.floor(Number(data.total) || 0));
      setListTotals((prev) => {
        if (curTab !== 'pending') {
          return { ...prev, [curTab]: listed };
        }
        // 未处理 total 以本次接口为准；丢掉明显虚高的旧缓存
        const cached = Number(pendingTotalRef.current || 0);
        const prevN = Number(prev.pending || 0);
        let floor = listed;
        for (const n of [cached, prevN]) {
          if (n <= 0 || listed <= 0) continue;
          const ratio = n / listed;
          if (ratio >= 0.85 && ratio <= 1.25) {
            floor = Math.max(floor, n);
          }
        }
        if (listed > 0 && (cached <= 0 || cached / listed > 1.25)) {
          pendingTotalRef.current = listed;
          writeCachedPendingTotal(regionId, listed);
        }
        return { ...prev, pending: floor };
      });
    }
    const noMid =
      !st?.running ||
      st?.halt === 'pause' ||
      st?.halt === 'stop' ||
      st?.phase === 'paused' ||
      st?.phase === 'stopped';
    if (curTab === 'running' && noMid) {
      tabCacheRef.current.running = [];
      if (tabRef.current === 'running') {
        setQueueItems([]);
      }
      return;
    }
    if (Array.isArray(data.items)) {
      const raw = data.items;
      // 软缺口只影响本页展示，不改全局角标（角标以 SSE/扫描 counts 为准）
      let items = raw.map(normalizeSoftSuccessRow);
      if (curTab === 'fail') {
        items = items.filter((r) => rowStatus(r.status) === 'fail');
      } else if (curTab === 'soft') {
        items = items.filter(
          (r) => rowStatus(r.status) === 'done' && isPartialOk(r),
        );
      } else if (curTab === 'done') {
        items = items.filter(
          (r) => rowStatus(r.status) === 'done' && !isPartialOk(r),
        );
      }
      const pageN = Math.max(
        1,
        Math.floor(data.page || queuePageRef.current || 1),
      );
      // 只缓存第 1 页；列表必须同步 setState（startTransition 会被 status 流打断）
      if (pageN <= 1) {
        tabCacheRef.current[curTab] = items;
        if (curTab === 'done' || curTab === 'soft' || curTab === 'fail') {
          tabDbLoadedRef.current[curTab] = true;
        }
      }
      // 过期页响应丢弃，避免翻页后又被旧请求盖回第一页
      if (tabRef.current === curTab && pageN === queuePageRef.current) {
        setQueueItems(items);
      }
    }
    // 翻页时也对齐角标总数（以库 counts 为准）
    if (
      data.updateCounts === false &&
      data.counts &&
      typeof data.counts === 'object'
    ) {
      const c = data.counts;
      const pendingFromServer = Number(c.pending || 0);
      // 服务端估算为准；仅当本地缓存略大（扫描中）时保留，避免旧虚高卡死角标
      const cached = pendingTotalRef.current || 0;
      let pending = pendingFromServer;
      if (cached > 0 && pendingFromServer > 0) {
        const ratio = cached / pendingFromServer;
        if (ratio >= 0.85 && ratio <= 1.25) {
          pending = Math.max(pendingFromServer, cached);
        } else {
          pending = pendingFromServer;
          pendingTotalRef.current = pendingFromServer;
          writeCachedPendingTotal(regionId, pendingFromServer);
        }
      } else if (pendingFromServer > 0) {
        pendingTotalRef.current = pendingFromServer;
        writeCachedPendingTotal(regionId, pendingFromServer);
      }
      setQueueCounts({
        pending,
        running: Number(c.running || 0),
        done: Number(c.done || 0),
        soft: Number(c.soft || 0),
        fail: Number(c.fail || 0),
      });
    }
  }

  async function loadQueueTab(status: LiveTab, page = queuePageRef.current) {
    if (logsCleared) return;
    const seq = ++loadSeqRef.current;
    const pageSafe = Math.max(1, Math.floor(page || 1));
    queueHydratingRef.current = true;
    try {
      const data = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        status,
        limit: QUEUE_PAGE_SIZE,
        offset: (pageSafe - 1) * QUEUE_PAGE_SIZE,
      });
      if (seq !== loadSeqRef.current) return;
      if (status === 'done' || status === 'soft' || status === 'fail') {
        tabDbLoadedRef.current[status] = true;
      }
      applyQueuePayload({
        ...data,
        cacheTab: status,
        updateCounts: false,
        page: pageSafe,
        pendingTotal: pendingTotalRef.current || readCachedPendingTotal(regionId),
      });
    } finally {
      if (seq === loadSeqRef.current) {
        queueHydratingRef.current = false;
      }
    }
  }

  function goQueuePage(next: number) {
    setTabTouched(true);
    const listed = Number(listTotals[tab] ?? queueCounts[tab] ?? 0);
    const total = Math.max(1, Math.ceil(listed / QUEUE_PAGE_SIZE));
    const p = Math.max(1, Math.min(total, Math.floor(next || 1)));
    if (p === queuePageRef.current) return;
    setQueuePage(p);
  }

  function clearCodeSearch() {
    setSearchCode('');
    setCodeQuery('');
    setSearchItems([]);
    setSearching(false);
    setSelectedKey(null);
    setDbDetail(null);
  }

  async function runCodeSearch(raw?: string) {
    const q = String(raw ?? codeQuery)
      .trim()
      .toUpperCase()
      .replace(/[\s　]+/g, '');
    if (!q) {
      clearCodeSearch();
      return;
    }
    setSearching(true);
    setSearchCode(q);
    setCodeQuery(q);
    setSelectedKey(null);
    setDbDetail(null);
    // 先用各 tab 缓存做即时预览（仍无视当前 tab）
    const localHits: ScrapLibraryEnrichQueueItem[] = [];
    const seen = new Set<string>();
    const pushLocal = (row: ScrapLibraryEnrichQueueItem) => {
      const code = String(row.code || '')
        .trim()
        .toUpperCase()
        .replace(/[\s　]+/g, '');
      if (!code) return;
      if (!(code === q || (q.length >= 2 && code.startsWith(q)))) return;
      const key = String(row.itemId || row.logId || code).trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      localHits.push(normalizeSoftSuccessRow(row));
    };
    for (const rows of Object.values(tabCacheRef.current)) {
      if (!Array.isArray(rows)) continue;
      for (const r of rows) pushLocal(r);
    }
    for (const r of queueItems) pushLocal(r);
    if (localHits.length) setSearchItems(localHits);
    try {
      // 故意不传 status：全局跨未处理/处理中/成功/软成功/失败
      const data = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        code: q,
        limit: 50,
      });
      setSearchItems(
        (data.items || []).map((r) => normalizeSoftSuccessRow(r)),
      );
    } catch (e) {
      if (!localHits.length) setSearchItems([]);
      setMsg(e instanceof Error ? e.message : '搜索失败');
    } finally {
      setSearching(false);
    }
  }

  async function runQueueScan() {
    setLogsCleared(false);
    setQueueScanning(true);
    setMsg('');
    tabCacheRef.current = {};
    tabDbLoadedRef.current = {};
    try {
      const scanned = await scanScrapLibraryEnrichQueue({ region: regionId });
      queueScanDoneRef.current = true;
      enrichLiveBootstrapped.add(regionId);
      applyQueuePayload({ ...scanned, cacheTab: 'pending' });
      const curTab = tabRef.current;
      if (curTab !== 'pending') {
        await loadQueueTab(curTab);
      }
      const n = Number(
        scanned.pendingTotal ?? scanned.scannedN ?? scanned.counts?.pending ?? 0,
      );
      const done = Number(scanned.counts?.done || scanned.localDone || 0);
      const soft = Number(scanned.counts?.soft || scanned.localSoft || 0);
      const fail = Number(scanned.counts?.fail || scanned.localFail || 0);
      setMsg(
        `已扫描本地 · 未处理 ${n.toLocaleString()} · 成功 ${done.toLocaleString()} · 软成功 ${soft.toLocaleString()} · 失败 ${fail.toLocaleString()}（分类全量可翻页；未处理按全量虚拟翻页）`,
      );
      return true;
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '队列扫描失败');
      throw e;
    } finally {
      setQueueScanning(false);
    }
  }

  useEffect(() => {
    queueScanDoneRef.current = false;
    pendingTotalRef.current = readCachedPendingTotal(regionId);
    tabCacheRef.current = {};
    tabDbLoadedRef.current = {};
    loadSeqRef.current += 1;
    setQueueItems([]);
    setQueueCounts({ pending: 0, running: 0, done: 0, soft: 0, fail: 0 });
    setListTotals({});
    setQueuePage(1);
    setLogsCleared(false);
    setQueueScanning(false);
  }, [regionId]);

  // 进页：有队列只读表；无数据才自动扫描。再进同区不重扫。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const cachedPending = readCachedPendingTotal(regionId);
      if (cachedPending > 0) pendingTotalRef.current = cachedPending;

      try {
        const curTab = tabRef.current;
        const existing = await getScrapLibraryEnrichQueueLog({
          region: regionId,
          status: curTab,
          limit: QUEUE_PAGE_SIZE,
          offset: 0,
        });
        if (cancelled) return;
        const c = existing.counts || {
          pending: 0,
          running: 0,
          done: 0,
          soft: 0,
          fail: 0,
        };
        const hasRows =
          Number(c.pending || 0) +
            Number(c.running || 0) +
            Number(c.done || 0) +
            Number(c.soft || 0) +
            Number(c.fail || 0) >
          0;

        if (hasRows || enrichLiveBootstrapped.has(regionId)) {
          enrichLiveBootstrapped.add(regionId);
          queueScanDoneRef.current = true;
          const serverPending = Number(c.pending || 0);
          // 缓存只允许接近服务端的值；虚高（旧全量补写/双计）直接丢弃
          let pendingTotal = serverPending;
          if (serverPending > 0 && cachedPending > 0) {
            const ratio = cachedPending / serverPending;
            if (ratio >= 0.85 && ratio <= 1.25) {
              pendingTotal = Math.max(serverPending, cachedPending);
            } else {
              try {
                sessionStorage.removeItem(pendingTotalStorageKey(regionId));
              } catch {
                /* ignore */
              }
              pendingTotalRef.current = serverPending;
              pendingTotal = serverPending;
            }
          } else if (serverPending === 0 && cachedPending > 0) {
            try {
              sessionStorage.removeItem(pendingTotalStorageKey(regionId));
            } catch {
              /* ignore */
            }
            pendingTotalRef.current = 0;
            pendingTotal = 0;
          }
          applyQueuePayload({
            ...existing,
            page: 1,
            pendingTotal,
          });
          setQueueScanning(false);
          return;
        }

        // 空队列：不自动全量扫描（会卡在「扫描未处理…」）
        enrichLiveBootstrapped.add(regionId);
        queueScanDoneRef.current = true;
        if (cachedPending > 0) {
          try {
            sessionStorage.removeItem(pendingTotalStorageKey(regionId));
          } catch {
            /* ignore */
          }
          pendingTotalRef.current = 0;
        }
        applyQueuePayload({
          ...existing,
          items: [],
          pendingTotal: 0,
        });
        setQueueScanning(false);
        setMsg(
          '打开分区开关即可边扫边刮；或点「清空·扫描」按向量骨架生成未处理队列',
        );
      } catch (e) {
        if (cancelled) return;
        setQueueScanning(false);
        setMsg(e instanceof Error ? e.message : '队列加载失败');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅 region 引导
  }, [regionId]);

  // 切换 tab / 翻页：第 1 页可用缓存瞬切，再拉当前页（同步写入列表）
  useEffect(() => {
    if (!queueScanDoneRef.current || logsCleared) return;
    queuePaneRef.current?.scrollTo?.({ top: 0 });
    if (queuePage === 1) {
      const cached = tabCacheRef.current[tab];
      if (cached) {
        setQueueItems(cached);
      }
    } else {
      // 翻页先清空，避免仍显示上一页造成「没变」的错觉
      setQueueItems([]);
    }
    let alive = true;
    setQueuePaging(true);
    void (async () => {
      try {
        await loadQueueTab(tab, queuePage);
      } catch {
        if (!alive) return;
      } finally {
        if (alive) setQueuePaging(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tab/页码变化拉一次
  }, [tab, queuePage, regionId, logsCleared]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      if (logsCleared) return;
      // 任务进行中不要灌历史库日志，否则角标一上来就是 200
      if (initialStatus?.running) return;
      try {
        const data = await getScrapLibraryEnrichLogs({
          region: regionId,
          limit: LOG_CAP,
        });
        if (!alive || logsCleared || sessionLiveRef.current) return;
        const lines = Array.isArray(data.log) ? data.log : [];
        if (lines.length) {
          setPersistedLogs((prev) =>
            prev.length ? mergeLogLines(prev, lines) : lines.slice(-LOG_CAP),
          );
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      alive = false;
    };
  }, [regionId, logsCleared, initialStatus?.running]);

  useEffect(() => {
    let alive = true;
    const ac = new AbortController();
    let lastUiAt = 0;
    let pendingData: ScrapLibraryEnrichJobStatus | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const LIVE_UI_GAP_MS = 750;
    let lastLogTail = '';

    function applyStatusCore(data: ScrapLibraryEnrichJobStatus) {
      if (!alive) return;
      setSt(data);
      setHydrated(true);
      const qs = data.queueScan;
      const qsHere =
        Boolean(qs?.active) &&
        (!qs?.region || qs.region === regionId);
      if (qsHere) {
        // 进度只更新角标 / 空态文案，不打 Toast（AppMsg 会因文案变化一直弹）
        setQueueCounts((prev) => ({
          pending: Number(prev.pending || 0),
          running: Number(prev.running || 0),
          done: Number(qs?.done || 0),
          soft: Number(qs?.soft || 0),
          fail: Number(qs?.fail || 0),
        }));
        // 边扫边看：仅在尚未从库表拉过该 tab 时用样例占位。
        // 点过成功/失败等 tab 后必须以库表为准，否则扫序样例（常为 AARM*）会几秒盖掉真列表。
        const want = tabRef.current;
        if (
          (want === 'done' || want === 'soft' || want === 'fail') &&
          !tabDbLoadedRef.current[want] &&
          !queueHydratingRef.current &&
          !searchActiveRef.current
        ) {
          const rawSamples =
            want === 'done'
              ? qs?.samplesDone
              : want === 'soft'
                ? qs?.samplesSoft
                : qs?.samplesFail;
          if (Array.isArray(rawSamples) && rawSamples.length > 0) {
            const items = rawSamples.map((r) => normalizeSoftSuccessRow(r));
            tabCacheRef.current[want] = items;
            if (tabRef.current === want) {
              // 扫描预览勿 startTransition：会被密集 status 流打断，列表会一直空
              setQueueItems(items);
            }
          }
        }
      }
      const live = data.regionLogs?.[regionId] || [];
      const liveHere =
        Boolean(data.running) &&
        (!data.currentRegion || data.currentRegion === regionId);
      if (liveHere) {
        if (!sessionLiveRef.current) {
          // 本轮开始：只用内存日志，丢掉历史 200
          sessionLiveRef.current = true;
          const boot = Array.isArray(live) ? live.slice(-LOG_CAP) : [];
          lastLogTail = boot.length ? boot[boot.length - 1]! : '';
          setPersistedLogs(boot);
        } else if (!logsCleared && Array.isArray(live) && live.length) {
          const tip = live[live.length - 1] || '';
          if (tip !== lastLogTail) {
            lastLogTail = tip;
            setPersistedLogs((prev) => mergeLogLines(prev, live));
          }
        }
      } else {
        sessionLiveRef.current = false;
        if (!logsCleared) {
          if (Array.isArray(live) && live.length) {
            const tip = live[live.length - 1] || '';
            if (tip !== lastLogTail) {
              lastLogTail = tip;
              setPersistedLogs((prev) => mergeLogLines(prev, live));
            }
          }
        } else if (!data.running) {
          if (!live.length) {
            lastLogTail = '';
            setPersistedLogs([]);
          }
        }
      }

      // 运行中对齐本区计数；暂停/结束后「处理中」必须为 0（退回未处理）
      // 全局 queueCounts 只属于 currentRegion / queueCountsRegion，禁止 FC2 吃有码数字
      const byRegion = data.regionQueueCounts;
      const qcRegion = String(
        data.queueCountsRegion || data.currentRegion || '',
      ).trim();
      const regionQc =
        byRegion && typeof byRegion === 'object'
          ? byRegion[regionId] ||
            byRegion[
              Object.keys(byRegion).find(
                (k) => k === regionId || k.toLowerCase() === regionId.toLowerCase(),
              ) || ''
            ]
          : null;
      const qc =
        regionQc ||
        (qcRegion && qcRegion === regionId ? data.queueCounts : null);
      const halted =
        data.halt === 'pause' ||
        data.halt === 'stop' ||
        data.phase === 'paused' ||
        data.phase === 'stopping' ||
        data.phase === 'stopped' ||
        !data.running;
      // 用本区 library.total 纠正串区缓存（曾把有码 12 万写进 FC2 sessionStorage）
      const libRow =
        data.library && typeof data.library === 'object'
          ? data.library[regionId] ||
            data.library[
              Object.keys(data.library).find(
                (k) => k === regionId || k.toLowerCase() === regionId.toLowerCase(),
              ) || ''
            ]
          : null;
      const libTotal = Number(
        (libRow as { vectorTotal?: number; total?: number } | null)
          ?.vectorTotal ??
          (libRow as { total?: number } | null)?.total ??
          0,
      );
      if (libTotal > 0) {
        const cached = readCachedPendingTotal(regionId);
        if (cached > libTotal) {
          pendingTotalRef.current = 0;
          try {
            sessionStorage.removeItem(pendingTotalStorageKey(regionId));
          } catch {
            /* ignore */
          }
        }
      }
      if (qc && (liveHere || (halted && (regionQc || qcRegion === regionId)))) {
        const runN = halted ? 0 : Number(qc.running || 0);
        const statusPending =
          Number(qc.pending || 0) + (halted ? Number(qc.running || 0) : 0);
        // 以服务端为准；勿 Math.max 旧缓存，否则会把历史 12 万钉死在角标上
        const pendingN =
          libTotal > 0 ? Math.min(statusPending, libTotal) : statusPending;
        if (halted) {
          pendingTotalRef.current = pendingN;
          writeCachedPendingTotal(regionId, pendingN);
        }
        // 队列表写全部分类行；角标与 local totals / DB 对齐。
        const preferBadge = (server: number, prev: number) =>
          server === 500 && prev > 500 ? prev : server;
        setQueueCounts((prev) => ({
          pending: pendingN,
          running: runN,
          // 空闲以服务端为准（软成功升档后 soft 必须能下降）；运行中仍取大防漏计
          done: halted
            ? preferBadge(Number(qc.done || 0), Number(prev.done || 0))
            : Math.max(Number(prev.done || 0), Number(qc.done || 0)),
          soft: halted
            ? preferBadge(Number(qc.soft || 0), Number(prev.soft || 0))
            : Math.max(Number(prev.soft || 0), Number(qc.soft || 0)),
          fail: halted
            ? preferBadge(Number(qc.fail || 0), Number(prev.fail || 0))
            : Math.max(Number(prev.fail || 0), Number(qc.fail || 0)),
        }));
      }
      if (halted) {
        tabCacheRef.current.running = [];
        if (tabRef.current === 'running') {
          startTransition(() => setQueueItems([]));
        }
        delete tabCacheRef.current.pending;
      } else if (liveHere && tabRef.current === 'running') {
        const liveRunning = (data.queue || []).filter(
          (r) => rowStatus(r.status) === 'running',
        );
        tabCacheRef.current.running = liveRunning;
        // 有 monitor.inflight 时列表走监控行，勿每帧 setQueueItems 打断滚动
        const monN = Array.isArray(data.monitor?.inflight)
          ? data.monitor.inflight.length
          : 0;
        if (monN <= 0) {
          startTransition(() => setQueueItems(liveRunning));
        }
      } else if (
        liveHere &&
        !searchActiveRef.current &&
        !queueHydratingRef.current &&
        queuePageRef.current === 1 &&
        (tabRef.current === 'done' ||
          tabRef.current === 'soft' ||
          tabRef.current === 'fail')
      ) {
        // 成功类 tab：只跟库表 updated_at（最新在上）。
        // 勿用 data.queue 抽样插顶——工作队列里残留的旧 AARM 会被当成「新项」顶上来。
        const want = tabRef.current;
        const curRaw = data.current;
        let shouldReload = false;
        if (curRaw && typeof curRaw === 'object') {
          const cur = normalizeSoftSuccessRow(
            curRaw as ScrapLibraryEnrichQueueItem,
          );
          const st = rowStatus(cur.status);
          const match =
            (want === 'fail' && st === 'fail') ||
            (want === 'soft' && st === 'done' && isPartialOk(cur)) ||
            (want === 'done' && st === 'done' && !isPartialOk(cur));
          if (match && (cur.code || cur.itemId)) {
            shouldReload = true;
            setQueueItems((prev) => {
              const base = prev.map(normalizeSoftSuccessRow);
              const key = rowKey(cur);
              const code = String(cur.code || '')
                .trim()
                .toUpperCase();
              const without = base.filter((r) => {
                if (rowKey(r) === key) return false;
                if (
                  code &&
                  String(r.code || '')
                    .trim()
                    .toUpperCase() === code
                ) {
                  return false;
                }
                return true;
              });
              const next = [cur, ...without].slice(0, QUEUE_PAGE_SIZE);
              tabCacheRef.current[want] = next;
              return next;
            });
          }
        }
        // 角标上涨也回读（current 有时已被下一号清掉）
        const badgeDone = Number(qc?.done || 0);
        const badgeFail = Number(qc?.fail || 0);
        const badgeSoft = Number(
          (qc as { soft?: number } | null)?.soft ||
            resultTabCountRef.current.soft,
        );
        const prevBadge = resultTabCountRef.current;
        if (want === 'soft' && badgeSoft > prevBadge.soft) shouldReload = true;
        if (want === 'done' && badgeDone > prevBadge.done) shouldReload = true;
        if (want === 'fail' && badgeFail > prevBadge.fail) shouldReload = true;
        resultTabCountRef.current = {
          soft: Math.max(prevBadge.soft, badgeSoft),
          done: Math.max(prevBadge.done, badgeDone),
          fail: Math.max(prevBadge.fail, badgeFail),
        };
        if (shouldReload) {
          delete tabCacheRef.current[want];
          if (resultTabReloadTimerRef.current) {
            clearTimeout(resultTabReloadTimerRef.current);
          }
          const reloadWant = want;
          resultTabReloadTimerRef.current = setTimeout(() => {
            resultTabReloadTimerRef.current = null;
            if (
              tabRef.current !== reloadWant ||
              queuePageRef.current !== 1 ||
              searchActiveRef.current
            ) {
              return;
            }
            void loadQueueTab(reloadWant, 1);
          }, 900);
        }
      }
    }

    function applyStatus(data: ScrapLibraryEnrichJobStatus) {
      if (!alive) return;
      // 暂停/结束立刻刷；运行中合并到 750ms，避免 monitor 时钟把主线程打满
      const terminal =
        !data.running ||
        data.halt === 'pause' ||
        data.halt === 'stop' ||
        data.phase === 'paused' ||
        data.phase === 'stopping' ||
        data.phase === 'stopped';
      if (terminal) {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        pendingData = null;
        lastUiAt = Date.now();
        applyStatusCore(data);
        return;
      }
      const now = Date.now();
      pendingData = data;
      if (now - lastUiAt >= LIVE_UI_GAP_MS) {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        lastUiAt = now;
        pendingData = null;
        applyStatusCore(data);
        return;
      }
      if (!flushTimer) {
        flushTimer = setTimeout(() => {
          flushTimer = null;
          if (!alive || !pendingData) return;
          lastUiAt = Date.now();
          const next = pendingData;
          pendingData = null;
          applyStatusCore(next);
        }, Math.max(80, LIVE_UI_GAP_MS - (now - lastUiAt)));
      }
    }

    void (async () => {
      try {
        await subscribeScrapLibraryEnrichStatus(applyStatus, {
          signal: ac.signal,
          onError: (message) => {
            if (!alive) return;
            setHydrated(true);
            setMsg(message);
          },
        });
      } catch (e) {
        if (!alive) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (e instanceof Error && e.name === 'AbortError') return;
        setHydrated(true);
        setMsg(e instanceof Error ? e.message : '状态推送失败');
      }
    })();

    return () => {
      alive = false;
      ac.abort();
      if (flushTimer) clearTimeout(flushTimer);
    };
  }, [regionId, logsCleared]);

  const hasCheckpoint = Boolean(st?.checkpoints?.[regionId]);

  async function onPause() {
    if (stopping || !st?.running) return;
    setStopping(true);
    try {
      await pauseScrapLibraryEnrich();
      // 立刻清掉「处理中」中间态，等 SSE 再对齐角标
      setQueueCounts((prev) => ({
        ...prev,
        running: 0,
        pending: Math.max(
          Number(prev.pending || 0) + Number(prev.running || 0),
          pendingTotalRef.current || 0,
        ),
      }));
      tabCacheRef.current.running = [];
      delete tabCacheRef.current.pending;
      if (tabRef.current === 'running') {
        startTransition(() => setQueueItems([]));
      }
      onStatus('正在暂停刮削…', 'mute');
      setMsg('已暂停 · 进行中已退回未处理');
    } catch (e) {
      const text = e instanceof Error ? e.message : '暂停失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setStopping(false);
    }
  }

  async function onRetryFails() {
    if (retryingFails || retryingSofts || clearing) return;
    const failN = Number(queueCounts.fail || 0);
    if (failN <= 0) {
      setMsg('没有失败任务');
      return;
    }
    setRetryingFails(true);
    setMsg('');
    try {
      const data = await retryScrapLibraryEnrichFails({ region: regionId });
      const n = Number(data.reopened || 0);
      const counts = data.counts || {};
      const nextPending = Number(counts.pending || 0);
      const nextFail = Number(counts.fail || 0);
      const nextDone = Number(counts.done || 0);
      const nextSoft = Number(counts.soft || 0);
      setQueueCounts({
        pending: nextPending,
        running: Number(counts.running || 0),
        done: nextDone,
        soft: nextSoft,
        fail: nextFail,
      });
      setListTotals((prev) => ({
        ...prev,
        pending: Math.max(nextPending, Number(prev.pending || 0)),
        fail: nextFail,
        done: nextDone || prev.done,
        soft: nextSoft || prev.soft,
      }));
      pendingTotalRef.current = Math.max(pendingTotalRef.current, nextPending);
      if (nextPending > 0) {
        writeCachedPendingTotal(regionId, nextPending);
      }
      // 失败列表已迁走，清缓存避免回看仍显示旧失败
      delete tabCacheRef.current.fail;
      delete tabCacheRef.current.pending;
      setTabTouched(true);
      setQueuePage(1);
      setTab('pending');
      await loadQueueTab('pending', 1);
      if (n <= 0) {
        setMsg('没有可重试的失败（可能已在未处理中）');
        onStatus('无失败可重试', 'mute');
      } else {
        const tip = data.injected
          ? `已重试 ${n.toLocaleString()} 条 · 插入当前任务优先处理`
          : `已重试 ${n.toLocaleString()} 条 · 已转入未处理（优先）`;
        setMsg(tip);
        onStatus(tip, 'ok');
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '重试失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRetryingFails(false);
    }
  }

  async function onRetrySofts() {
    if (retryingSofts || retryingFails || clearing) return;
    const softN = Number(queueCounts.soft || 0);
    if (softN <= 0) {
      setMsg('没有软成功任务');
      return;
    }
    setRetryingSofts(true);
    setMsg('');
    try {
      const data = await retryScrapLibraryEnrichSofts({ region: regionId });
      const n = Number(data.reopened || 0);
      const counts = data.counts || {};
      const nextPending = Number(counts.pending || 0);
      const nextFail = Number(counts.fail || 0);
      const nextDone = Number(counts.done || 0);
      const nextSoft = Number(counts.soft || 0);
      setQueueCounts({
        pending: nextPending,
        running: Number(counts.running || 0),
        done: nextDone,
        soft: nextSoft,
        fail: nextFail,
      });
      setListTotals((prev) => ({
        ...prev,
        pending: Math.max(nextPending, Number(prev.pending || 0)),
        soft: nextSoft,
        done: nextDone,
        fail: nextFail || prev.fail,
      }));
      pendingTotalRef.current = Math.max(pendingTotalRef.current, nextPending);
      if (nextPending > 0) {
        writeCachedPendingTotal(regionId, nextPending);
      }
      delete tabCacheRef.current.soft;
      delete tabCacheRef.current.pending;
      setTabTouched(true);
      setQueuePage(1);
      setTab('pending');
      await loadQueueTab('pending', 1);
      if (n <= 0) {
        setMsg('没有可重试的软成功（可能已在未处理中）');
        onStatus('无软成功可重试', 'mute');
      } else {
        const tip = data.injected
          ? `已重试 ${n.toLocaleString()} 条软成功 · 插入当前任务优先处理`
          : `已重试 ${n.toLocaleString()} 条软成功 · 已转入未处理（优先）`;
        setMsg(tip);
        onStatus(tip, 'ok');
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '软成功重试失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRetryingSofts(false);
    }
  }

  async function onClearAndScan() {
    if (clearing || queueScanning || retryingFails || retryingSofts) return;
    setClearing(true);
    setLogsCleared(true);
    setPersistedLogs([]);
    setQueueItems([]);
    setQueueCounts({ pending: 0, running: 0, done: 0, soft: 0, fail: 0 });
    setListTotals({});
    pendingTotalRef.current = 0;
    tabCacheRef.current = {};
    loadSeqRef.current += 1;
    enrichLiveBootstrapped.delete(regionId);
    try {
      sessionStorage.removeItem(pendingTotalStorageKey(regionId));
    } catch {
      /* ignore */
    }
    setSt((prev) =>
      prev
        ? {
            ...prev,
            log: [],
            regionLogs: {
              ...(prev.regionLogs || {}),
              [regionId]: [],
            },
            regionLogCounts: {
              ...(prev.regionLogCounts || {}),
              [regionId]: 0,
            },
            queue: [],
            queueCounts: {
              pending: 0,
              running: 0,
              done: 0,
              soft: 0,
              fail: 0,
            },
            // 丢掉旧检查点，避免「已暂停 · 历史 fail=622」残留
            checkpoints: Object.fromEntries(
              Object.entries(prev.checkpoints || {}).filter(
                ([rid]) => rid !== regionId,
              ),
            ),
            progress: prev.running
              ? prev.progress
              : {
                  stage: 'idle',
                  label: '已清空',
                  done: 0,
                  total: 0,
                  ok: 0,
                  failed: 0,
                  percent: 0,
                },
            paused: false,
            halt: prev.running ? prev.halt : null,
          }
        : prev,
    );
    setMsg('');
    onStatus('清空扫描…', 'mute');
    try {
      // 刮削中禁止硬清：先暂停，避免与入队死锁/卡死「清空中…」
      if (st?.running) {
        try {
          await pauseScrapLibraryEnrich();
        } catch {
          /* 仍尝试清空；后端忙会返回明确错误 */
        }
      }
      await clearScrapLibraryEnrichLogs({ region: regionId });
      await runQueueScan();
      onStatus('已清空并重新扫描', 'ok');
    } catch (e) {
      const text = e instanceof Error ? e.message : '清空扫描失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setClearing(false);
    }
  }

  async function resolveItemIdForRow(
    row: ScrapLibraryEnrichQueueItem,
  ): Promise<string> {
    const iid = String(row.itemId || '').trim();
    if (iid) return iid;
    const code = String(row.code || '').trim();
    if (!code) return '';
    const page = await listScrapLibraryEmbedItems({ q: code, limit: 8 });
    const hit =
      (page.items || []).find(
        (it) =>
          String(it.code || '').toUpperCase() === code.toUpperCase(),
      ) || (page.items || [])[0];
    return String(hit?.itemId || '').trim();
  }

  async function onRescrapeSelected() {
    if (rescraping || !selectedRow) return;
    if (st?.running) {
      setMsg('分区刮削进行中，请先暂停再重刮');
      onStatus('请先暂停刮削', 'warn');
      return;
    }
    setRescraping(true);
    setMsg('');
    const code = String(selectedRow.code || '').trim().toUpperCase();
    try {
      const itemId = await resolveItemIdForRow(selectedRow);
      if (!itemId) throw new Error('找不到该番号的向量条目');
      onStatus(`重刮 ${code || itemId}…`, 'mute');
      const data = await enrichScrapLibraryItem({
        itemId,
        overwrite: true,
        // 与分区批量一致：只写本地；元库/向量交给「同步数据库」「数据库向量化」
        syncVector: false,
      });
      const result = data.result || {};
      const softOk =
        Boolean(result.partialOk) ||
        String(result.error || '').startsWith('软成功') ||
        String(result.error || '').startsWith('次成功');
      const ok = Boolean(
        data.ok &&
          result.ok !== false &&
          (!result.error || softOk),
      );
      const resultFields = Array.isArray(result.fields)
        ? (result.fields as ScrapLibraryEnrichFieldRow[])
        : [];
      const nextRow: ScrapLibraryEnrichQueueItem = {
        ...selectedRow,
        itemId,
        status: ok ? 'done' : 'fail',
        partialOk: ok ? Boolean(result.partialOk) : false,
        error: String(result.error || (ok ? '' : '重刮失败')),
        source: String(result.source || selectedRow.source || ''),
        fetchMs:
          typeof result.fetchMs === 'number'
            ? result.fetchMs
            : selectedRow.fetchMs,
        coverMs:
          typeof result.coverMs === 'number'
            ? result.coverMs
            : selectedRow.coverMs,
        actressMs:
          typeof result.actressMs === 'number'
            ? result.actressMs
            : selectedRow.actressMs,
        vectorMs:
          typeof result.vectorMs === 'number'
            ? result.vectorMs
            : selectedRow.vectorMs,
        totalMs:
          typeof result.totalMs === 'number'
            ? result.totalMs
            : selectedRow.totalMs,
        detailTitle:
          String(data.item?.title || selectedRow.detailTitle || ''),
        nfoChanged:
          typeof result.nfoChanged === 'boolean'
            ? result.nfoChanged
            : selectedRow.nfoChanged,
        posterDownloaded:
          typeof result.posterDownloaded === 'boolean'
            ? result.posterDownloaded
            : selectedRow.posterDownloaded,
        sourceTimings: Array.isArray(result.sourceTimings)
          ? result.sourceTimings
          : selectedRow.sourceTimings,
        fields: resultFields.length ? resultFields : selectedRow.fields,
        gapsAfter: Array.isArray(result.gapsAfter)
          ? result.gapsAfter
          : selectedRow.gapsAfter,
        vectorSynced: Boolean(data.item) && !Boolean(result.vectorSkipped),
        vectorSkipped: Boolean(result.vectorSkipped),
      };
      const wasSt = rowStatus(selectedRow.status);
      const was: LiveTab =
        wasSt === 'done'
          ? isPartialOk(selectedRow)
            ? 'soft'
            : 'done'
          : wasSt;
      const now: LiveTab = ok
        ? isPartialOk(nextRow)
          ? 'soft'
          : 'done'
        : 'fail';
      setQueueCounts((prev) => {
        if (was === now) return prev;
        const next = { ...prev };
        if (was in next) next[was] = Math.max(0, Number(next[was] || 0) - 1);
        next[now] = Number(next[now] || 0) + 1;
        return next;
      });
      // 清掉相关 tab 缓存，避免旧失败/未处理残留
      delete tabCacheRef.current[was];
      delete tabCacheRef.current[now];
      if (ok) {
        // 立即从当前列表拿掉，切到成功/软成功队列
        if (tabRef.current !== now) {
          setQueueItems((prev) =>
            prev.filter((r) => rowKey(r) !== selectedKey),
          );
        } else {
          setQueueItems((prev) =>
            prev.map((r) => (rowKey(r) === selectedKey ? nextRow : r)),
          );
        }
        setTabTouched(true);
        setQueuePage(1);
        setTab(now);
        await loadQueueTab(now, 1);
        // 若库回填稍慢，确保成功列表里立刻能看到本条
        setQueueItems((prev) => {
          const key = selectedKey;
          const hit = prev.some(
            (r) =>
              rowKey(r) === key ||
              String(r.code || '').toUpperCase() === code,
          );
          if (hit) {
            return prev.map((r) =>
              rowKey(r) === key ||
              String(r.code || '').toUpperCase() === code
                ? { ...r, ...nextRow, status: 'done' }
                : r,
            );
          }
          return [{ ...nextRow, status: 'done' }, ...prev];
        });
        tabCacheRef.current.done = undefined;
      } else {
        setQueueItems((prev) =>
          prev.map((r) => (rowKey(r) === selectedKey ? nextRow : r)),
        );
        if (tabRef.current !== 'fail') {
          setTabTouched(true);
          setQueuePage(1);
          setTab('fail');
          await loadQueueTab('fail', 1);
        }
      }
      if (data.item || resultFields.length) {
        setDbDetail({
          code: data.item?.code || code,
          itemId,
          detailTitle: data.item?.title || nextRow.detailTitle || '',
          status: nextRow.status,
          fields: resultFields.length
            ? resultFields
            : fieldsFromSourceText(String(data.item?.sourceText || '')),
          vectorSynced: nextRow.vectorSynced,
          vectorSkipped: nextRow.vectorSkipped,
          posterDownloaded:
            typeof nextRow.posterDownloaded === 'boolean'
              ? nextRow.posterDownloaded
              : Boolean(data.item?.posterApi || data.item?.thumbApi),
          source: nextRow.source,
          fetchMs: nextRow.fetchMs,
          coverMs: nextRow.coverMs,
          actressMs: nextRow.actressMs,
          vectorMs: nextRow.vectorMs,
          totalMs: nextRow.totalMs,
          sourceTimings: nextRow.sourceTimings,
          nfoChanged: nextRow.nfoChanged,
        });
      }
      const text = ok
        ? `${code || itemId} · 重刮完成 · 已转入成功`
        : `${code || itemId} · 重刮失败${result.error ? ` · ${result.error}` : ''}`;
      setMsg(text);
      onStatus(ok ? '重刮完成 · 已转入成功' : '重刮失败', ok ? 'ok' : 'warn');
    } catch (e) {
      const text = e instanceof Error ? e.message : '重刮失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRescraping(false);
    }
  }

  const queue = queueItems;
  const current = (st?.current || null) as ScrapLibraryEnrichCurrent | null;
  const queueScanHere =
    Boolean(st?.queueScan?.active) &&
    (!st?.queueScan?.region || st.queueScan.region === regionId);
  const scanTip =
    (clearing || queueScanning || queueScanHere) &&
    (formatQueueScanLabel(st?.queueScan) ||
      (clearing && !queueScanning
        ? '清空日志…'
        : queueScanning || queueScanHere
          ? '扫描本地分类…'
          : ''));

  const inflightN = Math.max(
    Number(st?.monitor?.summary?.inflightN || 0),
    Array.isArray(st?.monitor?.inflight) ? st.monitor.inflight.length : 0,
  );
  const tabCounts: Record<LiveTab, number> = {
    pending: Number(queueCounts.pending || 0),
    // 处理中 = 真实占槽（inflight）；任务未跑则为 0
    running: st?.running ? inflightN : 0,
    done: Number(queueCounts.done || 0),
    soft: Number(queueCounts.soft || 0),
    fail: Number(queueCounts.fail || 0),
  };

  // 有进行中时默认切到「处理中」（用户点过 tab 后不再抢）；勿重置页码
  useEffect(() => {
    if (tabTouched) return;
    if (st?.running || tabCounts.running > 0) {
      if (tab !== 'running') setTab('running');
    } else if (tabCounts.pending > 0) {
      if (tab !== 'pending') setTab('pending');
    }
  }, [st?.running, tabCounts.running, tabCounts.pending, tabTouched, tab]);

  const searchActive = Boolean(searchCode);
  const filteredQueue = searchActive
    ? searchItems.map(normalizeSoftSuccessRow)
    : queue
        .map(normalizeSoftSuccessRow)
        .filter((r) => {
          if (tab === 'fail') return rowStatus(r.status) === 'fail';
          if (tab === 'soft')
            return rowStatus(r.status) === 'done' && isPartialOk(r);
          if (tab === 'done')
            return rowStatus(r.status) === 'done' && !isPartialOk(r);
          return rowStatus(r.status) === tab;
        });
  const queueTotalForTab = Number(
    listTotals[tab] ?? tabCounts[tab] ?? 0,
  );
  const queuePageTotal = Math.max(
    1,
    Math.ceil(queueTotalForTab / QUEUE_PAGE_SIZE),
  );
  const pageShown = Math.min(queuePage, queuePageTotal);
  const showQueuePager =
    !searchActive &&
    tab !== 'running' &&
    filteredQueue.length > 0 &&
    queuePageTotal > 1;
  const monitor = st?.monitor || null;
  const monitorInflight = Array.isArray(monitor?.inflight) ? monitor.inflight : [];
  const liveRunningPool = (() => {
    const fromStatus = (st?.queue || []).filter(
      (r) => rowStatus(r.status) === 'running',
    );
    if (fromStatus.length) return fromStatus;
    return queueItems.filter((r) => rowStatus(r.status) === 'running');
  })();
  const runningViewRows: EnrichMonitorInflight[] = monitorInflight.length
    ? monitorInflight
    : liveRunningPool.map((r) => ({
        code: r.code,
        itemId: r.itemId,
        phase: 'fetch',
        phaseLabel: '处理中',
        elapsedMs:
          typeof r.totalMs === 'number'
            ? r.totalMs
            : typeof r.fetchMs === 'number'
              ? r.fetchMs
              : 0,
        sources: r.sourceTimings,
        stall: r.stallLabel ? { label: r.stallLabel } : null,
      }));
  const hasRunningRows = runningViewRows.length > 0;

  const selectedRow =
    selectedKey == null
      ? null
      : searchItems.find((r) => rowKey(r) === selectedKey) ||
        queue.find((r) => rowKey(r) === selectedKey) ||
        liveRunningPool.find((r) => rowKey(r) === selectedKey) ||
        (st?.queue || []).find((r) => rowKey(r) === selectedKey) ||
        null;
  const selectedDetail = (() => {
    if (!selectedRow) return null;
    const base = detailFromRow(selectedRow, current);
    if (!dbDetail) return base;
    // 成功/失败入库回填：补标题与字段（不覆盖本轮源耗时）
    return {
      ...base,
      detailTitle: base.detailTitle || dbDetail.detailTitle,
      fields:
        base.fields && base.fields.length > 0 ? base.fields : dbDetail.fields,
      vectorSynced:
        base.vectorSkipped || dbDetail.vectorSkipped
          ? false
          : typeof base.vectorSynced === 'boolean'
            ? base.vectorSynced
            : dbDetail.vectorSynced,
      vectorSkipped:
        typeof base.vectorSkipped === 'boolean'
          ? base.vectorSkipped
          : dbDetail.vectorSkipped,
      posterDownloaded:
        typeof base.posterDownloaded === 'boolean'
          ? base.posterDownloaded
          : dbDetail.posterDownloaded,
    };
  })();

  // 切 tab 时关掉详情；当前条若已不在队列则清空
  useEffect(() => {
    setSelectedKey(null);
    setDbDetail(null);
  }, [tab]);
  useEffect(() => {
    // selectedKey empty: do not setState — SSE st.queue identity churn
    // caused Maximum update depth even with functional bailout.
    // Clear dbDetail wherever selectedKey is cleared.
    if (!selectedKey) return;
    const runningFromStatus = (st?.queue || []).filter(
      (r) => rowStatus(r.status) === 'running',
    );
    const inPool =
      searchItems.some((r) => rowKey(r) === selectedKey) ||
      queueItems.some((r) => rowKey(r) === selectedKey) ||
      runningFromStatus.some((r) => rowKey(r) === selectedKey);
    if (!inPool) {
      setSelectedKey(null);
      setDbDetail(null);
    }
  }, [queueItems, searchItems, selectedKey, st?.queue]);

  // 成功/失败点进详情：优先用队列表已落库字段；空壳再从向量库补
  useEffect(() => {
    if (!selectedRow) return;
    const stt = rowStatus(selectedRow.status);
    if (stt !== 'done' && stt !== 'fail') return;
    const code = String(selectedRow.code || '').trim();
    const iid = String(selectedRow.itemId || '').trim();
    if (!code && !iid) return;

    // 已有带选用源的字段 / 源耗时：不必再打向量库
    const hasRichFields = (selectedRow.fields || []).some(
      (f) => String(f.source || '').trim().length > 0,
    );
    if (
      hasRichFields ||
      (selectedRow.sourceTimings || []).length > 0 ||
      ((selectedRow.fields || []).length > 0 &&
        displayHitSource(selectedRow.source))
    ) {
      return;
    }

    let alive = true;
    void (async () => {
      try {
        // 再拉一次队列表该条（服务端会对空壳做 NFO 回填）
        const page = await getScrapLibraryEnrichQueueLog({
          region: regionId,
          status: stt,
          limit: 80,
        });
        if (!alive) return;
        const hitQ =
          (page.items || []).find(
            (it) =>
              (iid && it.itemId === iid) ||
              (code &&
                String(it.code || '').toUpperCase() === code.toUpperCase()),
          ) || null;
        if (hitQ && (hitQ.fields || []).length > 0) {
          setQueueItems((prev) =>
            prev.map((r) =>
              rowKey(r) === rowKey(selectedRow)
                ? {
                    ...r,
                    ...hitQ,
                    fields: hitQ.fields,
                    sourceTimings: hitQ.sourceTimings || r.sourceTimings,
                    detailTitle: hitQ.detailTitle || r.detailTitle,
                    source: displayHitSource(hitQ.source) || r.source,
                    posterDownloaded:
                      typeof hitQ.posterDownloaded === 'boolean'
                        ? hitQ.posterDownloaded
                        : r.posterDownloaded,
                  }
                : r,
            ),
          );
          // NFO 回填的字段已够展示；站点源/源耗时需当次刮削落库
          return;
        }

        if ((selectedRow.fields || []).length > 0) return;

        const pageEmbed = await listScrapLibraryEmbedItems({
          q: code || iid,
          limit: 8,
        });
        if (!alive) return;
        const hit =
          (pageEmbed.items || []).find(
            (it) =>
              (iid && it.itemId === iid) ||
              (code &&
                String(it.code || '').toUpperCase() === code.toUpperCase()),
          ) || (pageEmbed.items || [])[0];
        if (!hit) return;
        const src = String(hit.sourceText || '');
        setDbDetail({
          code: hit.code || code,
          itemId: hit.itemId || iid,
          detailTitle: hit.title || selectedRow.detailTitle || '',
          status: selectedRow.status,
          fields: ensurePosterField(fieldsFromSourceText(src), {
            posterDownloaded: Boolean(hit.posterApi || hit.thumbApi),
          }),
          // 仅补字段展示；不要把「库里有向量行」当成「本步已同步」
          vectorSynced: selectedRow.vectorSkipped
            ? false
            : selectedRow.vectorSynced,
          vectorSkipped: selectedRow.vectorSkipped,
          posterDownloaded: Boolean(hit.posterApi || hit.thumbApi),
          source: displayHitSource(selectedRow.source) || undefined,
          sourceTimings: selectedRow.sourceTimings,
        });
      } catch {
        /* ignore */
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedRow, regionId]);
  return (
    <AppPush
      title={
        selectedDetail?.code
          ? `${selectedDetail.code} · 详情`
          : `${label} · 刮削`
      }
      onBack={
        selectedKey
          ? () => {
              setSelectedKey(null);
              setDbDetail(null);
            }
          : onBack
      }
      scrollKey={
        selectedDetail?.code
          ? `enrich-live-detail-${selectedDetail.code}`
          : `enrich-live-${regionId}`
      }
      scrollMode="top"
      scrollPin="once"
      right={
        selectedKey ? (
          <span className="makers-manage__status-actions">
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={rescraping || Boolean(st?.running)}
              onClick={() => void onRescrapeSelected()}
            >
              {rescraping ? '重刮中…' : '重刮'}
            </button>
          </span>
        ) : (
        <span className="makers-manage__status-actions">
          {st?.running ? (
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={stopping}
              onClick={() => void onPause()}
            >
              {stopping ? '处理中' : '暂停'}
            </button>
          ) : null}
          <button
            type="button"
            className="makers-manage__probe-btn makers-manage__probe-btn--danger"
            disabled={clearing || queueScanning || retryingFails || retryingSofts}
            onClick={() => void onClearAndScan()}
          >
            {clearing && !queueScanning
              ? '清空中…'
              : queueScanning || queueScanHere
                ? '扫描中…'
                : '清空·扫描'}
          </button>
        </span>
        )
      }
    >
      <div
        className={cn(
          'makers-manage makers-manage--detail enrich-live',
          hydrated && 'enrich-live--ready',
        )}
      >
        {selectedDetail ? (
          <EnrichItemDetail detail={selectedDetail} regionId={regionId} />
        ) : (
          <>
        <div className="enrich-live__chrome">
          <form
            className="app-search-row enrich-live__search"
            onSubmit={(e) => {
              e.preventDefault();
              void runCodeSearch();
            }}
          >
            <label className="app-search enrich-live__search-field">
              <Search
                className="app-search-icon enrich-live__search-icon"
                size={16}
                strokeWidth={2.2}
                aria-hidden
              />
              <input
                type="search"
                enterKeyHint="search"
                autoCapitalize="characters"
                autoCorrect="off"
                spellCheck={false}
                placeholder="全局搜索番号"
                value={codeQuery}
                disabled={clearing}
                onChange={(e) => setCodeQuery(e.target.value)}
                aria-label="全局搜索番号"
              />
              {searchActive || codeQuery ? (
                <button
                  type="button"
                  className="enrich-live__search-clear"
                  aria-label="清除搜索"
                  onClick={() => clearCodeSearch()}
                >
                  <X size={15} strokeWidth={2.4} aria-hidden />
                </button>
              ) : null}
            </label>
            <button
              type="submit"
              className="app-search-btn enrich-live__search-btn"
              disabled={searching || !codeQuery.trim()}
            >
              {searching ? '…' : '搜索'}
            </button>
          </form>

          <div
            className="app-seg enrich-live__tabs enrich-live__tabs--status"
            role="tablist"
            aria-label="刮削队列"
          >
            {TAB_META.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={searchActive ? false : tab === t.id}
                className={cn(
                  'app-seg__btn',
                  !searchActive && tab === t.id && 'app-seg__btn--active',
                  searchActive && 'enrich-live__tab--dim',
                )}
                onClick={() => {
                  if (searchActive) clearCodeSearch();
                  setTabTouched(true);
                  const next = t.id;
                  setQueuePage(1);
                  // 成功类按库表时间排序：扫描/刮削中都勿用扫序样例或旧缓存
                  // （样例多为先扫到的 AARM，会盖住 updated_at 真列表）
                  const qs = st?.queueScan;
                  const qsHere =
                    Boolean(qs?.active) &&
                    (!qs?.region || qs.region === regionId);
                  const live =
                    Boolean(st?.running) &&
                    (!st?.currentRegion || st.currentRegion === regionId);
                  if (
                    (qsHere || live) &&
                    (next === 'done' || next === 'soft' || next === 'fail')
                  ) {
                    delete tabCacheRef.current[next];
                    // 立刻禁止 SSE 扫序样例；等库表回填（勿先置 false，否则加载几秒内仍会被 AARM 盖）
                    tabDbLoadedRef.current[next] = true;
                    setQueueItems([]);
                    setTab(next);
                    return;
                  }
                  const cached = tabCacheRef.current[next];
                  if (cached) {
                    startTransition(() => setQueueItems(cached));
                  }
                  setTab(next);
                }}
              >
                <span className="enrich-live__tab-label">{t.label}</span>
                <span className="enrich-live__tab-count">
                  {Number(tabCounts[t.id] || 0).toLocaleString()}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="enrich-live__pane" ref={queuePaneRef}>
          {searchActive ? (
            <p className="enrich-live__queue-hint">
              {searching
                ? `全局搜索 ${searchCode}…`
                : `全局搜索 ${searchCode} · ${filteredQueue.length} 条（跨全部状态）`}
            </p>
          ) : scanTip ? (
            <p className="enrich-live__queue-hint">
              {scanTip}
              {filteredQueue.length > 0
                ? ` · 预览 ${filteredQueue.length} 条（扫完会补全）`
                : ''}
            </p>
          ) : null}
          {!searchActive && tab === 'fail' && Number(tabCounts.fail || 0) > 0 ? (
            <div className="enrich-live__fail-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={
                  retryingFails ||
                  retryingSofts ||
                  clearing ||
                  queueScanning
                }
                onClick={() => void onRetryFails()}
              >
                {retryingFails ? '重试中…' : '失败重试'}
              </button>
              <span className="enrich-live__fail-actions-hint">
                {`将 ${Number(tabCounts.fail || 0).toLocaleString()} 条失败转入未处理优先刮削`}
              </span>
            </div>
          ) : null}
          {!searchActive && tab === 'soft' && Number(tabCounts.soft || 0) > 0 ? (
            <div className="enrich-live__fail-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={
                  retryingSofts ||
                  retryingFails ||
                  clearing ||
                  queueScanning
                }
                onClick={() => void onRetrySofts()}
              >
                {retryingSofts ? '重试中…' : '软成功重试'}
              </button>
              <span className="enrich-live__fail-actions-hint">
                {`将 ${Number(tabCounts.soft || 0).toLocaleString()} 条软成功转入未处理优先刮削`}
              </span>
            </div>
          ) : null}
          {!searchActive && tab === 'running' ? (
            <div className="enrich-live__monitor">
              {(st?.running || monitorInflight.length > 0) && (
                <p className="enrich-live__queue-hint">
                  番号并发 {Number(monitor?.itemWorkers || 5)} · 进行中{' '}
                  {Number(
                    monitor?.summary?.inflightN ||
                      monitorInflight.length ||
                      liveRunningPool.length ||
                      0,
                  )}
                  {Number(monitor?.summary?.stallingN || 0) > 0
                    ? ` · 卡顿 ${Number(monitor?.summary?.stallingN || 0)}`
                    : ''}
                  {Number(monitor?.summary?.avgFetchMs || 0) > 0
                    ? ` · 均耗时 ${formatMs(monitor?.summary?.avgFetchMs)}`
                    : ''}
                  {' · '}
                  {topStallKinds(monitor)}
                </p>
              )}
              {!hasRunningRows ? (
                <EnrichTabIdle
                  waiting={Boolean(st?.running)}
                  title={st?.running ? '等待番号占槽…' : '暂无进行中任务'}
                  desc={
                    st?.running
                      ? '占槽后会显示各路阶段、耗时与卡顿原因；改策略后下一番号即用新数据源'
                      : hasCheckpoint
                        ? '已暂停 · 新策略保存后立即生效，继续刮削用最新配置'
                        : '开始刮削后，最多 5 路番号进度会出现在这里'
                  }
                  icon={
                    st?.running ? (
                      <LoaderCircle size={22} strokeWidth={2.2} />
                    ) : (
                      <Activity size={22} strokeWidth={2.2} />
                    )
                  }
                />
              ) : (
                <ul className="settings-group enrich-live__queue">
                  {runningViewRows.map((row) => {
                    const stall = row.stall?.label || '';
                    const stallKind = String(row.stall?.kind || '').trim();
                    const softStall = Boolean(
                      stall &&
                        (!stallKind ||
                          [
                            'slot_blocked',
                            'cover_slow',
                            'source_slow',
                            'fetch_tail',
                            'all_sources_pending',
                            'actress_slow',
                            'write_slow',
                          ].includes(stallKind)),
                    );
                    const hardStall = Boolean(stall && !softStall);
                    const matched = findQueueForMonitor(row, [
                      ...liveRunningPool,
                      ...queueItems,
                    ]);
                    const desc = monitorRowDesc(row);
                    const openDetail = () => {
                      if (!matched) return;
                      setDbDetail(null);
                      setSelectedKey(rowKey(matched));
                    };
                    const rowTone = hardStall
                      ? 'fail'
                      : softStall
                        ? 'warn'
                        : 'on';
                    const badgeTone = hardStall
                      ? 'fail'
                      : softStall
                        ? 'warn'
                        : 'running';
                    const badgeText = hardStall
                      ? '卡顿'
                      : softStall
                        ? '偏慢'
                        : row.phaseLabel || '处理中';
                    return (
                      <li key={`${row.code || ''}-${row.itemId || ''}`}>
                        {matched ? (
                          <button
                            type="button"
                            className={cn(
                              'settings-nav enrich-live__queue-row',
                              `enrich-live__queue-row--${rowTone}`,
                            )}
                            onClick={openDetail}
                          >
                            <span
                              className={cn(
                                'enrich-live__queue-badge',
                                `enrich-live__queue-badge--${badgeTone}`,
                              )}
                            >
                              {badgeText}
                            </span>
                            <span className="settings-nav__main enrich-live__queue-main">
                              <span className="settings-nav__title">
                                {row.code || matched.code || '—'}
                              </span>
                              <span className="settings-nav__desc">{desc}</span>
                            </span>
                            <span className="enrich-live__queue-meta">
                              {formatMs(row.elapsedMs)}
                            </span>
                            <ChevronRight
                              className="settings-nav__chev"
                              size={17}
                              strokeWidth={2.4}
                              aria-hidden
                            />
                          </button>
                        ) : (
                          <div
                            className={cn(
                              'settings-nav enrich-live__queue-row enrich-live__queue-row--static',
                              `enrich-live__queue-row--${rowTone}`,
                            )}
                          >
                            <span
                              className={cn(
                                'enrich-live__queue-badge',
                                `enrich-live__queue-badge--${badgeTone}`,
                              )}
                            >
                              {badgeText}
                            </span>
                            <span className="settings-nav__main enrich-live__queue-main">
                              <span className="settings-nav__title">
                                {row.code || '—'}
                              </span>
                              <span className="settings-nav__desc">{desc}</span>
                            </span>
                            <span className="enrich-live__queue-meta">
                              {formatMs(row.elapsedMs)}
                            </span>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ) : filteredQueue.length === 0 ? (
            queuePaging ? (
              <EnrichTabIdle
                waiting
                title="加载队列…"
                desc={`正在加载第 ${pageShown} 页`}
                icon={<LoaderCircle size={22} strokeWidth={2.2} />}
              />
            ) : searchActive ? (
              <EnrichTabIdle
                waiting={searching}
                title={searching ? '全局搜索中…' : '未找到番号'}
                desc={
                  searching
                    ? `正在跨全部状态查 ${searchCode}`
                    : `未处理 / 成功 / 软成功 / 失败中都没有匹配 ${searchCode} 的记录`
                }
                icon={
                  searching ? (
                    <LoaderCircle size={22} strokeWidth={2.2} />
                  ) : (
                    <Search size={22} strokeWidth={2.2} />
                  )
                }
              />
            ) : tab === 'pending' ? (
              <EnrichTabIdle
                waiting={
                  Boolean(scanTip) ||
                  queueScanning ||
                  !hydrated ||
                  Boolean(st?.running)
                }
                title={
                  scanTip
                    ? '扫描未处理任务…'
                    : queueScanning || !hydrated
                      ? '扫描未处理任务…'
                      : st?.running
                        ? '边扫边刮进行中…'
                        : '暂无未处理项'
                }
                desc={
                  scanTip ||
                  (queueScanning || !hydrated
                    ? '正在对照库内空壳与本地缺口'
                    : st?.running
                      ? '扫描入队与刮削并行，新任务会出现在这里'
                      : '打开分区开关即可边扫边刮，或点「清空·扫描」按向量骨架−本地已分类重建队列')
                }
                icon={
                  scanTip ||
                  queueScanning ||
                  !hydrated ||
                  st?.running ? (
                    <LoaderCircle size={22} strokeWidth={2.2} />
                  ) : (
                    <Inbox size={22} strokeWidth={2.2} />
                  )
                }
              />
            ) : tab === 'done' ? (
              <EnrichTabIdle
                waiting={Boolean(scanTip)}
                tone={scanTip ? 'neutral' : 'ok'}
                title={scanTip ? '扫描本地成功项…' : '暂无成功项'}
                desc={
                  scanTip ||
                  '本地封面与标题等字段齐全的番号会出现在这里；点「清空·扫描」按磁盘重建'
                }
                icon={
                  scanTip ? (
                    <LoaderCircle size={22} strokeWidth={2.2} />
                  ) : (
                    <CheckCircle2 size={22} strokeWidth={2.2} />
                  )
                }
              />
            ) : tab === 'soft' ? (
              <EnrichTabIdle
                waiting={Boolean(scanTip)}
                tone={scanTip ? 'neutral' : 'ok'}
                title={scanTip ? '扫描本地软成功…' : '暂无软成功项'}
                desc={
                  scanTip ||
                  '本地封面和标题已齐，但仍缺女优或片商；点「清空·扫描」按磁盘重建'
                }
                icon={
                  scanTip ? (
                    <LoaderCircle size={22} strokeWidth={2.2} />
                  ) : (
                    <CheckCircle2 size={22} strokeWidth={2.2} />
                  )
                }
              />
            ) : (
              <EnrichTabIdle
                waiting={Boolean(scanTip)}
                tone={scanTip ? 'neutral' : 'fail'}
                title={scanTip ? '扫描本地失败项…' : '暂无失败项'}
                desc={
                  scanTip ||
                  '本地缺封面或标题；点「清空·扫描」按磁盘重建'
                }
                icon={
                  scanTip ? (
                    <LoaderCircle size={22} strokeWidth={2.2} />
                  ) : (
                    <CircleAlert size={22} strokeWidth={2.2} />
                  )
                }
              />
            )
          ) : (
            <div className="enrich-live__body">
              <ul
                className="settings-group enrich-live__queue"
              >
                {filteredQueue.map((row) => (
                  <li key={rowKey(row)}>
                    <button
                      type="button"
                      className={cn(
                        'settings-nav enrich-live__queue-row',
                        row.status === 'running' &&
                          'enrich-live__queue-row--on',
                        row.status === 'done' &&
                          !isPartialOk(row) &&
                          'enrich-live__queue-row--ok',
                        row.status === 'done' &&
                          isPartialOk(row) &&
                          'enrich-live__queue-row--warn',
                        row.status === 'fail' &&
                          'enrich-live__queue-row--fail',
                      )}
                      onClick={() => {
                        setDbDetail(null);
                        setSelectedKey(rowKey(row));
                      }}
                    >
                      <span
                        className={cn(
                          'enrich-live__queue-badge',
                          `enrich-live__queue-badge--${statusTone(row.status, row)}`,
                        )}
                      >
                        {statusLabel(row.status, row)}
                      </span>
                      <span className="settings-nav__main enrich-live__queue-main">
                        <span className="settings-nav__title">
                          {row.code || '—'}
                        </span>
                        <span className="settings-nav__desc">
                          {queueRowDesc(row) || '—'}
                        </span>
                      </span>
                      <span className="enrich-live__queue-meta">
                        {typeof row.totalMs === 'number'
                          ? `${row.totalMs}ms`
                          : typeof row.fetchMs === 'number'
                            ? `${row.fetchMs}ms`
                            : ''}
                      </span>
                      <ChevronRight
                        className="settings-nav__chev"
                        size={17}
                        strokeWidth={2.4}
                        aria-hidden
                      />
                    </button>
                  </li>
                ))}
              </ul>
              {showQueuePager ? (
                <div className="enrich-live__pager" role="navigation" aria-label="队列翻页">
                  <button
                    type="button"
                    className="enrich-live__pager-btn"
                    disabled={pageShown <= 1 || queuePaging || queueScanning}
                    onClick={() => goQueuePage(pageShown - 1)}
                  >
                    上一页
                  </button>
                  <span className="enrich-live__pager-meta">
                    <span className="enrich-live__pager-page">
                      {pageShown}
                      <span className="enrich-live__pager-slash">/</span>
                      {queuePageTotal}
                    </span>
                    <span className="enrich-live__pager-total">
                      {(
                        (pageShown - 1) * QUEUE_PAGE_SIZE + 1
                      ).toLocaleString()}
                      –
                      {Math.min(
                        pageShown * QUEUE_PAGE_SIZE,
                        queueTotalForTab,
                      ).toLocaleString()}
                      <span className="enrich-live__pager-of">/</span>
                      {queueTotalForTab.toLocaleString()}
                      {queuePaging ? (
                        <span className="enrich-live__pager-loading">加载中</span>
                      ) : null}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="enrich-live__pager-btn"
                    disabled={
                      pageShown >= queuePageTotal || queuePaging || queueScanning
                    }
                    onClick={() => goQueuePage(pageShown + 1)}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </div>
          )}
        </div>
          </>
        )}

        {msg && !queueScanning && !queueScanHere && !clearing ? (
          <AppMsg tone="info">{msg}</AppMsg>
        ) : null}
      </div>
    </AppPush>
  );
}
