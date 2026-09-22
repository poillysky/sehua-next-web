/**
 * 刮削补全：质量、队列、状态、日志
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import type { PrefixCatalogLocalIndexProgress } from './prefix';
import type { ScrapLibraryEmbedItem } from './scrap-library';
import type {
  ScrapLibraryEnrichFieldRow,
  ScrapLibraryEnrichSourceTiming,
  ScrapLibraryQualityItem,
  ScrapLibraryQualityStats,
} from './scrap-jobs';
import type {
  AuthUser,
  BrowseResult,
  FilterSize,
  FilterTime,
  MatchMode,
  ResourceDbConfig,
  ResourceItem,
  SearchResult,
  SortType,
} from '@/types/resource';

export type ScrapLibraryEnrichQueueItem = {
  logId?: number;
  index?: number;
  itemId?: string;
  code?: string;
  gaps?: string[];
  gapsAfter?: string[];
  status?: 'pending' | 'running' | 'done' | 'fail' | string;
  error?: string;
  source?: string;
  fetchMs?: number;
  coverMs?: number;
  actressMs?: number;
  vectorMs?: number;
  totalMs?: number;
  detailTitle?: string;
  actors?: number;
  nfoChanged?: boolean;
  posterDownloaded?: boolean;
  vectorSynced?: boolean;
  vectorSkipped?: boolean;
  vectorError?: string;
  /** 软成功：封面+标题已齐，仍缺剧情/女优等 */
  partialOk?: boolean;
  relPath?: string;
  rel_path?: string;
  sourceTimings?: ScrapLibraryEnrichSourceTiming[];
  fields?: ScrapLibraryEnrichFieldRow[];
  wouldFill?: Record<string, boolean | number>;
  /** 处理中卡顿原因（来自 monitor） */
  stallLabel?: string;
};

export type EnrichMonitorStall = {
  kind?: string;
  label?: string;
  detail?: string;
  sinceMs?: number;
};

export type EnrichMonitorInflight = {
  code?: string;
  itemId?: string;
  region?: string;
  phase?: string;
  phaseLabel?: string;
  elapsedMs?: number;
  phaseElapsedMs?: number;
  sources?: Array<{
    id?: string;
    status?: string;
    ms?: number;
    ok?: boolean;
    error?: string;
  }>;
  stall?: EnrichMonitorStall | null;
};

export type EnrichMonitorRecentStall = {
  code?: string;
  itemId?: string;
  ok?: boolean;
  elapsedMs?: number;
  phase?: string;
  stall?: EnrichMonitorStall | null;
  error?: string;
};

export type EnrichMonitorSnapshot = {
  enabled?: boolean;
  itemWorkers?: number;
  perSourceTimeoutSec?: number;
  region?: string;
  inflight?: EnrichMonitorInflight[];
  recentStalls?: EnrichMonitorRecentStall[];
  summary?: {
    inflightN?: number;
    stallingN?: number;
    stallKinds?: Record<string, number>;
    avgFetchMs?: number;
  };
};

export type ScrapLibraryEnrichCurrent = {
  code?: string;
  itemId?: string;
  gaps?: string[];
  status?: string;
  index?: number;
  total?: number;
  ok?: boolean;
  error?: string;
  source?: string;
  detailTitle?: string;
  fetchMs?: number;
  coverMs?: number;
  actressMs?: number;
  vectorMs?: number;
  totalMs?: number;
  actors?: number;
  nfoChanged?: boolean;
  posterDownloaded?: boolean;
  vectorSynced?: boolean;
  vectorSkipped?: boolean;
  vectorError?: string;
  relPath?: string;
  sourceTimings?: ScrapLibraryEnrichSourceTiming[];
  fields?: ScrapLibraryEnrichFieldRow[];
  wouldFill?: Record<string, boolean | number>;
};

export type ScrapLibraryEnrichCheckpoint = {
  region?: string;
  mode?: string;
  dryRun?: boolean;
  done?: number;
  remaining?: number;
  total?: number;
  ok?: number;
  failed?: number;
};

export type ScrapLibraryEnrichJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  regionLogs?: Record<string, string[]>;
  /** 各分区本轮/内存日志条数（可大于 regionLogs 回传长度） */
  regionLogCounts?: Record<string, number>;
  currentRegion?: string;
  cancel?: boolean;
  halt?: 'pause' | 'stop' | string | null;
  paused?: boolean;
  checkpoints?: Record<string, ScrapLibraryEnrichCheckpoint>;
  /** 库内总量/未完成（进度条用，避免队列表样例把进度撑高） */
  library?: Record<
    string,
    {
      total?: number;
      incomplete?: number;
      complete?: number;
      percent?: number;
    }
  >;
  queue?: ScrapLibraryEnrichQueueItem[];
  queueTotal?: number;
  queueCounts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  /** 全局 queueCounts 对应的分区（防串区） */
  queueCountsRegion?: string;
  /**
   * 上一次读库计数是否成功。false = 读库失败（断连/超时），此时 counts 全是 0，
   * 前端应保留旧角标而不是把数字塌成 0。取代旧的 `server === 500` 魔数哨兵。
   */
  queueCountsOk?: boolean;
  /**
   * 只统计「真实刮削产出」的行（排除 `source='local_scan'` 的扫描判定行）。
   * 队列日志表把十万级的「扫描判定已齐」与百级的「真抓成功」混在一张表，
   * 角标不拆开就会被误读成刮削产出。
   */
  queueCountsScrape?: {
    done?: number;
    soft?: number;
    fail?: number;
    total?: number;
  };
  queueCountsScrapeRegion?: string;
  /** 各分区独立角标 */
  regionQueueCounts?: Record<
    string,
    {
      pending?: number;
      running?: number;
      done?: number;
      soft?: number;
      fail?: number;
    }
  >;
  current?: ScrapLibraryEnrichCurrent | null;
  /** 清空·扫描进行中的磁盘分类进度（SSE 边扫边看） */
  queueScan?: {
    active?: boolean;
    region?: string;
    stage?: string;
    label?: string;
    scanned?: number;
    total?: number;
    done?: number;
    soft?: number;
    fail?: number;
    pending?: number;
    /** 边扫边看：成功样例 */
    samplesDone?: ScrapLibraryEnrichQueueItem[];
    /** 边扫边看：软成功样例 */
    samplesSoft?: ScrapLibraryEnrichQueueItem[];
    /** 边扫边看：失败样例 */
    samplesFail?: ScrapLibraryEnrichQueueItem[];
  } | null;
  result?: {
    dryRun?: boolean;
    region?: string;
    regions?: string[];
    kinds?: string[];
    /** ⚠️ 增量模式下是**库内待处理预估**（十万级），不要当本轮总量用来显示 */
    queued?: number;
    /** 本轮实际处理条数（= ok + failed）；显示「成功 x/y」请用它 */
    processed?: number;
    ok?: number;
    failed?: number;
    cancelled?: boolean;
    paused?: boolean;
    sources?: string[];
    items?: Array<{
      code?: string;
      ok?: boolean;
      error?: string;
      dryRun?: boolean;
      detailTitle?: string;
    }>;
  } | null;
  error?: string | null;
  monitor?: EnrichMonitorSnapshot;
};

export async function getScrapLibraryQuality(
  region = 'japan_censored',
): Promise<ScrapLibraryQualityStats> {
  const q = new URLSearchParams();
  if (region) q.set('region', region);
  const res = await apiFetch(
    `/scrap-library/embed/quality${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryQualityStats>).data;
}

export async function getScrapLibraryQualityItems(opts?: {
  region?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}): Promise<{ items: ScrapLibraryQualityItem[]; kind?: string; region?: string }> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.kind) q.set('kind', opts.kind);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  const res = await apiFetch(
    `/scrap-library/embed/quality/items${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      items: ScrapLibraryQualityItem[];
      kind?: string;
      region?: string;
    }>
  ).data;
}

export type ScrapLibraryQualityGate = {
  ok: boolean;
  code?: string;
  hardFail?: string[];
  soft?: string[];
  info?: {
    code?: string;
    badges?: string[];
    actorsN?: number;
    poster?: {
      width?: number;
      height?: number;
      issues?: string[];
    };
    hasTitleJa?: boolean;
    [k: string]: unknown;
  };
};

