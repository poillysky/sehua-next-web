/**
 * 刮削库浏览、收藏、封面
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import { proxiedCoverUrl } from './media';
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

export type ScrapLibraryEmbedItem = {
  itemId?: string;
  region?: string;
  prefix?: string;
  code?: string;
  title?: string;
  sourceText?: string;
  year?: string;
  actresses?: string[];
  badges?: string[];
  cnsub?: boolean;
  definition?: string;
  mosaic?: string;
  relPath?: string;
  posterPath?: string;
  thumbPath?: string;
  fanartPath?: string;
  coverUrl?: string;
  posterApi?: string;
  thumbApi?: string;
  fanartApi?: string;
  score?: number;
};

export type ScrapLibraryEmbedRegion = {
  id: string;
  label: string;
  count: number;
};

export type ScrapLibraryEmbedPrefix = {
  prefix: string;
  count: number;
  /** 该前缀库内最新番号 */
  latestCode?: string;
  /** 该前缀库内最新发行年份（先后排序） */
  latestYear?: number;
  /** 该前缀最近入库/更新时间 ISO */
  latestAt?: string;
  /** 主力线优先级，越小越靠前 */
  lineRank?: number;
  blurb?: string;
  /** 标准厂牌名（有则可用于文件夹导航） */
  studio?: string;
  posterPath?: string;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
};

export type ScrapLibraryEmbedFacet = {
  name: string;
  count: number;
  kind: 'genre' | 'tag' | 'studio' | string;
  blurb?: string;
  age?: number | null;
  posterPath?: string;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
};

export type ScrapLibraryEmbedRecommendShelf = {
  region: string;
  label: string;
  latest: ScrapLibraryEmbedItem[];
  total?: number;
};

export type ScrapLibraryEmbedRecommend = {
  shelves?: ScrapLibraryEmbedRecommendShelf[];
  latest: ScrapLibraryEmbedItem[];
  genres: ScrapLibraryEmbedFacet[];
  collections: ScrapLibraryEmbedFacet[];
  folders: ScrapLibraryEmbedPrefix[];
  total: number;
};

export type ScrapLibraryEmbedItemsPage = {
  total: number;
  offset: number;
  limit: number;
  items: ScrapLibraryEmbedItem[];
};

export async function listScrapLibraryEmbedRegions(): Promise<
  ScrapLibraryEmbedRegion[]
> {
  const res = await apiFetch('/scrap-library/embed/regions');
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ regions: ScrapLibraryEmbedRegion[] }>).data
      .regions || []
  );
}

