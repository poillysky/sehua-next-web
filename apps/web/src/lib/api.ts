/**
 * 精简 API 客户端 — 对接 apps/api（色花同协议），非整包复制 sehua 前端。
 */
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

export const API_BASE =
  typeof window === 'undefined'
    ? (process.env.API_INTERNAL_BASE || 'http://127.0.0.1:8020').replace(/\/$/, '')
    : (process.env.NEXT_PUBLIC_API_BASE || '/api').replace(/\/$/, '');

type Envelope<T> = { data: T; message: string; status: number };

async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as {
      detail?: string | Array<{ msg?: string; loc?: unknown[] }>;
    };
    if (typeof j.detail === 'string') return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]) {
      const first = j.detail[0];
      const msg = String(first.msg || '').trim();
      if (/field required/i.test(msg)) {
        const loc = Array.isArray(first.loc) ? first.loc : [];
        const field = String(loc[loc.length - 1] || '').trim();
        if (field === 'apiKey' || field === 'api_key') return '请填写 API Key';
        return field ? `请填写 ${field}` : '请填写必填项';
      }
      if (msg) return msg;
    }
  } catch {
    /* ignore */
  }
  return `请求失败 ${res.status}`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const isForm =
    typeof FormData !== 'undefined' && init.body instanceof FormData;
  if (init.body && !headers.has('Content-Type') && !isForm) {
    headers.set('Content-Type', 'application/json');
  }
  if (isForm && headers.has('Content-Type')) {
    headers.delete('Content-Type');
  }
  return fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' });
}

export async function authMe(): Promise<AuthUser | null> {
  const res = await apiFetch('/auth/me');
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AuthUser>).data;
}

export async function authLogin(username: string, password: string): Promise<AuthUser> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AuthUser>).data;
}

export async function authRegister(username: string, password: string): Promise<AuthUser> {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AuthUser>).data;
}

export async function authLogout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' });
}

export async function authChangePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await apiFetch('/auth/password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function listUsers(): Promise<AuthUser[]> {
  const res = await apiFetch('/auth/users');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AuthUser[]>).data;
}

export async function adminCreateUser(
  username: string,
  password: string,
): Promise<AuthUser> {
  const res = await apiFetch('/auth/users', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AuthUser>).data;
}

