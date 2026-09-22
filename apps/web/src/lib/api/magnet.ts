/**
 * 磁力搜索、盘搜、CloudSaver
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
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

export type MagnetFile = {
  index: number;
  path: string;
  size: number;
  extension?: string;
};

export type MagnetHit = {
  title: string;
  path: string;
  hash?: string;
  name?: string;
  infoHash?: string;
  detailUrl?: string;
  size?: number;
  sizeText?: string;
  fileCount?: number | null;
  files_count?: number | null;
  files?: MagnetFile[] | null;
  single_file?: boolean;
  seeders?: number | null;
  leechers?: number | null;
  created_at?: number;
  createdAt?: string;
  magnet?: string | null;
  magnet_uri?: string | null;
  magnets?: string[] | null;
};

export type MagnetSearchResult = {
  keyword: string;
  keywords?: string[];
  page?: number;
  source: string;
  baseUrl?: string;
  openUrl?: string;
  items: MagnetHit[];
  total: number;
  hasMore?: boolean;
  costMs?: number;
};

export async function fetchMagnetSearch(opts: {
  keyword: string;
  page?: number;
  sortType?: string;
  filterTime?: string;
  filterSize?: string;
  signal?: AbortSignal;
}): Promise<MagnetSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  q.set('page', String(opts.page ?? 1));
  if (opts.sortType) q.set('sortType', opts.sortType);
  if (opts.filterTime) q.set('filterTime', opts.filterTime);
  if (opts.filterSize) q.set('filterSize', opts.filterSize);
  const res = await apiFetch(`/magnet/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetSearchResult>).data;
}

export type PansouLink = {
  type: string;
  url: string;
  password?: string;
  workTitle?: string;
  label?: string;
};

export type PansouHit = {
  id: string;
  title: string;
  content?: string;
  channel?: string;
  datetime?: string;
  tags?: string[];
  links: PansouLink[];
};

export type PansouSearchResult = {
  keyword: string;
  source: string;
  baseUrl?: string;
  host?: string;
  total: number;
  items: PansouHit[];
};

export async function fetchPansouSearch(opts: {
  keyword: string;
  refresh?: boolean;
  src?: 'all' | 'tg' | 'plugin';
  signal?: AbortSignal;
}): Promise<PansouSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  if (opts.refresh) q.set('refresh', 'true');
  if (opts.src) q.set('src', opts.src);
  const res = await apiFetch(`/pansou/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSearchResult>).data;
}

export async function fetchCloudSaverSearch(opts: {
  keyword: string;
  signal?: AbortSignal;
}): Promise<PansouSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  const res = await apiFetch(`/cloudsaver/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSearchResult>).data;
}

export type PansouSettings = {
  enabled: boolean;
  baseUrl: string;
  timeoutSec: number;
  note?: string;
};

export async function getPansouSettings(): Promise<PansouSettings> {
  const res = await apiFetch('/settings/pansou');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSettings>).data;
}

export async function putPansouSettings(body: {
  enabled: boolean;
  baseUrl: string;
  timeoutSec?: number;
  note?: string;
}): Promise<PansouSettings> {
  const res = await apiFetch('/settings/pansou', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSettings>).data;
}

export async function testPansou(): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/pansou/health');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ ok?: boolean; message?: string }>).data;
  return {
    ok: Boolean(data?.ok),
    message: data?.message || (data?.ok ? '连接成功' : '连接失败'),
  };
}

export type CloudSaverSettings = {
  enabled: boolean;
  baseUrl: string;
  username: string;
  hasPassword?: boolean;
  timeoutSec: number;
  note?: string;
};

export async function getCloudSaverSettings(): Promise<CloudSaverSettings> {
  const res = await apiFetch('/settings/cloudsaver');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<CloudSaverSettings>).data;
}

export async function putCloudSaverSettings(body: {
  enabled: boolean;
  baseUrl: string;
  username: string;
  password?: string;
  timeoutSec?: number;
  note?: string;
}): Promise<CloudSaverSettings> {
  const res = await apiFetch('/settings/cloudsaver', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<CloudSaverSettings>).data;
}

export async function testCloudSaver(): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/cloudsaver/health');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ ok?: boolean; message?: string }>).data;
  return {
    ok: Boolean(data?.ok),
    message: data?.message || (data?.ok ? '登录成功' : '登录失败'),
  };
}

export async function fetchMagnetDetail(
  hash: string,
  signal?: AbortSignal,
): Promise<MagnetHit> {
  const q = new URLSearchParams();
  q.set('hash', hash);
  const res = await apiFetch(`/magnet/detail?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetHit>).data;
}

export type MagnetPreviewShot = {
  time?: number | null;
  screenshot: string;
};

export type MagnetPreview = {
  hash: string;
  name?: string;
  file_type?: string;
  size?: number;
  count?: number;
  screenshots: MagnetPreviewShot[];
  error?: string;
};

export async function fetchMagnetPreview(
  hash: string,
  signal?: AbortSignal,
): Promise<MagnetPreview> {
  const q = new URLSearchParams();
  q.set('hash', hash);
  const res = await apiFetch(`/magnet/preview?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetPreview>).data;
}

