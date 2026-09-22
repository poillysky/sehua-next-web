/**
 * 影视榜单与详情
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

export function proxiedCoverUrl(
  url: string | null | undefined,
  opts?: { w?: number; rp?: boolean },
): string {
  let s = String(url || "").trim();
  if (!s) return "";
  // 协议相对地址
  if (s.startsWith("//")) s = `https:${s}`;
  const w =
    typeof opts?.w === "number" && opts.w >= 32 && opts.w <= 1280
      ? Math.round(opts.w)
      : 0;
  const appendParams = (base: string) => {
    let out = base;
    if (w && !/[?&]w=\d+/.test(out)) {
      out = out.includes("?") ? `${out}&w=${w}` : `${out}?w=${w}`;
    }
    if (
      typeof opts?.rp === "boolean" &&
      w > 0 &&
      !/[?&]rp=/.test(out)
    ) {
      out = `${out}${out.includes("?") ? "&" : "?"}rp=${opts.rp ? 1 : 0}`;
    }
    return out;
  };
  if (
    s.startsWith(`${API_BASE}/cover-proxy?`) ||
    s.includes("/cover-proxy?")
  ) {
    return appendParams(s);
  }
  // 外站相对路径不应拼到 /api；仅本站 /api|/covers 等保留
  if (s.startsWith("/")) {
    if (s.startsWith(`${API_BASE}/`) || s === API_BASE) {
      return appendParams(s);
    }
    // /pics/... 这类外站相对路径无法代理
    if (
      s.startsWith("/api/") ||
      s.startsWith("/covers/") ||
      s.startsWith("/brand/") ||
      s.startsWith("/scrap-library/")
    ) {
      const joined = `${API_BASE}${s.startsWith("/api/") ? s.slice(4) : s}`;
      return appendParams(joined);
    }
    return "";
  }
  if (!/^https?:\/\//i.test(s)) return s;
  const base = `${API_BASE}/cover-proxy?url=${encodeURIComponent(s)}`;
  return w ? `${base}&w=${w}` : base;
}


/* —— Media (TMDB / 豆瓣 / Bangumi / AniList) —— */

export type MediaSourceId = 'tmdb' | 'douban' | 'bangumi' | 'anilist';
export type MediaCategoryId = 'movie' | 'tv' | 'anime' | 'variety';

export type MediaCastPerson = {
  id?: string | null;
  name: string;
  avatarUrl?: string | null;
};

export type MediaItem = {
  source: MediaSourceId;
  id: string;
  mediaType: 'movie' | 'tv';
  title: string;
  originalTitle?: string | null;
  aka: string[];
  posterUrl?: string | null;
  year?: string | null;
  rating?: number | null;
  overview?: string | null;
  cast?: Array<MediaCastPerson | string>;
  genres?: string[];
  runtime?: number | null;
  countries?: string[];
};

export type MediaChartResult = {
  source: MediaSourceId;
  category: MediaCategoryId;
  chart: string;
  page: number;
  totalPages: number;
  items: MediaItem[];
};

export type MediaSearchResult = {
  source: MediaSourceId;
  query: string;
  /** 服务端拆分后的片名列表（多片名逐条搜再合并） */
  terms?: string[];
  page: number;
  totalPages: number;
  items: MediaItem[];
};

export type MediaRelatedResult = {
  similar: MediaItem[];
  recommendations: MediaItem[];
};

export type MediaMeta = {
  tmdbConfigured: boolean;
  categories: Array<{ id: MediaCategoryId; label: string }>;
  sources: Array<{
    id: MediaSourceId;
    label: string;
    charts: Array<{ id: string; label: string }>;
  }>;
};

export async function fetchMediaMeta(signal?: AbortSignal): Promise<MediaMeta> {
  const res = await apiFetch('/media/meta', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaMeta>).data;
}

export async function fetchMediaCharts(opts: {
  source: MediaSourceId;
  category: MediaCategoryId;
  chart: string;
  page?: number;
  signal?: AbortSignal;
}): Promise<MediaChartResult> {
  const q = new URLSearchParams();
  q.set('category', opts.category);
  q.set('chart', opts.chart);
  if (opts.page != null) q.set('page', String(opts.page));
  const path =
    opts.source === 'douban'
      ? `/media/douban/charts?${q}`
      : opts.source === 'bangumi'
        ? `/media/bangumi/charts?${q}`
        : opts.source === 'anilist'
          ? `/media/anilist/charts?${q}`
          : `/media/tmdb/charts?${q}`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaChartResult>).data;
}