export async function listScrapLibraryEmbedPrefixes(
  region = '',
  opts?: { studio?: string; q?: string; limit?: number },
): Promise<ScrapLibraryEmbedPrefix[]> {
  const q = new URLSearchParams();
  if (region) q.set('region', region);
  if (opts?.studio) q.set('studio', opts.studio);
  if (opts?.q) q.set('q', opts.q);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(
    `/scrap-library/embed/prefixes${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prefixes: ScrapLibraryEmbedPrefix[] }>)
      .data.prefixes || []
  );
}

export async function listScrapLibraryEmbedItems(opts?: {
  region?: string;
  prefix?: string;
  q?: string;
  genre?: string;
  tag?: string;
  studio?: string;
  actress?: string;
  signal?: string;
  sort?: 'code' | 'recent' | 'name' | 'year' | 'studio' | 'prefix' | 'actress' | 'random' | string;
  order?: 'asc' | 'desc' | string;
  offset?: number;
  limit?: number;
}): Promise<ScrapLibraryEmbedItemsPage> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.prefix) q.set('prefix', opts.prefix);
  if (opts?.q) q.set('q', opts.q);
  if (opts?.genre) q.set('genre', opts.genre);
  if (opts?.tag) q.set('tag', opts.tag);
  if (opts?.studio) q.set('studio', opts.studio);
  if (opts?.actress) q.set('actress', opts.actress);
  if (opts?.signal) q.set('signal', opts.signal);
  if (opts?.sort) q.set('sort', opts.sort);
  if (opts?.order) q.set('order', opts.order);
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(
    `/scrap-library/embed/items${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedItemsPage>).data;
}

export async function listScrapLibraryEmbedFacets(opts?: {
  region?: string;
  kind?: 'genre' | 'tag' | 'studio' | 'actress' | string;
  studio?: string;
  prefix?: string;
  q?: string;
  sort?: 'name' | 'count' | string;
  order?: 'asc' | 'desc' | string;
  offset?: number;
  limit?: number;
}): Promise<{ facets: ScrapLibraryEmbedFacet[]; total: number }> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.kind) q.set('kind', opts.kind);
  if (opts?.studio) q.set('studio', opts.studio);
  if (opts?.prefix) q.set('prefix', opts.prefix);
  if (opts?.q) q.set('q', opts.q);
  if (opts?.sort) q.set('sort', opts.sort);
  if (opts?.order) q.set('order', opts.order);
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(
    `/scrap-library/embed/facets${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  const data = (
    (await res.json()) as Envelope<{
      facets: ScrapLibraryEmbedFacet[];
      total?: number;
    }>
  ).data;
  const facets = data.facets || [];
  return {
    facets,
    total: typeof data.total === 'number' ? data.total : facets.length,
  };
}

export async function refreshScrapLibraryEmbedFacetsSnapshot(opts?: {
  region?: string;
  kinds?: Array<'genre' | 'tag' | 'studio' | 'actress' | string>;
  /** 默认 true：六区全量；false 时仅刷 opts.region */
  allRegions?: boolean;
}): Promise<{
  region: string;
  regions: string[];
  kinds: Record<string, number>;
  recommend?: { shelves: number; total: number };
  updatedAt: number;
}> {
  const allRegions = opts?.allRegions !== false;
  const res = await apiFetch('/scrap-library/embed/facets/refresh', {
    method: 'POST',
    body: JSON.stringify({
      region: allRegions ? '' : opts?.region || '',
      kinds: opts?.kinds,
      allRegions,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      region: string;
      regions: string[];
      kinds: Record<string, number>;
      recommend?: { shelves: number; total: number };
      updatedAt: number;
    }>
  ).data;
}

export async function listScrapLibraryEmbedRecommend(
  _region = '',
): Promise<ScrapLibraryEmbedRecommend> {
  // 推荐页为各区货架，不再按单区过滤
  const res = await apiFetch('/scrap-library/embed/recommend');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEmbedRecommend>).data;
}

export async function searchScrapLibraryEmbed(opts: {
  query: string;
  limit?: number;
  region?: string;
}): Promise<ScrapLibraryEmbedItem[]> {
  const res = await apiFetch('/scrap-library/embed/search', {
    method: 'POST',
    body: JSON.stringify({
      query: opts.query,
      limit: opts.limit ?? 24,
      region: opts.region || '',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ hits: ScrapLibraryEmbedItem[] }>).data
      .hits || []
  );
}

/** 片商刮削库收藏（服务端按登录账号持久化） */
export type ScrapFavoriteServerItem = ScrapLibraryEmbedItem & {
  favoritedAt?: number;
  hubRegion?: string;
};

export async function listScrapFavoritesServer(): Promise<
  ScrapFavoriteServerItem[]
> {
  const res = await apiFetch('/scrap-favorites');
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (
      (await res.json()) as Envelope<{
        items: ScrapFavoriteServerItem[];
        total: number;
      }>
    ).data.items || []
  );
}

export async function addScrapFavoriteServer(
  item: ScrapLibraryEmbedItem,
  hubRegion?: string,
): Promise<void> {
  const itemId = String(item.itemId || '').trim();
  if (!itemId) throw new Error('缺少条目 ID');
  // itemId 含路径分隔符，放 body 而非 URL path
  const res = await apiFetch('/scrap-favorites', {
    method: 'PUT',
    body: JSON.stringify({
      itemId,
      region: String(hubRegion || '').trim(),
      payload: item,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function removeScrapFavoriteServer(itemId: string): Promise<void> {
  const id = String(itemId || '').trim();
  if (!id) throw new Error('缺少条目 ID');
  const q = new URLSearchParams();
  q.set('itemId', id);
  const res = await apiFetch(`/scrap-favorites?${q}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await parseError(res));
}

/** 影视列表缩略最长边 */
export const COVER_LIST_THUMB_W = 360;
/** 片商列表：保持清晰（约 2x 屏） */
export const SCRAP_LIST_THUMB_W = 360;
/** 拼贴 / 货架：竖图清晰度 */
export const SCRAP_COLLAGE_THUMB_W = 320;

/** 刮削库本地封面 → 可请求的 /api URL。
 * 一律 poster 优先；无 poster 才用 thumb（列表可配 rp 右裁）。
 * 默认不回退远程 coverUrl；需要外链时显式传 allowRemote: true。
 */
export function scrapLibraryCoverUrl(
  item: Pick<ScrapLibraryEmbedItem, 'posterApi' | 'thumbApi' | 'coverUrl'>,
  opts?: {
    w?: number;
    prefer?: 'thumb' | 'poster';
    rp?: boolean;
    allowRemote?: boolean;
  },
): string {
  const poster = String(item.posterApi || '').trim();
  const thumb = String(item.thumbApi || '').trim();
  const local = poster || thumb;
  // 无 poster 走 thumb 时默认右裁；有 poster 不裁（除非显式 rp）
  const rp = poster ? Boolean(opts?.rp) : opts?.rp !== false;
  const w =
    typeof opts?.w === 'number'
      ? opts.w
      : SCRAP_LIST_THUMB_W;
  if (local) {
    const via = proxiedCoverUrl(local, { w, rp });
    if (via) return via;
    let url = local.startsWith('/api/') ? local : `${API_BASE}${local}`;
    if (w > 0 && !/[?&]rp=/.test(url)) {
      url = `${url}${url.includes('?') ? '&' : '?'}rp=${rp ? 1 : 0}`;
    }
    return url;
  }
  if (!opts?.allowRemote) return '';
  return proxiedCoverUrl(item.coverUrl, { w, rp }) || '';
}