export async function getScrapLibraryQualityGate(opts?: {
  itemId?: string;
  code?: string;
  relPath?: string;
}): Promise<ScrapLibraryQualityGate> {
  const q = new URLSearchParams();
  if (opts?.itemId) q.set('itemId', opts.itemId);
  if (opts?.code) q.set('code', opts.code);
  if (opts?.relPath) q.set('relPath', opts.relPath);
  const res = await apiFetch(
    `/scrap-library/embed/quality/gate${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryQualityGate>).data;
}

export async function startScrapLibraryEnrich(body?: {
  region?: string;
  regions?: string[];
  kinds?: string[];
  limit?: number;
  dryRun?: boolean;
  mode?: 'incremental' | 'refresh_weak' | 'overwrite';
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/enrich', {
    method: 'POST',
    body: JSON.stringify({
      region: body?.region ?? '',
      regions: body?.regions ?? [],
      // 空数组走服务端默认：完整元数据 + 封面
      kinds: body?.kinds ?? [
        'no_local',
        'no_media',
        'no_actress',
        'no_studio',
        'no_plot',
        'thin_title',
      ],
      limit: body?.limit ?? 0,
      dryRun: Boolean(body?.dryRun),
      mode:
        body?.mode === 'overwrite'
          ? 'overwrite'
          : body?.mode === 'refresh_weak'
            ? 'refresh_weak'
            : 'incremental',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

/** 详情页：清空该条向量后全量重刮并覆盖 NFO/向量。
 *  syncVector=false：只写本地 NFO/封面（设置页分区刮削重刮），不清空向量。
 */
export async function enrichScrapLibraryItem(opts: {
  itemId: string;
  dryRun?: boolean;
  overwrite?: boolean;
  syncVector?: boolean;
}): Promise<{
  ok: boolean;
  dryRun?: boolean;
  overwrite?: boolean;
  gaps?: string[];
  result?: {
    ok?: boolean;
    error?: string;
    code?: string;
    nfoChanged?: boolean;
    posterDownloaded?: boolean;
    source?: string;
    actors?: number;
    fetchMs?: number;
    coverMs?: number;
    actressMs?: number;
    vectorMs?: number;
    totalMs?: number;
    vectorSkipped?: boolean;
    partialOk?: boolean;
    gapsAfter?: string[];
    fields?: ScrapLibraryEnrichFieldRow[];
    sourceTimings?: Array<{
      id?: string;
      access?: string;
      ms?: number;
      ok?: boolean;
      error?: string;
      actors?: number;
      poster?: boolean;
    }>;
  };
  item?: ScrapLibraryEmbedItem | null;
}> {
  const itemId = String(opts.itemId || '').trim();
  if (!itemId) throw new Error('缺少条目 ID');
  const res = await apiFetch('/scrap-library/embed/enrich/one', {
    method: 'POST',
    body: JSON.stringify({
      itemId,
      dryRun: Boolean(opts.dryRun),
      overwrite: opts.overwrite !== false,
      syncVector: opts.syncVector !== false,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok: boolean;
      dryRun?: boolean;
      gaps?: string[];
      result?: {
        ok?: boolean;
        error?: string;
        code?: string;
        nfoChanged?: boolean;
        posterDownloaded?: boolean;
        source?: string;
        actors?: number;
        fetchMs?: number;
        coverMs?: number;
        actressMs?: number;
        vectorMs?: number;
        totalMs?: number;
        vectorSkipped?: boolean;
        partialOk?: boolean;
        gapsAfter?: string[];
        fields?: ScrapLibraryEnrichFieldRow[];
        sourceTimings?: Array<{
          id?: string;
          access?: string;
          ms?: number;
          ok?: boolean;
          error?: string;
          actors?: number;
          poster?: boolean;
        }>;
      };
      item?: ScrapLibraryEmbedItem | null;
    }>
  ).data;
}

export async function getScrapLibraryEnrichStatus(opts?: {
  lite?: boolean;
}): Promise<ScrapLibraryEnrichJobStatus> {
  const q = new URLSearchParams();
  if (opts?.lite) q.set('lite', '1');
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(`/scrap-library/embed/enrich/status${suffix}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEnrichJobStatus>).data;
}

/** SSE：服务端状态变更时推送，替代 450ms 轮询。 */
export async function subscribeScrapLibraryEnrichStatus(
  onStatus: (data: ScrapLibraryEnrichJobStatus) => void,
  opts?: {
    signal?: AbortSignal;
    onError?: (message: string) => void;
    /** 总览角标：不含 queue，帧更小、更不易卡设置页 */
    lite?: boolean;
  },
): Promise<void> {
  const signal = opts?.signal;
  const abortError = () => {
    const err = new DOMException('Aborted', 'AbortError');
    throw err;
  };
  if (signal?.aborted) abortError();

  const q = new URLSearchParams();
  if (opts?.lite) q.set('lite', '1');
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(`/scrap-library/embed/enrich/status/stream${suffix}`, {
    signal,
  });
  if (signal?.aborted) abortError();
  if (!res.ok) throw new Error(await parseError(res));
  if (!res.body) throw new Error('无流式响应');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const onAbort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      if (signal?.aborted) abortError();
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';
      for (const chunk of chunks) {
        const line = chunk
          .split('\n')
          .map((l) => l.trim())
          .find((l) => l.startsWith('data:'));
        if (!line) continue;
        const raw = line.replace(/^data:\s*/, '');
        try {
          const evt = JSON.parse(raw) as {
            event?: string;
            data?: ScrapLibraryEnrichJobStatus;
          };
          if (evt.event === 'status' && evt.data) {
            onStatus(evt.data);
          } else if (evt.event === 'error') {
            const msg = String(
              (evt.data as { message?: string } | undefined)?.message || '推送失败',
            );
            opts?.onError?.(msg);
          }
        } catch {
          /* ignore bad chunk */
        }
      }
    }
  } catch (e) {
    if (signal?.aborted) abortError();
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    if (e instanceof Error && e.name === 'AbortError') throw e;
    const msg = e instanceof Error ? e.message : '推送中断';
    opts?.onError?.(msg);
    throw e;
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }
}

