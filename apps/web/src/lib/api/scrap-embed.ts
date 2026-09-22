/**
 * 刮削库向量设置
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

export type ScrapLibraryEmbedSettings = {
  root: string;
  resolved?: string;
  default_root?: string;
  meta_db?: string;
  table?: string;
  updated_at?: string | null;
};

export type ScrapLibraryEmbedStats = {
  meta_db?: string;
  table?: string;
  embedded?: number;
  nfo_files?: number;
  root?: string;
  indexes?: string[];
};

export type ScrapLibraryEmbedJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    written?: number;
    skipped?: number;
    deleted?: number;
    total?: number;
    meta_db?: string;
    mode?: string;
  } | null;
  error?: string | null;
};

export async function getScrapLibraryEmbedSettings(): Promise<ScrapLibraryEmbedSettings> {
  const res = await apiFetch('/scrap-library/embed');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedSettings>).data;
}

export async function putScrapLibraryEmbedSettings(
  root: string,
): Promise<ScrapLibraryEmbedSettings> {
  const res = await apiFetch('/scrap-library/embed', {
    method: 'PUT',
    body: JSON.stringify({ root }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedSettings>).data;
}

export async function getScrapLibraryEmbedStats(): Promise<ScrapLibraryEmbedStats> {
  const res = await apiFetch('/scrap-library/embed/stats');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedStats>).data;
}

export async function getScrapLibraryEmbedStatus(): Promise<ScrapLibraryEmbedJobStatus> {
  const res = await apiFetch('/scrap-library/embed/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedJobStatus>).data;
}

export async function startScrapLibraryEmbed(body?: {
  root?: string;
  force?: boolean;
  /** full=元数据+向量；meta=仅同步数据库；embed=仅向量化 */
  mode?: 'full' | 'meta' | 'embed';
}): Promise<{ started: boolean; mode?: string; resumed?: boolean }> {
  const res = await apiFetch('/scrap-library/embed/start', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    started: boolean;
    mode?: string;
    resumed?: boolean;
  }>).data;
}

