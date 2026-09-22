/**
 * 刮削字幕
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

export async function ensureScrapLibraryPoster(
  itemIdOrOpts:
    | string
    | {
        itemId?: string;
        coverUrl?: string;
      },
) {
  const opts =
    typeof itemIdOrOpts === 'string'
      ? { itemId: itemIdOrOpts, coverUrl: '' }
      : itemIdOrOpts || {};
  const id = String(opts.itemId || '').trim();
  const coverUrl = String(opts.coverUrl || '').trim();
  if (!id && !coverUrl) return null;
  const q = new URLSearchParams();
  if (id) q.set('itemId', id);
  if (coverUrl) q.set('coverUrl', coverUrl);
  const res = await apiFetch(`/scrap-library/embed/ensure-poster?${q}`, {
    method: 'POST',
  });
  if (!res.ok) return null;
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      skipped?: boolean;
      posterPath?: string;
      posterApi?: string;
      reason?: string;
    }>
  ).data;
}

export type ScrapSubtitleFile = {
  name?: string;
  path?: string;
  size?: number;
  rel?: string;
};

export type ScrapSubtitleFetchResult = {
  ok?: boolean;
  skipped?: boolean;
  code?: string;
  itemId?: string;
  saved?: string;
  lang?: string;
  source?: string;
  title?: string;
  files?: ScrapSubtitleFile[];
  message?: string;
  reason?: string;
  upload115?: {
    ok?: boolean;
    count?: number;
    message?: string;
    filename?: string;
    folderName?: string;
    normalized?: boolean;
  };
};

/** 搜中文字幕并保存；upload115 时同一请求内上传到 115 */
export async function fetchScrapLibrarySubtitles(opts: {
  itemId?: string;
  code?: string;
  force?: boolean;
  upload115?: boolean;
  region?: string;
}): Promise<ScrapSubtitleFetchResult> {
  const res = await apiFetch('/scrap-library/embed/subtitles/fetch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      itemId: opts.itemId || '',
      code: opts.code || '',
      force: Boolean(opts.force),
      upload115: Boolean(opts.upload115),
      region: opts.region || '',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<ScrapSubtitleFetchResult>
  ).data;
}

export async function listScrapLibrarySubtitles(opts: {
  itemId?: string;
  code?: string;
}): Promise<ScrapSubtitleFetchResult> {
  const q = new URLSearchParams();
  if (opts.itemId) q.set('itemId', opts.itemId);
  if (opts.code) q.set('code', opts.code);
  const res = await apiFetch(
    `/scrap-library/embed/subtitles${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<ScrapSubtitleFetchResult>
  ).data;
}

export type P115SubsUploadResult = {
  ok?: boolean;
  count?: number;
  message?: string;
  folderCid?: string;
  folderName?: string;
  filename?: string;
  failed?: Array<{ file?: string; message?: string }>;
};

/** 本地中文字幕立即上传到 115 配置的字幕目录 */
export async function uploadScrapSubsToP115(opts: {
  itemId?: string;
  code?: string;
  region?: string;
}): Promise<P115SubsUploadResult> {
  const res = await apiFetch('/settings/p115/subs/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scrapItemId: opts.itemId || undefined,
      attachSubsCode: opts.code || undefined,
      region: opts.region || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<P115SubsUploadResult> & {
    message?: string;
  };
  return {
    ...(json.data || {}),
    message: json.data?.message || json.message,
  };
}

