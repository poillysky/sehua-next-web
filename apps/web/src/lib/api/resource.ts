/**
 * 资源浏览 / 搜索 / 翻译
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

export async function fetchBrowse(opts: {
  page?: number;
  pageSize?: number;
  boardFid?: string;
  board?: string;
  boardParent?: string;
  keyword?: string;
  withTotalCount?: boolean;
  signal?: AbortSignal;
}): Promise<BrowseResult> {
  const q = new URLSearchParams();
  q.set('p', String(opts.page ?? 1));
  q.set('ps', String(opts.pageSize ?? 10));
  q.set('withTotalCount', opts.withTotalCount === true ? '1' : '0');
  if (opts.boardFid) q.set('board_fid', opts.boardFid);
  if (opts.board) q.set('board', opts.board);
  if (opts.boardParent) q.set('board_parent', opts.boardParent);
  if (opts.keyword?.trim()) q.set('keyword', opts.keyword.trim());
  const res = await apiFetch(`/browse?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<BrowseResult>).data;
}

export async function fetchSearch(opts: {
  keyword: string;
  page?: number;
  pageSize?: number;
  sortType?: SortType;
  filterTime?: FilterTime;
  filterSize?: FilterSize;
  matchMode?: MatchMode;
  withTotalCount?: boolean;
  countOnly?: boolean;
  preferChinese?: boolean;
  preferCrack?: boolean;
  region?: string;
  includeOptionalBoards?: boolean;
  signal?: AbortSignal;
}): Promise<SearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  q.set('p', String(opts.page ?? 1));
  q.set('ps', String(opts.pageSize ?? 10));
  q.set('sortType', opts.sortType ?? 'default');
  q.set('filterTime', opts.filterTime ?? 'all');
  q.set('filterSize', opts.filterSize ?? 'all');
  q.set('matchMode', opts.matchMode ?? 'smart');
  q.set('withTotalCount', opts.withTotalCount === false ? '0' : '1');
  if (opts.countOnly) q.set('countOnly', '1');
  const preferOn = Boolean(opts.preferChinese || opts.preferCrack);
  q.set('jp', preferOn ? '1' : '0');
  q.set('cn', opts.preferChinese ? '1' : '0');
  q.set('ck', opts.preferCrack ? '1' : '0');
  if (opts.region) {
    q.set('region', opts.region);
    if (opts.includeOptionalBoards === false) q.set('optb', '0');
  }
  const res = await apiFetch(`/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<SearchResult>).data;
}

export async function fetchTranslate(
  text: string,
  opts?: { target?: 'en' | 'zh' | string },
): Promise<{
  text: string;
  alreadyEnglish: boolean;
  alreadyChinese?: boolean;
  engine?: string;
  target?: string;
}> {
  const res = await apiFetch('/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      target: opts?.target || 'en',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      text: string;
      alreadyEnglish: boolean;
      alreadyChinese?: boolean;
      engine?: string;
      target?: string;
    }>
  ).data;
}

export async function saveScrapLibraryPlot(opts: {
  itemId: string;
  plot: string;
}): Promise<{
  ok: boolean;
  itemId?: string;
  code?: string;
  title?: string;
  sourceText?: string;
  plot?: string;
}> {
  const res = await apiFetch('/scrap-library/embed/plot', {
    method: 'POST',
    body: JSON.stringify({
      itemId: opts.itemId,
      plot: opts.plot,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok: boolean;
      itemId?: string;
      code?: string;
      title?: string;
      sourceText?: string;
      plot?: string;
    }>
  ).data;
}

export async function fetchResource(hash: string): Promise<ResourceItem> {
  const res = await apiFetch(`/resources/${encodeURIComponent(hash)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceItem>).data;
}