export async function getScrapLibraryEnrichLogs(opts?: {
  region?: string;
  limit?: number;
}): Promise<{ region?: string | null; log: string[] }> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(
    `/scrap-library/embed/enrich/logs${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{ region?: string | null; log: string[] }>
  ).data;
}

export async function getScrapLibraryEnrichQueueLog(opts?: {
  region?: string;
  status?: string;
  code?: string;
  limit?: number;
  offset?: number;
}): Promise<{
  region?: string | null;
  code?: string | null;
  counts: {
    pending: number;
    running: number;
    done: number;
    soft?: number;
    fail: number;
  };
  items: ScrapLibraryEnrichQueueItem[];
  total?: number;
  limit?: number;
  offset?: number;
}> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.status) q.set('status', opts.status);
  if (opts?.code) q.set('code', opts.code);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  const res = await apiFetch(
    `/scrap-library/embed/enrich/queue-log${q.toString() ? `?${q}` : ''}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      region?: string | null;
      code?: string | null;
      counts: {
        pending: number;
        running: number;
        done: number;
        soft?: number;
        fail: number;
      };
      items: ScrapLibraryEnrichQueueItem[];
      total?: number;
      limit?: number;
      offset?: number;
    }>
  ).data;
}

export async function getScrapLibraryEnrichLocalCovers(opts: {
  region?: string;
  code?: string;
  itemId?: string;
}): Promise<{
  ok?: boolean;
  folder?: string;
  posterApi?: string;
  thumbApi?: string;
  fanartApi?: string;
  files?: Array<{
    kind?: string;
    name?: string;
    posterApi?: string;
    mtime?: number;
  }>;
}> {
  const q = new URLSearchParams();
  if (opts.region) q.set('region', opts.region);
  if (opts.code) q.set('code', opts.code);
  if (opts.itemId) q.set('itemId', opts.itemId);
  const res = await apiFetch(
    `/scrap-library/embed/enrich/local-covers${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      folder?: string;
      posterApi?: string;
      thumbApi?: string;
      fanartApi?: string;
      files?: Array<{
        kind?: string;
        name?: string;
        posterApi?: string;
        mtime?: number;
      }>;
    }>
  ).data;
}

export async function scanScrapLibraryEnrichQueue(body?: {
  region?: string;
  limit?: number;
}): Promise<{
  ok?: boolean;
  scanned?: boolean;
  scannedN?: number;
  listedN?: number;
  pendingTotal?: number;
  prunedN?: number;
  mode?: string;
  reason?: string;
  region?: string | null;
  counts: {
    pending: number;
    running: number;
    done: number;
    soft?: number;
    fail: number;
  };
  items: ScrapLibraryEnrichQueueItem[];
  localDone?: number;
  localSoft?: number;
  localFail?: number;
  /** 磁盘本地 NFO 分类数（仅诊断用；角标以 counts/localDone 为准） */
  localDiskDone?: number;
  localDiskSoft?: number;
  localDiskFail?: number;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/queue-scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      region: body?.region || '',
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      scanned?: boolean;
      scannedN?: number;
      listedN?: number;
      pendingTotal?: number;
      prunedN?: number;
      mode?: string;
      reason?: string;
      region?: string | null;
      counts: {
        pending: number;
        running: number;
        done: number;
        soft?: number;
        fail: number;
      };
      items: ScrapLibraryEnrichQueueItem[];
      localDone?: number;
      localSoft?: number;
      localFail?: number;
      localDiskDone?: number;
      localDiskSoft?: number;
      localDiskFail?: number;
    }>
  ).data;
}

export async function clearScrapLibraryEnrichLogs(opts?: {
  region?: string;
}): Promise<{
  ok?: boolean;
  cleared?: boolean;
  busy?: boolean;
  error?: string;
  checkpointCleared?: boolean;
  region?: string | null;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/logs/clear', {
    method: 'POST',
    body: JSON.stringify({ region: opts?.region ?? '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (
    (await res.json()) as Envelope<{
      ok?: boolean;
      cleared?: boolean;
      busy?: boolean;
      error?: string;
      checkpointCleared?: boolean;
      region?: string | null;
    }>
  ).data;
  if (data && data.ok === false) {
    throw new Error(String(data.error || '清空失败'));
  }
  return data;
}