export async function adminDeleteUser(userId: number): Promise<void> {
  const res = await apiFetch(`/auth/users/${userId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function adminResetUserPassword(
  userId: number,
  newPassword: string,
): Promise<void> {
  const res = await apiFetch(`/auth/users/${userId}/password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

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

export type MagnetFile = {
  index: number;
  path: string;
  size: number;
  extension?: string;
};

export type MagnetHit = {
  title: string;
  path: string;
  hash?: string;
  name?: string;
  infoHash?: string;
  detailUrl?: string;
  size?: number;
  sizeText?: string;
  fileCount?: number | null;
  files_count?: number | null;
  files?: MagnetFile[] | null;
  single_file?: boolean;
  seeders?: number | null;
  leechers?: number | null;
  created_at?: number;
  createdAt?: string;
  magnet?: string | null;
  magnet_uri?: string | null;
  magnets?: string[] | null;
};

export type MagnetSearchResult = {
  keyword: string;
  keywords?: string[];
  page?: number;
  source: string;
  baseUrl?: string;
  openUrl?: string;
  items: MagnetHit[];
  total: number;
  hasMore?: boolean;
  costMs?: number;
};

export async function fetchMagnetSearch(opts: {
  keyword: string;
  page?: number;
  sortType?: string;
  filterTime?: string;
  filterSize?: string;
  signal?: AbortSignal;
}): Promise<MagnetSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  q.set('page', String(opts.page ?? 1));
  if (opts.sortType) q.set('sortType', opts.sortType);
  if (opts.filterTime) q.set('filterTime', opts.filterTime);
  if (opts.filterSize) q.set('filterSize', opts.filterSize);
  const res = await apiFetch(`/magnet/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetSearchResult>).data;
}

export type PansouLink = {
  type: string;
  url: string;
  password?: string;
  workTitle?: string;
  label?: string;
};

export type PansouHit = {
  id: string;
  title: string;
  content?: string;
  channel?: string;
  datetime?: string;
  tags?: string[];
  links: PansouLink[];
};

export type PansouSearchResult = {
  keyword: string;
  source: string;
  baseUrl?: string;
  host?: string;
  total: number;
  items: PansouHit[];
};

export async function fetchPansouSearch(opts: {
  keyword: string;
  refresh?: boolean;
  src?: 'all' | 'tg' | 'plugin';
  signal?: AbortSignal;
}): Promise<PansouSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  if (opts.refresh) q.set('refresh', 'true');
  if (opts.src) q.set('src', opts.src);
  const res = await apiFetch(`/pansou/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSearchResult>).data;
}

export async function fetchCloudSaverSearch(opts: {
  keyword: string;
  signal?: AbortSignal;
}): Promise<PansouSearchResult> {
  const q = new URLSearchParams();
  q.set('keyword', opts.keyword);
  const res = await apiFetch(`/cloudsaver/search?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSearchResult>).data;
}

export type PansouSettings = {
  enabled: boolean;
  baseUrl: string;
  timeoutSec: number;
  note?: string;
};

export async function getPansouSettings(): Promise<PansouSettings> {
  const res = await apiFetch('/settings/pansou');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSettings>).data;
}

export async function putPansouSettings(body: {
  enabled: boolean;
  baseUrl: string;
  timeoutSec?: number;
  note?: string;
}): Promise<PansouSettings> {
  const res = await apiFetch('/settings/pansou', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PansouSettings>).data;
}

export async function testPansou(): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/pansou/health');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ ok?: boolean; message?: string }>).data;
  return {
    ok: Boolean(data?.ok),
    message: data?.message || (data?.ok ? '连接成功' : '连接失败'),
  };
}

export type CloudSaverSettings = {
  enabled: boolean;
  baseUrl: string;
  username: string;
  hasPassword?: boolean;
  timeoutSec: number;
  note?: string;
};

export async function getCloudSaverSettings(): Promise<CloudSaverSettings> {
  const res = await apiFetch('/settings/cloudsaver');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<CloudSaverSettings>).data;
}

export async function putCloudSaverSettings(body: {
  enabled: boolean;
  baseUrl: string;
  username: string;
  password?: string;
  timeoutSec?: number;
  note?: string;
}): Promise<CloudSaverSettings> {
  const res = await apiFetch('/settings/cloudsaver', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<CloudSaverSettings>).data;
}

export async function testCloudSaver(): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/cloudsaver/health');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<{ ok?: boolean; message?: string }>).data;
  return {
    ok: Boolean(data?.ok),
    message: data?.message || (data?.ok ? '登录成功' : '登录失败'),
  };
}

export async function fetchMagnetDetail(
  hash: string,
  signal?: AbortSignal,
): Promise<MagnetHit> {
  const q = new URLSearchParams();
  q.set('hash', hash);
  const res = await apiFetch(`/magnet/detail?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetHit>).data;
}

export type MagnetPreviewShot = {
  time?: number | null;
  screenshot: string;
};

export type MagnetPreview = {
  hash: string;
  name?: string;
  file_type?: string;
  size?: number;
  count?: number;
  screenshots: MagnetPreviewShot[];
  error?: string;
};

export async function fetchMagnetPreview(
  hash: string,
  signal?: AbortSignal,
): Promise<MagnetPreview> {
  const q = new URLSearchParams();
  q.set('hash', hash);
  const res = await apiFetch(`/magnet/preview?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MagnetPreview>).data;
}

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

export type AiSamplingConfig = {
  temperature?: number | null;
  topP?: number | null;
  maxTokens?: number | null;
  maxContext?: number | null;
  frequencyPenalty?: number | null;
  presencePenalty?: number | null;
  topK?: number | null;
  minP?: number | null;
  repetitionPenalty?: number | null;
  seed?: number | null;
  n?: number | null;
  streamOpenai?: boolean | null;
  maxContextUnlocked?: boolean | null;
  continuePrefill?: boolean | null;
  squashSystemMessages?: boolean | null;
  showThoughts?: boolean | null;
};

export type AiLlmConfig = {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
  configured?: boolean;
  fromEnv?: boolean;
  fromEnvKey?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiEmbedDevice = 'cpu' | 'cuda' | 'directml';

export type AiEmbedDeviceOption = {
  value: AiEmbedDevice | string;
  label: string;
  hint?: string;
  available?: boolean;
};

export type AiEmbedConfig = {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  devices?: AiEmbedDeviceOption[];
  topK?: number;
  minScore?: number;
  chunkSize?: number;
  configured?: boolean;
  fromEnv?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiPresetOption = { value: string; label: string; baseUrl?: string; dim?: string };

export type AiPresets = {
  chatSources: AiPresetOption[];
  localEmbedModels: AiPresetOption[];
  localEmbedDevices?: AiEmbedDeviceOption[];
  openaiEmbedModels: AiPresetOption[];
  promptPostProcessing: AiPresetOption[];
  webSearchProviders?: AiPresetOption[];
};

export async function getAiPresets(): Promise<AiPresets> {
  const res = await apiFetch('/settings/ai/presets');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiPresets>).data;
}

export async function getAiLlm(): Promise<AiLlmConfig> {
  const res = await apiFetch('/settings/ai/llm');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiLlmConfig>).data;
}

export async function putAiLlm(body: {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
}): Promise<AiLlmConfig> {
  const res = await apiFetch('/settings/ai/llm', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiLlmConfig>).data;
}

export async function connectAiLlm(body: {
  baseUrl?: string;
  apiKey?: string;
  customIncludeHeaders?: string;
  listModels?: boolean;
}): Promise<{ ok: boolean; models: string[]; modelCount: number; message: string }> {
  const res = await apiFetch('/settings/ai/llm/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok: boolean;
    models?: string[];
    modelCount?: number;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    models: json.data?.models || [],
    modelCount: json.data?.modelCount ?? 0,
    message: json.message || '',
  };
}

export async function testAiLlm(body: {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/ai/llm/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & { message: string };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export async function getAiEmbed(): Promise<AiEmbedConfig> {
  const res = await apiFetch('/settings/ai/embed');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiEmbedConfig>).data;
}

export async function putAiEmbed(body: {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  topK?: number;
  minScore?: number;
  chunkSize?: number;
}): Promise<AiEmbedConfig> {
  const res = await apiFetch('/settings/ai/embed', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiEmbedConfig>).data;
}

export async function connectAiEmbed(body: {
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  apiKey?: string;
  listModels?: boolean;
}): Promise<{
  ok: boolean;
  models: string[];
  modelCount: number;
  totalModelCount?: number;
  embedMatchCount?: number;
  devices?: AiEmbedDeviceOption[];
  device?: string;
  message: string;
}> {
  const res = await apiFetch('/settings/ai/embed/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok: boolean;
    models?: string[];
    modelCount?: number;
    totalModelCount?: number;
    embedMatchCount?: number;
    devices?: AiEmbedDeviceOption[];
    device?: string;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    models: json.data?.models || [],
    modelCount: json.data?.modelCount ?? 0,
    totalModelCount: json.data?.totalModelCount,
    embedMatchCount: json.data?.embedMatchCount,
    devices: json.data?.devices,
    device: json.data?.device,
    message: json.message || '',
  };
}

export async function testAiEmbed(body: {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  topK?: number;
  minScore?: number;
  chunkSize?: number;
}): Promise<{ ok: boolean; message: string; dim?: number }> {
  const res = await apiFetch('/settings/ai/embed/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean; dim?: number }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    message: json.message || '',
    dim: typeof json.data?.dim === 'number' ? json.data.dim : undefined,
  };
}

export async function downloadAiEmbed(body: {
  provider?: 'local' | 'openai';
  model?: string;
  device?: AiEmbedDevice | string;
  dim?: number;
}): Promise<{
  ok: boolean;
  skipped?: boolean;
  downloaded?: boolean;
  model?: string;
  message: string;
}> {
  const res = await apiFetch('/settings/ai/embed/download', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok?: boolean;
    skipped?: boolean;
    downloaded?: boolean;
    model?: string;
    message?: string;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok ?? true),
    skipped: json.data?.skipped,
    downloaded: json.data?.downloaded,
    model: json.data?.model,
    message: json.message || json.data?.message || '',
  };
}

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

export type ScrapActressOptimizeJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    unchanged?: number;
    updated?: number;
    reembedded?: number;
    maps?: { count?: number; lang?: string };
  } | null;
  error?: string | null;
};

export async function startScrapActressOptimize(body?: {
  reembed?: boolean;
  force?: boolean;
  limit?: number;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/actress-optimize/start', {
    method: 'POST',
    body: JSON.stringify({
      reembed: body?.reembed !== false,
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getScrapActressOptimizeStatus(): Promise<ScrapActressOptimizeJobStatus> {
  const res = await apiFetch('/scrap-library/embed/actress-optimize/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressOptimizeJobStatus>).data;
}

export type ScrapNfoOptimizeJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    updated?: number;
    unchanged?: number;
    errors?: number;
    maps?: { count?: number; lang?: string };
    samples?: string[];
  } | null;
  error?: string | null;
};

export async function startScrapNfoOptimize(body?: {
  force?: boolean;
  limit?: number;
}): Promise<{ started: boolean; resumed?: boolean }> {
  const res = await apiFetch('/scrap-library/embed/nfo-optimize/start', {
    method: 'POST',
    body: JSON.stringify({
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean; resumed?: boolean }>)
    .data;
}

export async function getScrapNfoOptimizeStatus(): Promise<ScrapNfoOptimizeJobStatus> {
  const res = await apiFetch('/scrap-library/embed/nfo-optimize/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapNfoOptimizeJobStatus>).data;
}

export type ScrapActressAvatarJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  result?: {
    ok?: boolean;
    total?: number;
    downloaded?: number;
    downloadedGfriends?: number;
    downloadedJavbus?: number;
    skipped?: number;
    missed?: number;
    failed?: number;
    missSamples?: string[];
    polish?: {
      total?: number;
      updated?: number;
      unchanged?: number;
      reembedded?: number;
    };
  } | null;
  error?: string | null;
};

export async function startScrapActressAvatar(body?: {
  force?: boolean;
  limit?: number;
  region?: string;
  polishMeta?: boolean;
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/actress-avatar/start', {
    method: 'POST',
    body: JSON.stringify({
      force: Boolean(body?.force),
      limit: body?.limit ?? 0,
      region: body?.region || '',
      polishMeta: body?.polishMeta !== false,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

export async function getScrapActressAvatarStatus(): Promise<ScrapActressAvatarJobStatus> {
  const res = await apiFetch('/scrap-library/embed/actress-avatar/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressAvatarJobStatus>).data;
}

/** 批量解析女优本地头像 API 路径（无头像则不出现在结果中） */
export type ScrapActressProfile = {
  name: string;
  queryName?: string;
  aliases?: string[];
  count?: number;
  posterApi?: string;
  url?: string;
  javdb?: string;
  birthday?: string;
  age?: number | null;
  height?: number | null;
  bust?: number | null;
  waist?: number | null;
  hip?: number | null;
  cup?: string;
  birthplace?: string;
  careerPeriod?: string;
  debutWork?: string;
  bioSource?: string;
  bioSourceUrl?: string;
};

export async function getScrapActressProfile(opts: {
  name: string;
  region?: string;
  refresh?: boolean;
}): Promise<ScrapActressProfile> {
  const q = new URLSearchParams();
  q.set('name', opts.name);
  if (opts.region) q.set('region', opts.region);
  if (opts.refresh) q.set('refresh', '1');
  const res = await apiFetch(
    `/scrap-library/embed/actress-profile?${q.toString()}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapActressProfile>).data;
}

export async function lookupScrapActressAvatarUrls(
  names: string[],
): Promise<Record<string, string>> {
  const cleaned = [
    ...new Set(
      names.map((n) => String(n || '').trim()).filter(Boolean),
    ),
  ];
  if (!cleaned.length) return {};
  const q = new URLSearchParams();
  for (const n of cleaned) q.append('names', n);
  const res = await apiFetch(
    `/scrap-library/embed/actress-avatar/urls?${q.toString()}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<Record<string, string>>
  ).data;
}

/** 与后端 `_safe_filename` 对齐的乐观头像 API（免等 urls 查询）。 */
export function actressAvatarPosterApiGuess(name: string): string {
  let s = String(name || '')
    .normalize('NFKC')
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^[ .]+|[ .]+$/g, '');
  if (!s) return '';
  if (s.length > 96) s = s.slice(0, 96);
  const rel = `scrap-library/_actress/${s}.jpg`;
  return `/scrap-library/file?path=${encodeURIComponent(rel)}`;
}

/** 会话级头像路径缓存：命中则进详情首帧即可出图。 */
const _actressAvatarApiCache = new Map<string, string>();

export function peekActressAvatarPosterApi(name: string): string {
  const n = String(name || '').trim();
  if (!n) return '';
  return _actressAvatarApiCache.get(n) || actressAvatarPosterApiGuess(n);
}

export function rememberActressAvatarPosterApis(
  map: Record<string, string>,
): void {
  for (const [k, v] of Object.entries(map || {})) {
    const name = String(k || '').trim();
    const api = String(v || '').trim();
    if (name && api) _actressAvatarApiCache.set(name, api);
  }
}

export type ScrapLibraryQualityStats = {
  region?: string | null;
  total?: number;
  incomplete?: number;
  /** 向量库内已有条目（不含空壳） */
  embedTotal?: number;
  /** 片商目录有、尚未进向量库的空壳 */
  shells?: number;
  counts?: {
    no_local?: number;
    no_media?: number;
    no_actress?: number;
    no_studio?: number;
    no_plot?: number;
    thin_title?: number;
  };
};

export type ScrapLibraryQualityItem = {
  itemId?: string;
  region?: string;
  prefix?: string;
  code?: string;
  title?: string;
  relPath?: string;
  gaps?: string[];
};

export type ScrapLibraryEnrichFieldRow = {
  id?: string;
  label?: string;
  ok?: boolean;
  value?: string;
  /** 该字段最终选用的站点 id */
  source?: string;
};

export type ScrapLibraryEnrichSourceTiming = {
  id?: string;
  access?: string;
  ms?: number;
  /** 等出站槽毫秒（后端第十一轮起）：「排队」与「真在干活」的耗时分开看 */
  waitMs?: number;
  /** hit / miss / down / busy / cancelled —— busy = 我们没轮到，不是源故障 */
  kind?: string;
  ok?: boolean;
  error?: string;
  actors?: number;
  poster?: boolean;
  status?: 'pending' | 'done' | 'fail' | 'skipped' | string;
};

export type ScrapLibraryEnrichQueueItem = {
  logId?: number;
  index?: number;
  itemId?: string;
  code?: string;
  gaps?: string[];
  gapsAfter?: string[];
  status?: 'pending' | 'running' | 'done' | 'fail' | string;
  error?: string;
  source?: string;
  fetchMs?: number;
  coverMs?: number;
  actressMs?: number;
  vectorMs?: number;
  totalMs?: number;
  detailTitle?: string;
  actors?: number;
  nfoChanged?: boolean;
  posterDownloaded?: boolean;
  vectorSynced?: boolean;
  vectorSkipped?: boolean;
  vectorError?: string;
  /** 软成功：封面+标题已齐，仍缺剧情/女优等 */
  partialOk?: boolean;
  relPath?: string;
  rel_path?: string;
  sourceTimings?: ScrapLibraryEnrichSourceTiming[];
  fields?: ScrapLibraryEnrichFieldRow[];
  wouldFill?: Record<string, boolean | number>;
  /** 处理中卡顿原因（来自 monitor） */
  stallLabel?: string;
};

export type EnrichMonitorStall = {
  kind?: string;
  label?: string;
  detail?: string;
  sinceMs?: number;
};

export type EnrichMonitorInflight = {
  code?: string;
  itemId?: string;
  region?: string;
  phase?: string;
  phaseLabel?: string;
  elapsedMs?: number;
  phaseElapsedMs?: number;
  sources?: Array<{
    id?: string;
    status?: string;
    ms?: number;
    ok?: boolean;
    error?: string;
  }>;
  stall?: EnrichMonitorStall | null;
};

export type EnrichMonitorRecentStall = {
  code?: string;
  itemId?: string;
  ok?: boolean;
  elapsedMs?: number;
  phase?: string;
  stall?: EnrichMonitorStall | null;
  error?: string;
};

export type EnrichMonitorSnapshot = {
  enabled?: boolean;
  itemWorkers?: number;
  perSourceTimeoutSec?: number;
  region?: string;
  inflight?: EnrichMonitorInflight[];
  recentStalls?: EnrichMonitorRecentStall[];
  summary?: {
    inflightN?: number;
    stallingN?: number;
    stallKinds?: Record<string, number>;
    avgFetchMs?: number;
  };
};

export type ScrapLibraryEnrichCurrent = {
  code?: string;
  itemId?: string;
  gaps?: string[];
  status?: string;
  index?: number;
  total?: number;
  ok?: boolean;
  error?: string;
  source?: string;
  detailTitle?: string;
  fetchMs?: number;
  coverMs?: number;
  actressMs?: number;
  vectorMs?: number;
  totalMs?: number;
  actors?: number;
  nfoChanged?: boolean;
  posterDownloaded?: boolean;
  vectorSynced?: boolean;
  vectorSkipped?: boolean;
  vectorError?: string;
  relPath?: string;
  sourceTimings?: ScrapLibraryEnrichSourceTiming[];
  fields?: ScrapLibraryEnrichFieldRow[];
  wouldFill?: Record<string, boolean | number>;
};

export type ScrapLibraryEnrichCheckpoint = {
  region?: string;
  mode?: string;
  dryRun?: boolean;
  done?: number;
  remaining?: number;
  total?: number;
  ok?: number;
  failed?: number;
};

export type ScrapLibraryEnrichJobStatus = {
  running: boolean;
  phase?: string;
  progress?: PrefixCatalogLocalIndexProgress | null;
  log?: string[];
  regionLogs?: Record<string, string[]>;
  /** 各分区本轮/内存日志条数（可大于 regionLogs 回传长度） */
  regionLogCounts?: Record<string, number>;
  currentRegion?: string;
  cancel?: boolean;
  halt?: 'pause' | 'stop' | string | null;
  paused?: boolean;
  checkpoints?: Record<string, ScrapLibraryEnrichCheckpoint>;
  /** 库内总量/未完成（进度条用，避免队列表样例把进度撑高） */
  library?: Record<
    string,
    {
      total?: number;
      incomplete?: number;
      complete?: number;
      percent?: number;
    }
  >;
  queue?: ScrapLibraryEnrichQueueItem[];
  queueTotal?: number;
  queueCounts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  /** 全局 queueCounts 对应的分区（防串区） */
  queueCountsRegion?: string;
  /** 各分区独立角标 */
  regionQueueCounts?: Record<
    string,
    {
      pending?: number;
      running?: number;
      done?: number;
      soft?: number;
      fail?: number;
    }
  >;
  current?: ScrapLibraryEnrichCurrent | null;
  /** 清空·扫描进行中的磁盘分类进度（SSE 边扫边看） */
  queueScan?: {
    active?: boolean;
    region?: string;
    stage?: string;
    label?: string;
    scanned?: number;
    total?: number;
    done?: number;
    soft?: number;
    fail?: number;
    /** 边扫边看：成功样例 */
    samplesDone?: ScrapLibraryEnrichQueueItem[];
    /** 边扫边看：软成功样例 */
    samplesSoft?: ScrapLibraryEnrichQueueItem[];
    /** 边扫边看：失败样例 */
    samplesFail?: ScrapLibraryEnrichQueueItem[];
  } | null;
  result?: {
    dryRun?: boolean;
    region?: string;
    regions?: string[];
    kinds?: string[];
    /** ⚠️ 增量模式下是**库内待处理预估**（十万级），不要当本轮总量用来显示 */
    queued?: number;
    /** 本轮实际处理条数（= ok + failed）；显示「成功 x/y」请用它 */
    processed?: number;
    ok?: number;
    failed?: number;
    cancelled?: boolean;
    paused?: boolean;
    sources?: string[];
    items?: Array<{
      code?: string;
      ok?: boolean;
      error?: string;
      dryRun?: boolean;
      detailTitle?: string;
    }>;
  } | null;
  error?: string | null;
  monitor?: EnrichMonitorSnapshot;
};

export async function getScrapLibraryQuality(
  region = 'japan_censored',
): Promise<ScrapLibraryQualityStats> {
  const q = new URLSearchParams();
  if (region) q.set('region', region);
  const res = await apiFetch(
    `/scrap-library/embed/quality${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryQualityStats>).data;
}

export async function getScrapLibraryQualityItems(opts?: {
  region?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}): Promise<{ items: ScrapLibraryQualityItem[]; kind?: string; region?: string }> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.kind) q.set('kind', opts.kind);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  const res = await apiFetch(
    `/scrap-library/embed/quality/items${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      items: ScrapLibraryQualityItem[];
      kind?: string;
      region?: string;
    }>
  ).data;
}

export type ScrapLibraryQualityGate = {
  ok: boolean;
  code?: string;
  hardFail?: string[];
  soft?: string[];
  info?: {
    code?: string;
    badges?: string[];
    actorsN?: number;
    poster?: {
      width?: number;
      height?: number;
      issues?: string[];
    };
    hasTitleJa?: boolean;
    [k: string]: unknown;
  };
};

export async function getScrapLibraryQualityGate(opts?: {
  itemId?: string;
  code?: string;
  relPath?: string;
}): Promise<ScrapLibraryQualityGate> {
  const q = new URLSearchParams();
  if (opts?.itemId) q.set('itemId', opts.itemId);
  if (opts?.code) q.set('code', opts.code);
  if (opts?.relPath) q.set('relPath', opts.relPath);
  const res = await apiFetch(
    `/scrap-library/embed/quality/gate${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryQualityGate>).data;
}

export async function startScrapLibraryEnrich(body?: {
  region?: string;
  regions?: string[];
  kinds?: string[];
  limit?: number;
  dryRun?: boolean;
  mode?: 'incremental' | 'refresh_weak' | 'overwrite';
}): Promise<{ started: boolean }> {
  const res = await apiFetch('/scrap-library/embed/enrich', {
    method: 'POST',
    body: JSON.stringify({
      region: body?.region ?? '',
      regions: body?.regions ?? [],
      // 空数组走服务端默认：完整元数据 + 封面
      kinds: body?.kinds ?? [
        'no_local',
        'no_media',
        'no_actress',
        'no_studio',
        'no_plot',
        'thin_title',
      ],
      limit: body?.limit ?? 0,
      dryRun: Boolean(body?.dryRun),
      mode:
        body?.mode === 'overwrite'
          ? 'overwrite'
          : body?.mode === 'refresh_weak'
            ? 'refresh_weak'
            : 'incremental',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{ started: boolean }>).data;
}

/** 详情页：清空该条向量后全量重刮并覆盖 NFO/向量。
 *  syncVector=false：只写本地 NFO/封面（设置页分区刮削重刮），不清空向量。
 */
export async function enrichScrapLibraryItem(opts: {
  itemId: string;
  dryRun?: boolean;
  overwrite?: boolean;
  syncVector?: boolean;
}): Promise<{
  ok: boolean;
  dryRun?: boolean;
  overwrite?: boolean;
  gaps?: string[];
  result?: {
    ok?: boolean;
    error?: string;
    code?: string;
    nfoChanged?: boolean;
    posterDownloaded?: boolean;
    source?: string;
    actors?: number;
    fetchMs?: number;
    coverMs?: number;
    actressMs?: number;
    vectorMs?: number;
    totalMs?: number;
    vectorSkipped?: boolean;
    partialOk?: boolean;
    gapsAfter?: string[];
    fields?: ScrapLibraryEnrichFieldRow[];
    sourceTimings?: Array<{
      id?: string;
      access?: string;
      ms?: number;
      ok?: boolean;
      error?: string;
      actors?: number;
      poster?: boolean;
    }>;
  };
  item?: ScrapLibraryEmbedItem | null;
}> {
  const itemId = String(opts.itemId || '').trim();
  if (!itemId) throw new Error('缺少条目 ID');
  const res = await apiFetch('/scrap-library/embed/enrich/one', {
    method: 'POST',
    body: JSON.stringify({
      itemId,
      dryRun: Boolean(opts.dryRun),
      overwrite: opts.overwrite !== false,
      syncVector: opts.syncVector !== false,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok: boolean;
      dryRun?: boolean;
      gaps?: string[];
      result?: {
        ok?: boolean;
        error?: string;
        code?: string;
        nfoChanged?: boolean;
        posterDownloaded?: boolean;
        source?: string;
        actors?: number;
        fetchMs?: number;
        coverMs?: number;
        actressMs?: number;
        vectorMs?: number;
        totalMs?: number;
        vectorSkipped?: boolean;
        partialOk?: boolean;
        gapsAfter?: string[];
        fields?: ScrapLibraryEnrichFieldRow[];
        sourceTimings?: Array<{
          id?: string;
          access?: string;
          ms?: number;
          ok?: boolean;
          error?: string;
          actors?: number;
          poster?: boolean;
        }>;
      };
      item?: ScrapLibraryEmbedItem | null;
    }>
  ).data;
}

export async function getScrapLibraryEnrichStatus(opts?: {
  lite?: boolean;
}): Promise<ScrapLibraryEnrichJobStatus> {
  const q = new URLSearchParams();
  if (opts?.lite) q.set('lite', '1');
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(`/scrap-library/embed/enrich/status${suffix}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapLibraryEnrichJobStatus>).data;
}

/** SSE：服务端状态变更时推送，替代 450ms 轮询。 */
export async function subscribeScrapLibraryEnrichStatus(
  onStatus: (data: ScrapLibraryEnrichJobStatus) => void,
  opts?: {
    signal?: AbortSignal;
    onError?: (message: string) => void;
    /** 总览角标：不含 queue，帧更小、更不易卡设置页 */
    lite?: boolean;
  },
): Promise<void> {
  const signal = opts?.signal;
  const abortError = () => {
    const err = new DOMException('Aborted', 'AbortError');
    throw err;
  };
  if (signal?.aborted) abortError();

  const q = new URLSearchParams();
  if (opts?.lite) q.set('lite', '1');
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(`/scrap-library/embed/enrich/status/stream${suffix}`, {
    signal,
  });
  if (signal?.aborted) abortError();
  if (!res.ok) throw new Error(await parseError(res));
  if (!res.body) throw new Error('无流式响应');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const onAbort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      if (signal?.aborted) abortError();
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';
      for (const chunk of chunks) {
        const line = chunk
          .split('\n')
          .map((l) => l.trim())
          .find((l) => l.startsWith('data:'));
        if (!line) continue;
        const raw = line.replace(/^data:\s*/, '');
        try {
          const evt = JSON.parse(raw) as {
            event?: string;
            data?: ScrapLibraryEnrichJobStatus;
          };
          if (evt.event === 'status' && evt.data) {
            onStatus(evt.data);
          } else if (evt.event === 'error') {
            const msg = String(
              (evt.data as { message?: string } | undefined)?.message || '推送失败',
            );
            opts?.onError?.(msg);
          }
        } catch {
          /* ignore bad chunk */
        }
      }
    }
  } catch (e) {
    if (signal?.aborted) abortError();
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    if (e instanceof Error && e.name === 'AbortError') throw e;
    const msg = e instanceof Error ? e.message : '推送中断';
    opts?.onError?.(msg);
    throw e;
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }
}

export async function getScrapLibraryEnrichLogs(opts?: {
  region?: string;
  limit?: number;
}): Promise<{ region?: string | null; log: string[] }> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(
    `/scrap-library/embed/enrich/logs${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{ region?: string | null; log: string[] }>
  ).data;
}

export async function getScrapLibraryEnrichQueueLog(opts?: {
  region?: string;
  status?: string;
  code?: string;
  limit?: number;
  offset?: number;
}): Promise<{
  region?: string | null;
  code?: string | null;
  counts: {
    pending: number;
    running: number;
    done: number;
    soft?: number;
    fail: number;
  };
  items: ScrapLibraryEnrichQueueItem[];
  total?: number;
  limit?: number;
  offset?: number;
}> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.status) q.set('status', opts.status);
  if (opts?.code) q.set('code', opts.code);
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  if (opts?.offset != null) q.set('offset', String(opts.offset));
  const res = await apiFetch(
    `/scrap-library/embed/enrich/queue-log${q.toString() ? `?${q}` : ''}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      region?: string | null;
      code?: string | null;
      counts: {
        pending: number;
        running: number;
        done: number;
        soft?: number;
        fail: number;
      };
      items: ScrapLibraryEnrichQueueItem[];
      total?: number;
      limit?: number;
      offset?: number;
    }>
  ).data;
}

export async function getScrapLibraryEnrichLocalCovers(opts: {
  region?: string;
  code?: string;
  itemId?: string;
}): Promise<{
  ok?: boolean;
  folder?: string;
  posterApi?: string;
  thumbApi?: string;
  fanartApi?: string;
  files?: Array<{
    kind?: string;
    name?: string;
    posterApi?: string;
    mtime?: number;
  }>;
}> {
  const q = new URLSearchParams();
  if (opts.region) q.set('region', opts.region);
  if (opts.code) q.set('code', opts.code);
  if (opts.itemId) q.set('itemId', opts.itemId);
  const res = await apiFetch(
    `/scrap-library/embed/enrich/local-covers${q.toString() ? `?${q}` : ''}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      folder?: string;
      posterApi?: string;
      thumbApi?: string;
      fanartApi?: string;
      files?: Array<{
        kind?: string;
        name?: string;
        posterApi?: string;
        mtime?: number;
      }>;
    }>
  ).data;
}

export async function scanScrapLibraryEnrichQueue(body?: {
  region?: string;
  limit?: number;
}): Promise<{
  ok?: boolean;
  scanned?: boolean;
  scannedN?: number;
  listedN?: number;
  pendingTotal?: number;
  prunedN?: number;
  mode?: string;
  reason?: string;
  region?: string | null;
  counts: {
    pending: number;
    running: number;
    done: number;
    soft?: number;
    fail: number;
  };
  items: ScrapLibraryEnrichQueueItem[];
  localDone?: number;
  localSoft?: number;
  localFail?: number;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/queue-scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      region: body?.region || '',
      limit: body?.limit ?? 0,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      scanned?: boolean;
      scannedN?: number;
      listedN?: number;
      pendingTotal?: number;
      prunedN?: number;
      mode?: string;
      reason?: string;
      region?: string | null;
      counts: {
        pending: number;
        running: number;
        done: number;
        soft?: number;
        fail: number;
      };
      items: ScrapLibraryEnrichQueueItem[];
      localDone?: number;
      localSoft?: number;
      localFail?: number;
    }>
  ).data;
}

export async function clearScrapLibraryEnrichLogs(opts?: {
  region?: string;
}): Promise<{
  ok?: boolean;
  cleared?: boolean;
  busy?: boolean;
  error?: string;
  checkpointCleared?: boolean;
  region?: string | null;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/logs/clear', {
    method: 'POST',
    body: JSON.stringify({ region: opts?.region ?? '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (
    (await res.json()) as Envelope<{
      ok?: boolean;
      cleared?: boolean;
      busy?: boolean;
      error?: string;
      checkpointCleared?: boolean;
      region?: string | null;
    }>
  ).data;
  if (data && data.ok === false) {
    throw new Error(String(data.error || '清空失败'));
  }
  return data;
}

export async function cancelScrapLibraryEnrich(): Promise<{
  ok?: boolean;
  paused?: boolean;
  cancelled?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/pause', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      paused?: boolean;
      cancelled?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function pauseScrapLibraryEnrich(): Promise<{
  ok?: boolean;
  paused?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/pause', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      paused?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function stopScrapLibraryEnrich(opts?: {
  region?: string;
}): Promise<{
  ok?: boolean;
  stopped?: boolean;
  cleared?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/stop', {
    method: 'POST',
    body: JSON.stringify({ region: opts?.region ?? '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      stopped?: boolean;
      cleared?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function retryScrapLibraryEnrichFails(opts: {
  region: string;
}): Promise<{
  ok?: boolean;
  reopened?: number;
  region?: string;
  counts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  injected?: boolean;
  running?: boolean;
  error?: string;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/retry-fails', {
    method: 'POST',
    body: JSON.stringify({ region: opts.region || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      reopened?: number;
      region?: string;
      counts?: {
        pending?: number;
        running?: number;
        done?: number;
        soft?: number;
        fail?: number;
      };
      injected?: boolean;
      running?: boolean;
      error?: string;
    }>
  ).data;
}

export async function retryScrapLibraryEnrichSofts(opts: {
  region: string;
}): Promise<{
  ok?: boolean;
  reopened?: number;
  region?: string;
  counts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  injected?: boolean;
  running?: boolean;
  error?: string;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/retry-softs', {
    method: 'POST',
    body: JSON.stringify({ region: opts.region || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      reopened?: number;
      region?: string;
      counts?: {
        pending?: number;
        running?: number;
        done?: number;
        soft?: number;
        fail?: number;
      };
      injected?: boolean;
      running?: boolean;
      error?: string;
    }>
  ).data;
}

export type EnrichStrategyMode =
  | 'parallel_all'
  | 'adaptive_first'
  | 'adaptive_only';

export type CoverCropMode = 'right' | 'face' | 'none' | 'smart' | string;

export type ScrapEnrichCoverSettings = {
  quality: 'compact' | string;
  cropRatio?: 'full' | 'emby' | string;
  regionCrop: Record<string, CoverCropMode>;
  minShortEdge?: number;
  coverLogicVersion?: number;
};

export type ScrapEnrichStrategy = {
  mode: EnrichStrategyMode | string;
  modeLabel?: string;
  /** 同时处理的番号数 */
  itemWorkers?: number;
  adaptiveWorkers: number;
  flareWorkers: number;
  includeFlare: boolean;
  perSourceTimeoutSec: number;
  regionGroups: Record<string, string[]>;
  /** 番号类型 → 有序刮削源（全局优先级） */
  regionSources?: Record<string, string[]>;
  regionsEnabled?: Record<string, boolean>;
  fillMode?: 'incremental' | 'refresh_weak' | 'overwrite' | string;
  fillModeLabel?: string;
  fillModes?: { value: string; label: string }[];
  /** 女优头像：增量只补缺；覆盖已有也重下 */
  actressAvatarMode?: 'incremental' | 'overwrite' | string;
  /** 无可用中文或机翻过烂时，自动大模型译中 */
  llmTranslateOnJunk?: boolean;
  fieldLanguage?: { title?: string; overview?: string };
  stripTitleActorSuffix?: boolean;
  stripTitleCodePrefix?: boolean;
  fc2SellerAsActor?: boolean;
  coverEnhance?: 'off' | 'official' | string;
  outlineShow?: 'zh' | 'zh_jp' | 'jp_zh' | string;
  forceFields?: string[];
  /** 字段站点优先级覆盖：空 = catalog 默认；有值 = 配置源第一优先，链上首个合格即停 */
  fieldPriority?: Record<string, string[]>;
  /** 字段优先级页：隐藏未配置行 */
  fieldPriorityHideEmpty?: boolean;
  /** 元数据优化：标题/女优/标签映射 + 简介换行 */
  localMaps?: {
    title?: string;
    actors?: string;
    tags?: string;
    compactOutlineNewlines?: boolean;
  };
  cover?: ScrapEnrichCoverSettings;
  modes?: { value: string; label: string }[];
  groupOptions?: { id: string; label: string }[];
  regions?: {
    id: string;
    label: string;
    folderLabel?: string;
    groups: string[];
    sources?: string[];
    enabled?: boolean;
    coverHint?: string;
  }[];
  regionSourceDefaults?: Record<string, string[]>;
  /** 无码官网专用站（按前缀自动注入，不进 UI 链） */
  uncensoredOfficialSources?: string[];
  uncensoredOfficialHint?: string;
  coverCropOptions?: { id: string; label: string }[];
  coverQualityOptions?: { id: string; label: string }[];
  coverRatioOptions?: { id: string; label: string }[];
  fieldLanguageOptions?: { id: string; label: string }[];
  coverEnhanceOptions?: { id: string; label: string }[];
  outlineShowOptions?: { id: string; label: string }[];
  forceFieldOptions?: { id: string; label: string }[];
  fieldPriorityFields?: { id: string; label: string }[];
  sourceOptions?: { id: string; label: string; group?: string; enabled?: boolean }[];
  fieldPriorityDefaults?: Record<string, string[]>;
  localMapModeOptions?: { id: string; label: string }[];
};

export async function getScrapEnrichStrategy(): Promise<ScrapEnrichStrategy> {
  const res = await apiFetch('/scrap-library/embed/enrich/strategy');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapEnrichStrategy>).data;
}

export async function putScrapEnrichStrategy(
  body: Partial<ScrapEnrichStrategy>,
): Promise<ScrapEnrichStrategy> {
  const res = await apiFetch('/scrap-library/embed/enrich/strategy', {
    method: 'PUT',
    body: JSON.stringify({
      mode: body.mode ?? 'parallel_all',
      itemWorkers: body.itemWorkers ?? 5,
      adaptiveWorkers: body.adaptiveWorkers ?? 0,
      flareWorkers: body.flareWorkers ?? 0,
      includeFlare: body.includeFlare !== false,
      perSourceTimeoutSec: body.perSourceTimeoutSec ?? 45,
      regionGroups: body.regionGroups ?? {},
      regionSources:
        body.regionSources && typeof body.regionSources === 'object'
          ? body.regionSources
          : {},
      regionsEnabled: body.regionsEnabled ?? {},
      fillMode:
        body.fillMode === 'overwrite'
          ? 'overwrite'
          : body.fillMode === 'refresh_weak'
            ? 'refresh_weak'
            : 'incremental',
      actressAvatarMode:
        body.actressAvatarMode === 'overwrite' ? 'overwrite' : 'incremental',
      llmTranslateOnJunk: body.llmTranslateOnJunk !== false,
      fieldLanguage: body.fieldLanguage,
      stripTitleActorSuffix: Boolean(body.stripTitleActorSuffix),
      stripTitleCodePrefix: Boolean(body.stripTitleCodePrefix),
      fc2SellerAsActor: body.fc2SellerAsActor !== false,
      coverEnhance: body.coverEnhance === 'official' ? 'official' : 'off',
      outlineShow:
        body.outlineShow === 'zh_jp' || body.outlineShow === 'jp_zh'
          ? body.outlineShow
          : 'zh',
      forceFields: Array.isArray(body.forceFields)
        ? body.forceFields.map((x) => String(x || '').trim()).filter(Boolean)
        : [],
      fieldPriority:
        body.fieldPriority && typeof body.fieldPriority === 'object'
          ? body.fieldPriority
          : {},
      fieldPriorityHideEmpty: Boolean(body.fieldPriorityHideEmpty),
      localMaps: {
        title:
          body.localMaps?.title === 'off'
            ? 'off'
            : body.localMaps?.title === 'force'
              ? 'force'
              : 'prefer',
        actors: body.localMaps?.actors === 'off' ? 'off' : 'fallback',
        tags: body.localMaps?.tags === 'off' ? 'off' : 'fallback',
        compactOutlineNewlines: body.localMaps?.compactOutlineNewlines !== false,
      },
      cover: body.cover,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapEnrichStrategy>).data;
}

export type ScrapPosterRecompressStatus = {
  running: boolean;
  phase?: string;
  dryRun?: boolean;
  quality?: string;
  progress?: {
    done?: number;
    total?: number;
    ok?: number;
    skip?: number;
    fail?: number;
    savedBytes?: number;
    percent?: number;
  };
  result?: {
    ok?: boolean;
    dryRun?: boolean;
    quality?: string;
    total?: number;
    rewritten?: number;
    skipped?: number;
    failed?: number;
    savedBytes?: number;
    error?: string;
  } | null;
  error?: string;
};

export async function startScrapPosterRecompress(opts?: {
  region?: string;
  quality?: string;
  limit?: number;
  dryRun?: boolean;
}): Promise<ScrapPosterRecompressStatus> {
  const res = await apiFetch('/scrap-library/embed/posters/recompress', {
    method: 'POST',
    body: JSON.stringify({
      region: opts?.region || '',
      quality: opts?.quality || '',
      limit: opts?.limit ?? 0,
      dryRun: Boolean(opts?.dryRun),
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapPosterRecompressStatus>).data;
}

export async function getScrapPosterRecompressStatus(): Promise<ScrapPosterRecompressStatus> {
  const res = await apiFetch('/scrap-library/embed/posters/recompress/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapPosterRecompressStatus>).data;
}

/** 缺本地海报时，把远程 cover 落到番号目录 poster.jpg */
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

export type AiChatSearchResult = {
  reply: string;
  keyword: string;
  usedLlm?: boolean;
  searchMode?: 'semantic' | 'keyword';
  resources: ResourceItem[];
  total_count: number;
};

export async function aiChatSearch(opts: {
  message: string;
  history?: Array<{ role: 'user' | 'assistant'; content: string }>;
}): Promise<AiChatSearchResult> {
  const res = await apiFetch('/ai/chat-search', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiChatSearchResult>).data;
}

export type AssistantSource = 'sehua' | 'magnet' | 'scrap' | 'media' | 'web';

export type AssistantCard = {
  id: string;
  source: AssistantSource | string;
  title: string;
  subtitle?: string;
  meta?: string;
  cover?: string;
  score?: number;
  open: {
    kind: 'sehua' | 'magnet' | 'scrap' | 'media' | 'url' | string;
    hash?: string;
    url?: string;
    title?: string;
    item?: ScrapLibraryEmbedItem | MediaItem | Record<string, unknown>;
  };
};

export type AssistantStep = {
  tool?: string;
  label?: string;
  query?: string;
  status?: string;
  ok?: boolean;
  summary?: string;
};

export type AssistantChatResult = {
  reply: string;
  cards: AssistantCard[];
  steps?: AssistantStep[];
  usedLlm?: boolean;
  usedTools?: string[];
  toolSummary?: string;
};

export type AssistantMeta = {
  suggestChips: string[];
  webSearchEnabled?: boolean;
  sources?: string[];
};

export type AiWebSearchConfig = {
  enabled?: boolean;
  provider?: 'serper' | 'brave' | 'searxng' | string;
  baseUrl?: string;
  configured?: boolean;
  fromEnv?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiAssistantToolMeta = {
  id: string;
  group: string;
  label: string;
  desc: string;
};

export type AiAssistantSkillGroup = {
  id: string;
  label: string;
  desc: string;
};

export type AiAssistantConfig = {
  systemPrompt?: string;
  suggestChips?: string[];
  tools?: Record<string, boolean>;
  toolMeta?: AiAssistantToolMeta[];
  skillGroups?: AiAssistantSkillGroup[];
  updated_at?: string;
};

export async function getAssistantMeta(): Promise<AssistantMeta> {
  const res = await apiFetch('/ai/assistant/meta');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AssistantMeta>).data;
}

export async function assistantChat(opts: {
  message: string;
  history?: Array<{ role: 'user' | 'assistant'; content: string; summary?: string }>;
  preferSources?: string[];
}): Promise<AssistantChatResult> {
  const res = await apiFetch('/ai/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
      preferSources: opts.preferSources || [],
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AssistantChatResult>).data;
}

export async function assistantChatStream(
  opts: {
    message: string;
    history?: Array<{ role: 'user' | 'assistant'; content: string; summary?: string }>;
    preferSources?: string[];
  },
  handlers: {
    onStatus?: (text: string, tool?: string) => void;
    onStep?: (step: AssistantStep) => void;
    onCardsPartial?: (cards: AssistantCard[]) => void;
    onDone?: (data: AssistantChatResult) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<AssistantChatResult> {
  const abortError = () => {
    const err = new DOMException('Aborted', 'AbortError');
    throw err;
  };
  if (signal?.aborted) abortError();

  const res = await apiFetch('/ai/assistant/chat/stream', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
      preferSources: opts.preferSources || [],
    }),
    signal,
  });
  if (signal?.aborted) abortError();
  if (!res.ok) throw new Error(await parseError(res));
  if (!res.body) throw new Error('无流式响应');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: AssistantChatResult | null = null;

  const onAbort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      if (signal?.aborted) abortError();
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';
      for (const chunk of chunks) {
        const line = chunk
          .split('\n')
          .map((l) => l.trim())
          .find((l) => l.startsWith('data:'));
        if (!line) continue;
        const raw = line.replace(/^data:\s*/, '');
        try {
          const evt = JSON.parse(raw) as {
            event?: string;
            data?: Record<string, unknown>;
          };
          const data = (evt.data || {}) as Record<string, unknown>;
          if (evt.event === 'status') {
            handlers.onStatus?.(String(data.text || ''), data.tool ? String(data.tool) : undefined);
          } else if (evt.event === 'step') {
            handlers.onStep?.(data as AssistantStep);
          } else if (evt.event === 'cards_partial') {
            handlers.onCardsPartial?.((data.cards as AssistantCard[]) || []);
          } else if (evt.event === 'error') {
            handlers.onError?.(String(data.message || '失败'));
          } else if (evt.event === 'done') {
            finalResult = data as unknown as AssistantChatResult;
            handlers.onDone?.(finalResult);
          }
        } catch {
          /* ignore bad chunk */
        }
      }
    }
  } catch (e) {
    if (signal?.aborted) abortError();
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    if (e instanceof Error && e.name === 'AbortError') throw e;
    throw e;
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }

  if (signal?.aborted) abortError();
  if (!finalResult) throw new Error('流式结束但无结果');
  return finalResult;
}

export async function getAiWebSearch(): Promise<AiWebSearchConfig> {
  const res = await apiFetch('/settings/ai/web-search');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiWebSearchConfig>).data;
}

export async function putAiWebSearch(body: {
  enabled?: boolean;
  provider?: string;
  apiKey?: string;
  baseUrl?: string;
}): Promise<AiWebSearchConfig> {
  const res = await apiFetch('/settings/ai/web-search', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiWebSearchConfig>).data;
}

export async function getAiAssistant(): Promise<AiAssistantConfig> {
  const res = await apiFetch('/settings/ai/assistant');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiAssistantConfig>).data;
}

export async function putAiAssistant(body: {
  suggestChips?: string[];
  systemPrompt?: string;
  tools?: Record<string, boolean>;
}): Promise<AiAssistantConfig> {
  const res = await apiFetch('/settings/ai/assistant', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiAssistantConfig>).data;
}

export type ChatPresetListItem = {
  id: string;
  name: string;
  updatedAt?: string;
  promptCount?: number;
  kind?: string;
};

export type ChatPresetPrompt = {
  identifier: string;
  name: string;
  role: string;
  enabled: boolean;
  marker?: boolean;
  content?: string;
  injection_position?: number | null;
  injection_depth?: number | null;
  injection_order?: number | null;
  forbid_overrides?: boolean;
};

export type ChatPresetDetail = {
  id: string;
  name: string;
  updatedAt?: string;
  sampling: AiSamplingConfig;
  prompts: ChatPresetPrompt[];
  regexScripts?: Array<{
    id: string;
    scriptName: string;
    disabled?: boolean;
    findRegex?: string;
  }>;
  active?: boolean;
};

export async function listChatPresets(): Promise<{
  presets: ChatPresetListItem[];
  activeId: string | null;
}> {
  const res = await apiFetch('/settings/ai/chat-presets');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function getChatPreset(id: string): Promise<ChatPresetDetail> {
  const res = await apiFetch(`/settings/ai/chat-presets/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetDetail>).data;
}

export async function importChatPreset(file: File): Promise<ChatPresetListItem> {
  const text = await file.text();
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error('JSON 解析失败');
  }
  const res = await apiFetch('/settings/ai/chat-presets/import', {
    method: 'POST',
    body: JSON.stringify({ name: file.name, data }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetListItem>).data;
}

export async function activateChatPreset(
  id: string | null,
): Promise<{ presets: ChatPresetListItem[]; activeId: string | null }> {
  const res = await apiFetch('/settings/ai/chat-presets/activate', {
    method: 'POST',
    body: JSON.stringify({ id }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function deleteChatPreset(
  id: string,
): Promise<{ presets: ChatPresetListItem[]; activeId: string | null }> {
  const res = await apiFetch(`/settings/ai/chat-presets/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function saveChatPresetParams(
  id: string,
  sampling: AiSamplingConfig,
): Promise<ChatPresetDetail> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/params`,
    {
      method: 'PUT',
      body: JSON.stringify(sampling),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetDetail>).data;
}

export async function enableChatPresetPrompt(
  id: string,
  identifier: string,
  enabled: boolean,
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts/enable`,
    {
      method: 'POST',
      body: JSON.stringify({ identifier, enabled }),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export async function saveChatPresetPrompt(
  id: string,
  body: {
    identifier: string;
    name?: string;
    role?: string;
    content?: string;
    enabled?: boolean;
  },
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts`,
    {
      method: 'PUT',
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export async function addChatPresetPrompt(
  id: string,
  body?: { name?: string; role?: string; content?: string },
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts`,
    {
      method: 'POST',
      body: JSON.stringify(body || {}),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export function chatPresetExportUrl(id: string): string {
  return `${API_BASE}/settings/ai/chat-presets/${encodeURIComponent(id)}/export`;
}

export type P115SaveSource = 'warehouse' | 'movie' | 'tv' | 'makers';

export type P115TargetFolder = {
  folderCid: string;
  folderName: string;
};

export type P115Config = {
  enabled: boolean;
  folderCid: string;
  folderName: string;
  label: string;
  targets?: Partial<Record<P115SaveSource | 'media', P115TargetFolder>>;
  /** 字幕根目录（可浏览选择）；未配则片商根下自动用「字幕」 */
  subsFolder?: P115TargetFolder;
  /** 字幕分层：根/日本有码/ABC-123.srt */
  subsLayered?: boolean;
  hasCookie: boolean;
  cookieHint: string;
  configured?: boolean;
  updated_at?: string;
  /** 云转存剩余任务数 */
  quota?: number | null;
  /** 云转存总额度 */
  quotaTotal?: number | null;
  quotaError?: string;
  spaceTotal?: number | null;
  spaceTotalText?: string | null;
  spaceUsed?: number | null;
  spaceUsedText?: string | null;
  spaceRemain?: number | null;
  spaceRemainText?: string | null;
  /** 离线单任务大小上限（字节） */
  offlineLimit?: number | null;
};

export type P115FolderItem = { cid: string; name: string };

export type P115FolderList = {
  path: P115FolderItem[];
  folders: P115FolderItem[];
};

export async function getP115(): Promise<P115Config> {
  const res = await apiFetch('/settings/p115');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115Config>).data;
}

export async function getP115Status(): Promise<P115Config> {
  const res = await apiFetch('/settings/p115/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115Config>).data;
}

export async function putP115(body: {
  cookie?: string;
  folderCid?: string;
  folderName?: string;
  label?: string;
  targets?: Partial<Record<P115SaveSource | 'media', P115TargetFolder>>;
  subsFolder?: P115TargetFolder;
  subsLayered?: boolean;
  validate?: boolean;
}): Promise<P115Config & { message?: string }> {
  const warehouse = body.targets?.warehouse;
  const res = await apiFetch('/settings/p115', {
    method: 'PUT',
    body: JSON.stringify({
      cookie: body.cookie,
      folderCid: body.folderCid ?? warehouse?.folderCid ?? '0',
      folderName: body.folderName ?? warehouse?.folderName ?? '',
      label: body.label ?? '',
      targets: body.targets,
      subsFolder: body.subsFolder,
      subsLayered: body.subsLayered,
      validate: body.validate ?? true,
      enabled: true,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<P115Config> & { message: string };
  return { ...json.data, message: json.message };
}

export async function listP115Folders(body: {
  cid?: string;
  cookie?: string;
}): Promise<P115FolderList> {
  const res = await apiFetch('/settings/p115/folders', {
    method: 'POST',
    body: JSON.stringify({
      cid: body.cid || '0',
      cookie: body.cookie,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115FolderList>).data;
}

export async function validateP115(body: {
  cookie?: string;
  folderCid?: string;
}): Promise<{
  ok: boolean;
  message: string;
  folderName?: string;
  quota?: number | null;
  quotaTotal?: number | null;
  spaceTotalText?: string | null;
  spaceUsedText?: string | null;
  spaceRemainText?: string | null;
  spaceTotal?: number | null;
  spaceUsed?: number | null;
  spaceRemain?: number | null;
  offlineLimit?: number | null;
}> {
  const res = await apiFetch('/settings/p115/validate', {
    method: 'POST',
    body: JSON.stringify({
      cookie: body.cookie,
      folderCid: body.folderCid || '0',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok?: boolean;
    folderName?: string;
    quota?: number | null;
    quotaTotal?: number | null;
    spaceTotalText?: string | null;
    spaceUsedText?: string | null;
    spaceRemainText?: string | null;
    spaceTotal?: number | null;
    spaceUsed?: number | null;
    spaceRemain?: number | null;
    offlineLimit?: number | null;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok ?? true),
    message: json.message || '',
    folderName: json.data?.folderName,
    quota: json.data?.quota,
    quotaTotal: json.data?.quotaTotal,
    spaceTotalText: json.data?.spaceTotalText,
    spaceUsedText: json.data?.spaceUsedText,
    spaceRemainText: json.data?.spaceRemainText,
    spaceTotal: json.data?.spaceTotal,
    spaceUsed: json.data?.spaceUsed,
    spaceRemain: json.data?.spaceRemain,
    offlineLimit: json.data?.offlineLimit,
  };
}

export type P115Task = {
  name: string;
  status: number;
  statusLabel: string;
  percent: number;
  error?: string;
  infoHash?: string;
  size?: number | null;
  addTime?: number | null;
  updateTime?: number | null;
  fileId?: string | null;
};

export type P115TasksResult = {
  tasks: P115Task[];
  page?: number | null;
  pageCount?: number | null;
  count?: number | null;
  quota?: number | null;
  quotaTotal?: number | null;
};

export type P115ClearMode = 'done' | 'failed' | 'all';

export async function listP115Tasks(page = 1): Promise<P115TasksResult> {
  const res = await apiFetch(`/settings/p115/tasks?page=${Math.max(1, page)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115TasksResult>).data;
}

export async function clearP115Tasks(
  mode: P115ClearMode,
): Promise<P115TasksResult & { ok?: boolean; mode?: string; message?: string }> {
  const res = await apiFetch('/settings/p115/tasks/clear', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<
    P115TasksResult & { ok?: boolean; mode?: string; message?: string }
  > & { message: string };
  return { ...json.data, message: json.message };
}

export async function deleteP115Task(
  infoHash: string,
): Promise<P115TasksResult & { ok?: boolean; infoHash?: string; message?: string }> {
  const res = await apiFetch('/settings/p115/tasks/delete', {
    method: 'POST',
    body: JSON.stringify({ infoHash }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<
    P115TasksResult & { ok?: boolean; infoHash?: string; message?: string }
  > & { message: string };
  return { ...json.data, message: json.message };
}

export type P115QrStart = {
  uid: string;
  time: string | number;
  sign: string;
  qrImage?: string | null;
  qrcode?: string | null;
  app: string;
};

export type P115QrStatus = {
  status: number | null;
  statusLabel: string;
  done: boolean;
  expired: boolean;
};

export async function startP115Qrcode(app = 'alipaymini'): Promise<P115QrStart> {
  const res = await apiFetch('/settings/p115/qrcode/start', {
    method: 'POST',
    body: JSON.stringify({ app }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115QrStart>).data;
}

export async function pollP115Qrcode(body: {
  uid: string;
  time: string | number;
  sign: string;
}): Promise<P115QrStatus> {
  const res = await apiFetch('/settings/p115/qrcode/status', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<P115QrStatus>).data;
}

export async function completeP115Qrcode(body: {
  uid: string;
  app?: string;
  save?: boolean;
}): Promise<P115Config & { cookie?: string; saved?: boolean; message?: string }> {
  const res = await apiFetch('/settings/p115/qrcode/complete', {
    method: 'POST',
    body: JSON.stringify({
      uid: body.uid,
      app: body.app || 'alipaymini',
      save: body.save !== false,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<
    P115Config & { cookie?: string; saved?: boolean }
  > & { message: string };
  return { ...json.data, message: json.message };
}

/**
 * 外链封面 → 同源 /cover-proxy（服务端走 settings.proxyUrl）。
 * 已是 /api、相对路径或已代理的地址原样返回。
 * @param opts.w 列表缩略最长边（服务端 JPEG 压缩）
 */
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
