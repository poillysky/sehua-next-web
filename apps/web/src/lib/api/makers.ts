/**
 * 片商目录
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

export type MakerCatalogSourceId =
  | 'japan_censored'
  | 'japan_uncensored'
  | 'japan_amateur'
  /** @deprecated 已并入 japan_censored */
  | 'japan_gravure'
  | 'fc2'
  | 'china'
  | 'western'
  | 'javbus'
  | 'iqqtv';

export type MakerCatalogItem = {
  source: MakerCatalogSourceId;
  kind?: string | null;
  provider?: string | null;
  id: string;
  code?: string | null;
  title: string;
  originalTitle?: string | null;
  posterUrl?: string | null;
  year?: string | null;
  date?: string | null;
  studio?: string | null;
  maker?: string | null;
  publisher?: string | null;
  director?: string | null;
  series?: string | null;
  runtime?: number | null;
  actors?: string[];
  cast?: Array<{ name: string; id?: string | null; avatarUrl?: string | null }>;
  tags?: string[];
  samples?: string[];
  overview?: string | null;
};

export type MakerCatalogMeta = {
  kinds?: Array<{
    id: MakerCatalogSourceId;
    label: string;
    charts: Array<{ id: string; label: string }>;
  }>;
  sources: Array<{
    id: MakerCatalogSourceId;
    label: string;
    charts: Array<{ id: string; label: string }>;
  }>;
};

export type MakerCatalogChartResult = {
  source: MakerCatalogSourceId;
  chart: string;
  page: number;
  totalPages: number;
  items: MakerCatalogItem[];
};

export type MakerCatalogSearchResult = {
  source: MakerCatalogSourceId;
  query: string;
  page: number;
  totalPages: number;
  items: MakerCatalogItem[];
};

export async function fetchMakerCatalogMeta(
  signal?: AbortSignal,
): Promise<MakerCatalogMeta> {
  const res = await apiFetch('/makers/meta', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerCatalogMeta>).data;
}

export async function fetchMakerCatalogCharts(opts: {
  source: MakerCatalogSourceId;
  chart: string;
  page?: number;
  signal?: AbortSignal;
}): Promise<MakerCatalogChartResult> {
  const q = new URLSearchParams();
  q.set('chart', opts.chart);
  if (opts.page != null) q.set('page', String(opts.page));
  const res = await apiFetch(`/makers/${opts.source}/charts?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerCatalogChartResult>).data;
}

export async function fetchMakerCatalogSearch(opts: {
  source: MakerCatalogSourceId;
  q: string;
  page?: number;
  signal?: AbortSignal;
}): Promise<MakerCatalogSearchResult> {
  const q = new URLSearchParams();
  q.set('q', opts.q);
  if (opts.page != null) q.set('page', String(opts.page));
  const res = await apiFetch(`/makers/${opts.source}/search?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerCatalogSearchResult>).data;
}

export async function fetchMakerCatalogDetail(opts: {
  source: MakerCatalogSourceId;
  id: string;
  signal?: AbortSignal;
}): Promise<MakerCatalogItem> {
  const q = new URLSearchParams();
  q.set('id', opts.id);
  const res = await apiFetch(`/makers/${opts.source}/detail?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerCatalogItem>).data;
}

export async function fetchMakerCatalogStar(opts: {
  source: MakerCatalogSourceId;
  id?: string | null;
  q?: string | null;
  page?: number;
  signal?: AbortSignal;
}): Promise<MakerCatalogSearchResult> {
  const q = new URLSearchParams();
  if (opts.id) q.set('id', opts.id);
  if (opts.q) q.set('q', opts.q);
  if (opts.page != null) q.set('page', String(opts.page));
  const res = await apiFetch(`/makers/${opts.source}/star?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerCatalogSearchResult>).data;
}

export type MakersCatalogConfig = {
  configured?: boolean;
  hubStatus?: string;
  sourceOrder?: Array<'javbus' | 'iqqtv' | 'missav' | '7mmtv' | 'madou' | string>;
  javbus?: {
    enabled?: boolean;
    bases?: string[];
    cookie?: string;
    activeBase?: string;
  };
  iqqtv?: {
    enabled?: boolean;
    seeds?: string[];
    activeBase?: string;
  };
  missav?: {
    enabled?: boolean;
    seeds?: string[];
    activeBase?: string;
  };
  '7mmtv'?: {
    enabled?: boolean;
    seeds?: string[];
    activeBase?: string;
  };
  madou?: {
    enabled?: boolean;
    seeds?: string[];
    activeBase?: string;
  };
  live?: Record<
    string,
    { activeBase?: string; cached?: boolean; updatedAt?: string }
  >;
  refresh?: Record<
    string,
    { ok?: boolean; activeBase?: string; ms?: number; error?: string }
  >;
  sources?: Array<{
    id: string;
    label: string;
    notes?: string;
    enabled?: boolean;
    activeBase?: string;
  }>;
  updatedAt?: string;
};

export async function getMakersCatalog(): Promise<MakersCatalogConfig> {
  const res = await apiFetch('/settings/makers');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakersCatalogConfig>).data;
}

export async function refreshMakersMirrors(): Promise<MakersCatalogConfig> {
  const res = await apiFetch('/settings/makers/refresh', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakersCatalogConfig>).data;
}

type SeedProviderBody = {
  enabled?: boolean;
  seeds?: string | string[];
  activeBase?: string;
};

export async function putMakersCatalog(body: {
  javbus?: {
    enabled?: boolean;
    bases?: string | string[];
    cookie?: string;
    activeBase?: string;
  };
  iqqtv?: SeedProviderBody;
  missav?: SeedProviderBody;
  '7mmtv'?: SeedProviderBody;
  madou?: SeedProviderBody;
  sourceOrder?: string[];
}): Promise<MakersCatalogConfig> {
  const res = await apiFetch('/settings/makers', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakersCatalogConfig>).data;
}

export async function testMakersCatalog(body: {
  source: 'javbus' | 'iqqtv' | 'missav' | '7mmtv' | 'madou';
  persist?: boolean;
  javbus?: { enabled?: boolean; bases?: string | string[]; cookie?: string };
  iqqtv?: { enabled?: boolean; seeds?: string | string[] };
  missav?: { enabled?: boolean; seeds?: string | string[] };
  '7mmtv'?: { enabled?: boolean; seeds?: string | string[] };
  madou?: { enabled?: boolean; seeds?: string | string[] };
}): Promise<{ ok: boolean; message: string; data?: Record<string, unknown> }> {
  const res = await apiFetch('/settings/makers/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<Record<string, unknown>> & {
    message: string;
  };
  return {
    ok: Boolean(json.data?.ok ?? true),
    message: json.message || '',
    data: json.data,
  };
}

/* —— 六区前缀/番号目录 —— */