export type MediaGenre = { id: number; name: string };

export type MediaDiscoverSort =
  | 'popularity.desc'
  | 'vote_average.desc'
  | 'primary_release_date.desc'
  | 'first_air_date.desc'
  | 'revenue.desc'
  | 'vote_count.desc';

export type MediaDiscoverResult = {
  source: 'tmdb';
  mediaType: 'movie' | 'tv';
  genre?: string | null;
  sortBy: string;
  year?: string | null;
  page: number;
  totalPages: number;
  totalResults?: number;
  items: MediaItem[];
};

export async function fetchMediaGenres(opts: {
  mediaType: 'movie' | 'tv';
  signal?: AbortSignal;
}): Promise<MediaGenre[]> {
  const q = new URLSearchParams({ media_type: opts.mediaType });
  const res = await apiFetch(`/media/tmdb/genres?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ genres?: MediaGenre[] }>).data;
  return data.genres || [];
}

export async function fetchMediaDiscover(opts: {
  mediaType: 'movie' | 'tv';
  genre?: string;
  sortBy?: string;
  year?: string;
  page?: number;
  signal?: AbortSignal;
}): Promise<MediaDiscoverResult> {
  const q = new URLSearchParams();
  q.set('media_type', opts.mediaType);
  if (opts.genre) q.set('genre', opts.genre);
  if (opts.sortBy) q.set('sortBy', opts.sortBy);
  if (opts.year) q.set('year', opts.year);
  if (opts.page != null) q.set('page', String(opts.page));
  const res = await apiFetch(`/media/tmdb/discover?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaDiscoverResult>).data;
}

export async function fetchMediaSearch(opts: {
  source: MediaSourceId;
  q: string;
  page?: number;
  signal?: AbortSignal;
}): Promise<MediaSearchResult> {
  const params = new URLSearchParams();
  params.set('source', opts.source);
  params.set('q', opts.q);
  if (opts.page != null) params.set('page', String(opts.page));
  const res = await apiFetch(`/media/search?${params}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaSearchResult>).data;
}

export async function fetchMediaDetail(opts: {
  source: MediaSourceId;
  id: string;
  mediaType?: 'movie' | 'tv';
  signal?: AbortSignal;
}): Promise<MediaItem> {
  const path =
    opts.source === 'douban'
      ? `/media/douban/subject/${encodeURIComponent(opts.id)}`
      : opts.source === 'bangumi'
        ? `/media/bangumi/subject/${encodeURIComponent(opts.id)}`
        : opts.source === 'anilist'
          ? `/media/anilist/${encodeURIComponent(opts.id)}`
          : `/media/tmdb/${encodeURIComponent(opts.mediaType || 'movie')}/${encodeURIComponent(opts.id)}`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaItem>).data;
}

export async function fetchMediaRelated(opts: {
  source: MediaSourceId;
  mediaType: 'movie' | 'tv';
  id: string;
  signal?: AbortSignal;
}): Promise<MediaRelatedResult> {
  const path =
    opts.source === 'douban'
      ? `/media/douban/subject/${encodeURIComponent(opts.id)}/related`
      : opts.source === 'bangumi'
        ? `/media/bangumi/subject/${encodeURIComponent(opts.id)}/related`
        : opts.source === 'anilist'
          ? `/media/anilist/${encodeURIComponent(opts.id)}/related`
          : `/media/tmdb/${encodeURIComponent(opts.mediaType)}/${encodeURIComponent(opts.id)}/related`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaRelatedResult>).data;
}

export type MediaPersonWorksResult = {
  source: MediaSourceId;
  personId: string;
  name: string;
  items: MediaItem[];
};

export async function fetchMediaPersonWorks(opts: {
  source: MediaSourceId;
  q: string;
  personId?: string;
  signal?: AbortSignal;
}): Promise<MediaPersonWorksResult> {
  const params = new URLSearchParams();
  params.set('source', opts.source);
  if (opts.q) params.set('q', opts.q);
  if (opts.personId) params.set('person_id', opts.personId);
  const res = await apiFetch(`/media/person/works?${params}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaPersonWorksResult>).data;
}

/* —— 片商目录（六区；japan_gravure 为旧写真别名，已并入有码） —— */

