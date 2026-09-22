/**
 * 论坛 / TMDB / 字幕 / 网络设置
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

export type ForumRegionId = 'japan' | 'china' | 'western' | 'mixed' | 'other';

export type SehuatangForumSettings = {
  regionByKey: Record<string, ForumRegionId>;
  updated_at?: string;
};

export async function getSehuatangForumSettings(): Promise<SehuatangForumSettings> {
  const res = await apiFetch('/settings/forum/sehuatang');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<SehuatangForumSettings>).data;
  return {
    regionByKey: (data?.regionByKey || {}) as Record<string, ForumRegionId>,
    updated_at: data?.updated_at,
  };
}

export async function putSehuatangForumSettings(body: {
  regionByKey: Record<string, ForumRegionId>;
}): Promise<SehuatangForumSettings> {
  const res = await apiFetch('/settings/forum/sehuatang', {
    method: 'PUT',
    body: JSON.stringify({ regionByKey: body.regionByKey }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<SehuatangForumSettings>).data;
  return {
    regionByKey: (data?.regionByKey || {}) as Record<string, ForumRegionId>,
    updated_at: data?.updated_at,
  };
}

export type TmdbConfig = {
  configured?: boolean;
  fromEnv?: boolean;
  apiKeyHint?: string;
  apiKey?: string;
  updated_at?: string;
};

export async function getTmdb(): Promise<TmdbConfig> {
  const res = await apiFetch('/settings/tmdb');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<TmdbConfig>).data;
}

export async function putTmdb(body: { apiKey: string }): Promise<TmdbConfig> {
  const res = await apiFetch('/settings/tmdb', {
    method: 'PUT',
    body: JSON.stringify({ apiKey: body.apiKey }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<TmdbConfig>).data;
}

export async function testTmdb(body: {
  apiKey?: string;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/tmdb/test', {
    method: 'POST',
    body: JSON.stringify({ apiKey: body.apiKey || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & { message: string };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export type SubtitleSettings = {
  assrtConfigured?: boolean;
  assrtFromEnv?: boolean;
  assrtTokenHint?: string;
  sources?: string[];
  updated_at?: string;
};

export async function getSubtitleSettings(): Promise<SubtitleSettings> {
  const res = await apiFetch('/settings/subtitle');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<SubtitleSettings>).data;
}

export async function putSubtitleSettings(body: {
  assrtToken: string;
}): Promise<SubtitleSettings> {
  const res = await apiFetch('/settings/subtitle', {
    method: 'PUT',
    body: JSON.stringify({ assrtToken: body.assrtToken }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<SubtitleSettings>).data;
}

export async function testAssrtToken(body: {
  assrtToken?: string;
}): Promise<{ ok: boolean; message: string; quota?: number }> {
  const res = await apiFetch('/settings/subtitle/test-assrt', {
    method: 'POST',
    body: JSON.stringify({ assrtToken: body.assrtToken || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean; quota?: number }> & {
    message: string;
  };
  return {
    ok: Boolean(json.data?.ok),
    message: json.message || '',
    quota: json.data?.quota,
  };
}

export type NetworkConfig = {
  proxyUrl?: string;
  proxyEnabled?: boolean;
  configured?: boolean;
  fromEnv?: boolean;
  effectiveProxyUrl?: string;
  flareSolverrUrl?: string;
  flareSolverrEnabled?: boolean;
  flareSolverrConfigured?: boolean;
  effectiveFlareSolverrUrl?: string;
  updated_at?: string;
};

export async function getNetwork(): Promise<NetworkConfig> {
  const res = await apiFetch('/settings/network');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<NetworkConfig>).data;
}

export async function putNetwork(body: {
  proxyUrl: string;
  proxyEnabled?: boolean;
  flareSolverrUrl?: string;
  flareSolverrEnabled?: boolean;
}): Promise<NetworkConfig> {
  const res = await apiFetch('/settings/network', {
    method: 'PUT',
    body: JSON.stringify({
      proxyUrl: body.proxyUrl,
      proxyEnabled: body.proxyEnabled,
      flareSolverrUrl: body.flareSolverrUrl,
      flareSolverrEnabled: body.flareSolverrEnabled,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<NetworkConfig>).data;
}

export async function testNetwork(body: {
  proxyUrl?: string;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/network/test', {
    method: 'POST',
    body: JSON.stringify({ proxyUrl: body.proxyUrl || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & {
    message: string;
  };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export async function testFlareSolverr(body: {
  flareSolverrUrl?: string;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/network/flare-test', {
    method: 'POST',
    body: JSON.stringify({ flareSolverrUrl: body.flareSolverrUrl || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & {
    message: string;
  };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

