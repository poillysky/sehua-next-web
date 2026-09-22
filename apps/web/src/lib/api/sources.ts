/**
 * 刮削源设置与探测
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

export type ScrapeSourceLastProbe = {
  ok: boolean;
  ms?: number | null;
  message?: string;
  at?: number;
};

export type ScrapeSourceRow = {
  id: string;
  label: string;
  group: string;
  defaultUrl: string;
  probePath?: string;
  access?: string;
  accessLabel?: string;
  defaultCookie?: string;
  notes?: string;
  implemented?: boolean;
  needsApiKey?: boolean;
  seeds?: string[];
  enabled: boolean;
  baseUrl: string;
  cookie: string;
  apiKey: string;
  activeBase: string;
  displayUrl: string;
  lastProbe?: ScrapeSourceLastProbe | null;
};

export type ScrapeSourceGroup = {
  id: string;
  label: string;
  sources: ScrapeSourceRow[];
};

export type ScrapeSourcesCatalog = {
  groups: ScrapeSourceGroup[];
  sources: ScrapeSourceRow[];
  updatedAt?: string | null;
};

export type ScrapeSourceProbeResult = {
  ok: boolean;
  source?: string;
  ms?: number;
  activeBase?: string;
  seed?: string;
  message?: string;
};

export type ScrapeSourceProbeStatus = {
  running: boolean;
  done: number;
  total: number;
  current: string;
  results: ScrapeSourceProbeResult[];
};

export async function getScrapeSources(): Promise<ScrapeSourcesCatalog> {
  const res = await apiFetch('/settings/scrape-sources');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapeSourcesCatalog>).data;
}

export async function putScrapeSource(
  sourceId: string,
  body: {
    enabled?: boolean;
    baseUrl?: string;
    cookie?: string;
    apiKey?: string;
    activeBase?: string;
  },
): Promise<ScrapeSourcesCatalog> {
  const res = await apiFetch(
    `/settings/scrape-sources/${encodeURIComponent(sourceId)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapeSourcesCatalog>).data;
}

export async function probeScrapeSource(
  source: string,
  persist = true,
): Promise<ScrapeSourceProbeResult> {
  const res = await apiFetch('/settings/scrape-sources/probe', {
    method: 'POST',
    body: JSON.stringify({ source, persist, all: false }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeSourceProbeResult> & {
    message?: string;
  };
  return json.data;
}

export async function probeAllScrapeSources(
  onlyEnabled = true,
): Promise<{ started: boolean; total: number }> {
  const res = await apiFetch('/settings/scrape-sources/probe', {
    method: 'POST',
    body: JSON.stringify({ all: true, onlyEnabled, persist: true }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean; total: number }>)
    .data;
}

export async function getScrapeSourcesProbeStatus(): Promise<ScrapeSourceProbeStatus> {
  const res = await apiFetch('/settings/scrape-sources/probe/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapeSourceProbeStatus>).data;
}
