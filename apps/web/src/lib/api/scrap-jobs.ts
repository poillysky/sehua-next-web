/**
 * 刮削任务（女优资料 / NFO / 头像）
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import type { PrefixCatalogLocalIndexProgress } from './prefix';
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

export type ScrapActressOptimizeJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    unchanged?: number;
    updated?: number;
    reembedded?: number;
    maps?: { count?: number; lang?: string };
  } | null;
  error?: string | null;
};

export async function startScrapActressOptimize(body?: {
  reembed?: boolean;
  force?: boolean;
  limit?: number;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/actress-optimize/start', {
    method: 'POST',
    body: JSON.stringify({
      reembed: body?.reembed !== false,
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getScrapActressOptimizeStatus(): Promise<ScrapActressOptimizeJobStatus> {
  const res = await apiFetch('/scrap-library/embed/actress-optimize/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressOptimizeJobStatus>).data;
}

export type ScrapNfoOptimizeJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    updated?: number;
    unchanged?: number;
    errors?: number;
    maps?: { count?: number; lang?: string };
    samples?: string[];
  } | null;
  error?: string | null;
};

export async function startScrapNfoOptimize(body?: {
  force?: boolean;
  limit?: number;
}): Promise<{ started: boolean; resumed?: boolean }> {
  const res = await apiFetch('/scrap-library/embed/nfo-optimize/start', {
    method: 'POST',
    body: JSON.stringify({
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean; resumed?: boolean }>)
    .data;
}

export async function getScrapNfoOptimizeStatus(): Promise<ScrapNfoOptimizeJobStatus> {
  const res = await apiFetch('/scrap-library/embed/nfo-optimize/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapNfoOptimizeJobStatus>).data;
}

export type ScrapActressAvatarJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    downloaded?: number;
    downloadedGfriends?: number;
    downloadedJavbus?: number;
    skipped?: number;
    missed?: number;
    failed?: number;
    missSamples?: string[];
    polish?: {
      total?: number;
      updated?: number;
      unchanged?: number;
      reembedded?: number;
    };
  } | null;
  error?: string | null;
};

export async function startScrapActressAvatar(body?: {
  force?: boolean;
  limit?: number;
  region?: string;
  polishMeta?: boolean;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/actress-avatar/start', {
    method: 'POST',
    body: JSON.stringify({
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
      region: body?.region || '',
      polishMeta: body?.polishMeta !== false,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getScrapActressAvatarStatus(): Promise<ScrapActressAvatarJobStatus> {
  const res = await apiFetch('/scrap-library/embed/actress-avatar/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressAvatarJobStatus>).data;
}

/** 批量解析女优本地头像 API 路径（无头像则不出现在结果中） */
export type ScrapActressProfile = {
  name: string;
  queryName?: string;
  aliases?: string[];
  count?: number;
  posterApi?: string;
  url?: string;
  javdb?: string;
  birthday?: string;
  age?: number | null;
  height?: number | null;
  bust?: number | null;
  waist?: number | null;
  hip?: number | null;
  cup?: string;
  birthplace?: string;
  careerPeriod?: string;
  debutWork?: string;
  bioSource?: string;
  bioSourceUrl?: string;
};

export async function getScrapActressProfile(opts: {
  name: string;
  region?: string;
  refresh?: boolean;
}): Promise<ScrapActressProfile> {
  const q = new URLSearchParams();
  q.set('name', opts.name);
  if (opts.region) q.set('region', opts.region);
  if (opts.refresh) q.set('refresh', '1');
  const res = await apiFetch(
    `/scrap-library/embed/actress-profile?${q.toString()}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressProfile>).data;
}

export async function lookupScrapActressAvatarUrls(
  names: string[],
): Promise<Record<string, string>> {
  const cleaned = [
    ...new Set(
      names.map((n) => String(n || '').trim()).filter(Boolean),
    ),
  ];
  if (!cleaned.length) return {};
  const q = new URLSearchParams();
  for (const n of cleaned) q.append('names', n);
  const res = await apiFetch(
    `/scrap-library/embed/actress-avatar/urls?${q.toString()}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<Record<string, string>>
  ).data;
}

/** 与后端 `_safe_filename` 对齐的乐观头像 API（免等 urls 查询）。 */
export function actressAvatarPosterApiGuess(name: string): string {
  let s = String(name || '')
    .normalize('NFKC')
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^[ .]+|[ .]+$/g, '');
  if (!s) return '';
  if (s.length > 96) s = s.slice(0, 96);
  const rel = `scrap-library/_actress/${s}.jpg`;
  return `/scrap-library/file?path=${encodeURIComponent(rel)}`;
}

/** 会话级头像路径缓存：命中则进详情首帧即可出图。 */
const _actressAvatarApiCache = new Map<string, string>();

export function peekActressAvatarPosterApi(name: string): string {
  const n = String(name || '').trim();
  if (!n) return '';
  return _actressAvatarApiCache.get(n) || actressAvatarPosterApiGuess(n);
}

export function rememberActressAvatarPosterApis(
  map: Record<string, string>,
): void {
  for (const [k, v] of Object.entries(map || {})) {
    const name = String(k || '').trim();
    const api = String(v || '').trim();
    if (name && api) _actressAvatarApiCache.set(name, api);
  }
}

export type ScrapLibraryQualityStats = {
  region?: string | null;
  total?: number;
  incomplete?: number;
  /** 向量库内已有条目（不含空壳） */
  embedTotal?: number;
  /** 片商目录有、尚未进向量库的空壳 */
  shells?: number;
  counts?: {
    no_local?: number;
    no_media?: number;
    no_actress?: number;
    no_studio?: number;
    no_plot?: number;
    thin_title?: number;
  };
};

export type ScrapLibraryQualityItem = {
  itemId?: string;
  region?: string;
  prefix?: string;
  code?: string;
  title?: string;
  relPath?: string;
  gaps?: string[];
};

export type ScrapLibraryEnrichFieldRow = {
  id?: string;
  label?: string;
  ok?: boolean;
  value?: string;
  /** 该字段最终选用的站点 id */
  source?: string;
};

export type ScrapLibraryEnrichSourceTiming = {
  id?: string;
  access?: string;
  ms?: number;
  /** 等出站槽毫秒（后端第十一轮起）：「排队」与「真在干活」的耗时分开看 */
  waitMs?: number;
  /** hit / miss / down / busy / cancelled —— busy = 我们没轮到，不是源故障 */
  kind?: string;
  ok?: boolean;
  error?: string;
  actors?: number;
  poster?: boolean;
  status?: 'pending' | 'done' | 'fail' | 'skipped' | string;
};

