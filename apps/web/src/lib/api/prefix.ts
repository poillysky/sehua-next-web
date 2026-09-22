/**
 * 番号前缀目录与 STRM 同步
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

export type PrefixCatalogRegionSummary = {
  id: string;
  label: string;
  prefix_count: number;
  /** 目录扫描后实际有番号的前缀数（不看本地刮削库） */
  scrap_prefix_count?: number;
  code_count: number;
};

export type PrefixCatalogSummary = {
  version?: number;
  updated_at?: string;
  principle?: string;
  regions: PrefixCatalogRegionSummary[];
  prefix_total: number;
  /** 各区「扫描后有番号的前缀」合计 */
  scrap_prefix_total?: number;
  code_total: number;
};

export type PrefixCatalogPrefixRow = {
  prefix: string;
  maker: string;
  maker_zh?: string;
  maker_ja?: string;
  maker_en?: string;
  sources?: string[];
  code_count: number;
  serial_min: number;
  serial_max: number;
  serial_max_hint?: number;
  pad?: number;
  status?: string;
  integrity?: string;
  verified_at?: string;
};

export type PrefixCatalogPrefixDetail = PrefixCatalogPrefixRow & {
  serials?: number[];
  codes?: string[];
  codes_offset?: number;
  codes_limit?: number;
  format?: string;
  dmm_digit?: string;
  label_ja?: string;
  notes?: string;
  serial_max_hint?: number;
};

export async function getPrefixCatalogSummary(): Promise<PrefixCatalogSummary> {
  const res = await apiFetch('/prefix-catalog');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogSummary>).data;
}

export async function getPrefixCatalogRegions(): Promise<PrefixCatalogRegionSummary[]> {
  const res = await apiFetch('/prefix-catalog/regions');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogRegionSummary[]>).data;
}

export async function getPrefixCatalogPrefixes(
  regionId: string,
  q = '',
): Promise<PrefixCatalogPrefixRow[]> {
  const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
  const res = await apiFetch(
    `/prefix-catalog/regions/${encodeURIComponent(regionId)}/prefixes${qs}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogPrefixRow[]>).data;
}

export type PrefixCatalogMakerRow = {
  maker: string;
  label: string;
  canon: string;
  prefixes: string[];
  prefix_count: number;
  catalog_code_count: number;
  maker_zh?: string;
  maker_ja?: string;
  maker_en?: string;
};

export async function getPrefixCatalogMakers(
  regionId: string,
  q = '',
): Promise<PrefixCatalogMakerRow[]> {
  const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
  const res = await apiFetch(
    `/prefix-catalog/regions/${encodeURIComponent(regionId)}/makers${qs}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogMakerRow[]>).data;
}

export async function getPrefixCatalogPrefixDetail(
  regionId: string,
  prefix: string,
  opts?: { offset?: number; limit?: number },
): Promise<PrefixCatalogPrefixDetail> {
  const sp = new URLSearchParams();
  if (opts?.offset != null) sp.set('offset', String(opts.offset));
  if (opts?.limit != null) sp.set('limit', String(opts.limit));
  const qs = sp.toString() ? `?${sp}` : '';
  const res = await apiFetch(
    `/prefix-catalog/regions/${encodeURIComponent(regionId)}/prefixes/${encodeURIComponent(prefix)}${qs}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogPrefixDetail>).data;
}

export type PrefixCatalogLocalIndexProgress = {
  stage?: string;
  done?: number | null;
  total?: number | null;
  percent?: number | null;
  label?: string;
  /** 刮削补齐：成功条数（运行中实时） */
  ok?: number | null;
  /** 刮削补齐：失败条数（运行中实时） */
  failed?: number | null;
};

export type CatalogEmbedSkeletonResult = {
  ok?: boolean;
  skipped?: boolean;
  reason?: string;
  error?: string;
  mode?: string;
  inserted?: number;
  skipped_existing?: number;
  purged?: number;
  purged_codes?: number;
  purged_skeletons?: number;
  total?: number;
  pending?: number;
};

export type PrefixCatalogLocalIndexStatus = {
  running: boolean;
  phase: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log: string[];
  result: {
    updated?: number;
    cleared_miss?: number;
    summary?: PrefixCatalogSummary;
    by_region?: Record<
      string,
      { hit: number; codes: number; miss: number }
    >;
    skeleton?: CatalogEmbedSkeletonResult;
  } | null;
  error: string | null;
};

export async function startPrefixCatalogLocalIndex(): Promise<{ started: boolean }> {
  const res = await apiFetch('/prefix-catalog/local-index', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getPrefixCatalogLocalIndexStatus(): Promise<PrefixCatalogLocalIndexStatus> {
  const res = await apiFetch('/prefix-catalog/local-index/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogLocalIndexStatus>).data;
}

export type PrefixCatalogHarvestStatus = {
  running: boolean;
  phase: string;
  log: string[];
  result: {
    region?: string;
    mode?: string;
    checked?: number;
    refreshed?: number;
    miss?: number;
    error?: number;
    makers?: number;
    added?: number;
    summary?: PrefixCatalogSummary;
  } | null;
  error: string | null;
};

export async function getPrefixCatalogHarvestStatus(): Promise<PrefixCatalogHarvestStatus> {
  const res = await apiFetch('/prefix-catalog/harvest/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogHarvestStatus>).data;
}

export type PrefixCatalogStrmSyncSettings = {
  root: string;
  resolved?: string;
  default_root?: string;
  structure?: string;
  hint?: string;
  updated_at?: string | null;
};

export type PrefixCatalogStrmBrowse = {
  base: string;
  path: string;
  resolved: string;
  crumbs: { name: string; path: string }[];
  folders: { name: string; path: string }[];
};

export type PrefixCatalogStrmSyncStatus = {
  running: boolean;
  phase: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log: string[];
  result: {
    root?: string;
    resolved?: string;
    total?: number;
    written?: number;
    skipped?: number;
    deleted?: number;
    pruned_empty?: number;
    errors?: string[];
    by_region?: Record<string, number>;
    skeleton?: CatalogEmbedSkeletonResult;
  } | null;
  error: string | null;
};

export async function getPrefixCatalogStrmSyncSettings(): Promise<PrefixCatalogStrmSyncSettings> {
  const res = await apiFetch('/prefix-catalog/strm-sync');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogStrmSyncSettings>).data;
}

export async function putPrefixCatalogStrmSyncSettings(
  root: string,
): Promise<PrefixCatalogStrmSyncSettings> {
  const res = await apiFetch('/prefix-catalog/strm-sync', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogStrmSyncSettings>).data;
}

export async function browsePrefixCatalogStrmDirs(
  path = '',
): Promise<PrefixCatalogStrmBrowse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : '';
  const res = await apiFetch(`/prefix-catalog/strm-sync/browse${qs}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogStrmBrowse>).data;
}

export async function mkdirPrefixCatalogStrmDir(
  parent: string,
  name: string,
): Promise<PrefixCatalogStrmBrowse> {
  const res = await apiFetch('/prefix-catalog/strm-sync/mkdir', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parent, name }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogStrmBrowse>).data;
}

export async function startPrefixCatalogStrmSync(
  root?: string,
): Promise<{ started: boolean }> {
  const res = await apiFetch('/prefix-catalog/strm-sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root: root || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getPrefixCatalogStrmSyncStatus(): Promise<PrefixCatalogStrmSyncStatus> {
  const res = await apiFetch('/prefix-catalog/strm-sync/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCatalogStrmSyncStatus>).data;
}

