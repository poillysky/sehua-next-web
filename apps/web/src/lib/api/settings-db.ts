/**
 * 资源库 / Bitmagnet 连接与备份、向量任务
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

export async function getResourceDb(): Promise<ResourceDbConfig> {
  const res = await apiFetch('/settings/resource-db');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbConfig>).data;
}

export async function putResourceDb(body: {
  enabled: boolean;
  dsn: string;
  note: string;
}): Promise<ResourceDbConfig> {
  const res = await apiFetch('/settings/resource-db', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbConfig>).data;
}

export async function testResourceDb(dsn: string): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/resource-db/test', {
    method: 'POST',
    body: JSON.stringify({ enabled: true, dsn, note: '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & { message: string };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export type ResourceDbBackupItem = {
  filename: string;
  relPath: string;
  bytes: number;
  mtime: string;
};

export type ResourceDbBackupExportResult = {
  filename: string;
  relPath: string;
  bytes: number;
  elapsedMs: number;
  createdAt: string;
  tables: Array<{ name: string; rows: number; bytes: number; elapsedMs: number }>;
};

export async function listResourceDbBackups(): Promise<ResourceDbBackupItem[]> {
  const res = await apiFetch('/settings/resource-db/backups');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ items: ResourceDbBackupItem[] }>).data;
  return data?.items || [];
}

export async function exportResourceDbBackup(): Promise<ResourceDbBackupExportResult> {
  const res = await apiFetch('/settings/resource-db/backups/export', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbBackupExportResult>).data;
}

export async function importResourceDbBackup(
  filename: string,
): Promise<{ filename: string; elapsedMs: number; tables: Array<{ name: string; rows: number }> }> {
  const res = await apiFetch('/settings/resource-db/backups/import', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      filename: string;
      elapsedMs: number;
      tables: Array<{ name: string; rows: number }>;
    }>
  ).data;
}

export async function uploadImportResourceDbBackup(
  file: File,
): Promise<{
  filename: string;
  bytes: number;
  elapsedMs: number;
  tables: Array<{ name: string; rows: number }>;
}> {
  const body = new FormData();
  body.append('file', file);
  const res = await apiFetch('/settings/resource-db/backups/upload-import', {
    method: 'POST',
    body,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      filename: string;
      bytes: number;
      elapsedMs: number;
      tables: Array<{ name: string; rows: number }>;
    }>
  ).data;
}

export type ResourceDbEmbedStats = {
  ok?: boolean;
  resources?: number;
  embedded?: number;
  pending?: number;
  hasHnsw?: boolean;
  indexes?: string[];
  model?: string;
  dim?: number;
  error?: string;
  vectorExt?: string;
};

export type ResourceDbEmbedJobStatus = {
  running: boolean;
  phase?: string;
  progress?: {
    stage?: string;
    done?: number;
    total?: number | null;
    percent?: number | null;
    label?: string;
  } | null;
  log?: string[];
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export async function getResourceDbEmbedStats(): Promise<ResourceDbEmbedStats> {
  const res = await apiFetch('/settings/resource-db/embed/stats');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbEmbedStats>).data;
}

export async function getResourceDbEmbedStatus(): Promise<ResourceDbEmbedJobStatus> {
  const res = await apiFetch('/settings/resource-db/embed/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbEmbedJobStatus>).data;
}

export async function startResourceDbEmbed(body?: {
  force?: boolean;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/settings/resource-db/embed/start', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function stopResourceDbEmbed(): Promise<{ ok?: boolean; pausing?: boolean }> {
  const res = await apiFetch('/settings/resource-db/embed/stop', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ ok?: boolean; pausing?: boolean }>).data;
}

export async function createResourceDbEmbedIndex(): Promise<{ ok?: boolean; index?: string }> {
  const res = await apiFetch('/settings/resource-db/embed/create-index', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ ok?: boolean; index?: string }>).data;
}

export async function listBitmagnetDbBackups(): Promise<ResourceDbBackupItem[]> {
  const res = await apiFetch('/settings/bitmagnet-db/backups');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ items: ResourceDbBackupItem[] }>).data;
  return data?.items || [];
}

export async function exportBitmagnetDbBackup(): Promise<ResourceDbBackupExportResult> {
  const res = await apiFetch('/settings/bitmagnet-db/backups/export', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbBackupExportResult>).data;
}

export async function importBitmagnetDbBackup(
  filename: string,
): Promise<{ filename: string; elapsedMs: number; tables: Array<{ name: string; rows: number }> }> {
  const res = await apiFetch('/settings/bitmagnet-db/backups/import', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      filename: string;
      elapsedMs: number;
      tables: Array<{ name: string; rows: number }>;
    }>
  ).data;
}

export async function uploadImportBitmagnetDbBackup(
  file: File,
): Promise<{
  filename: string;
  bytes: number;
  elapsedMs: number;
  tables: Array<{ name: string; rows: number }>;
}> {
  const body = new FormData();
  body.append('file', file);
  const res = await apiFetch('/settings/bitmagnet-db/backups/upload-import', {
    method: 'POST',
    body,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      filename: string;
      bytes: number;
      elapsedMs: number;
      tables: Array<{ name: string; rows: number }>;
    }>
  ).data;
}

export async function getBitmagnetDbEmbedStats(): Promise<ResourceDbEmbedStats> {
  const res = await apiFetch('/settings/bitmagnet-db/embed/stats');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbEmbedStats>).data;
}

export async function getBitmagnetDbEmbedStatus(): Promise<ResourceDbEmbedJobStatus> {
  const res = await apiFetch('/settings/bitmagnet-db/embed/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ResourceDbEmbedJobStatus>).data;
}

export async function startBitmagnetDbEmbed(body?: {
  force?: boolean;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/settings/bitmagnet-db/embed/start', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function stopBitmagnetDbEmbed(): Promise<{ ok?: boolean; pausing?: boolean }> {
  const res = await apiFetch('/settings/bitmagnet-db/embed/stop', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ ok?: boolean; pausing?: boolean }>).data;
}

export async function createBitmagnetDbEmbedIndex(): Promise<{
  ok?: boolean;
  index?: string;
}> {
  const res = await apiFetch('/settings/bitmagnet-db/embed/create-index', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ ok?: boolean; index?: string }>).data;
}

export type BitmagnetDbConfig = ResourceDbConfig;

export async function getBitmagnetDb(): Promise<BitmagnetDbConfig> {
  const res = await apiFetch('/settings/bitmagnet-db');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<BitmagnetDbConfig>).data;
}

export async function putBitmagnetDb(body: {
  enabled: boolean;
  dsn: string;
  note: string;
}): Promise<BitmagnetDbConfig> {
  const res = await apiFetch('/settings/bitmagnet-db', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<BitmagnetDbConfig>).data;
}

export async function testBitmagnetDb(
  dsn: string,
): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/bitmagnet-db/test', {
    method: 'POST',
    body: JSON.stringify({ enabled: true, dsn, note: '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & { message: string };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

/* —— Settings: TMDB / 115 / forum —— */

