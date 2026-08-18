/**
 * 精简 API 客户端 — 对接 apps/api（色花同协议），非整包复制 sehua 前端。
 */
import type {
  AuthUser,
  BoardNavCategory,
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
    const j = (await res.json()) as { detail?: string | { msg?: string }[] };
    if (typeof j.detail === 'string') return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]?.msg) return j.detail[0].msg;
  } catch {
    /* ignore */
  }
  return `请求失败 ${res.status}`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
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

export async function fetchTranslate(text: string): Promise<{
  text: string;
  alreadyEnglish: boolean;
  engine?: string;
}> {
  const res = await apiFetch('/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      text: string;
      alreadyEnglish: boolean;
      engine?: string;
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

export async function fetchBoards(): Promise<BoardNavCategory[]> {
  const res = await apiFetch('/boards');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<BoardNavCategory[]>).data;
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

/* —— Settings: TMDB / 115 / scrape / maker-fs / forum —— */

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

export type P115Config = {
  enabled: boolean;
  folderCid: string;
  folderName: string;
  label: string;
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
  folderCid: string;
  folderName: string;
  label: string;
  validate?: boolean;
}): Promise<P115Config & { message?: string }> {
  const res = await apiFetch('/settings/p115', {
    method: 'PUT',
    body: JSON.stringify({
      cookie: body.cookie,
      folderCid: body.folderCid,
      folderName: body.folderName,
      label: body.label,
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

export type PosterCropMode = 'right' | 'none' | 'face';
export type PosterCropRatioId = 'full' | 'emby';

export type PosterCropConfig = {
  byKind: Record<string, PosterCropMode>;
  ratio: PosterCropRatioId;
  cropDownloadedPoster: boolean;
  preferCropIfBetter: boolean;
  kindHints?: Record<string, string>;
};

export const DEFAULT_POSTER_CROP: PosterCropConfig = {
  byKind: {
    japan_censored: 'right',
    japan_gravure: 'right',
    japan_uncensored: 'none',
    japan_amateur: 'face',
    fc2: 'face',
    china: 'none',
    western: 'none',
  },
  ratio: 'full',
  cropDownloadedPoster: false,
  preferCropIfBetter: false,
  kindHints: {
    japan_censored: '碟片封面海报多在右侧，显示时右侧取景',
    japan_gravure: '写真横图较多，显示时可用右侧取景',
    japan_uncensored: '无码作品可以保留原图，也可以进行人脸识别，推荐不裁剪',
    japan_amateur: '素人图片尺寸不规则，建议使用人脸识别',
    fc2: 'FC2图片尺寸不规则，建议使用人脸识别',
    china: '国产作品一般有完整封面，建议不裁剪保留原样',
    western: '欧美作品封面多为完整竖图或宽图，建议不裁剪保留原样',
  },
};

function normalizePosterCropClient(raw: unknown): PosterCropConfig {
  const src = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const byRaw =
    src.byKind && typeof src.byKind === 'object'
      ? (src.byKind as Record<string, unknown>)
      : {};
  const byKind = { ...DEFAULT_POSTER_CROP.byKind };
  for (const id of Object.keys(byKind)) {
    const v = String(byRaw[id] || byKind[id]).trim().toLowerCase();
    if (v === 'right' || v === 'none' || v === 'face') byKind[id] = v;
  }
  const ratio = src.ratio === 'emby' ? 'emby' : 'full';
  const hints =
    src.kindHints && typeof src.kindHints === 'object'
      ? {
          ...DEFAULT_POSTER_CROP.kindHints,
          ...(src.kindHints as Record<string, string>),
        }
      : DEFAULT_POSTER_CROP.kindHints;
  return {
    byKind,
    ratio,
    cropDownloadedPoster: Boolean(src.cropDownloadedPoster),
    preferCropIfBetter: Boolean(src.preferCropIfBetter),
    kindHints: hints,
  };
}

export async function getPosterCrop(): Promise<PosterCropConfig> {
  const res = await apiFetch('/settings/scrape/poster-crop');
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<unknown>).data;
  return normalizePosterCropClient(data);
}

export async function putPosterCrop(
  posterCrop: PosterCropConfig,
): Promise<PosterCropConfig> {
  const res = await apiFetch('/settings/scrape/poster-crop', {
    method: 'PUT',
    body: JSON.stringify({ posterCrop }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = ((await res.json()) as Envelope<unknown>).data;
  return normalizePosterCropClient(data);
}

export type ScrapeSourceAccess = 'direct' | 'proxy' | 'proxy_flare';

export type ScrapeSourceDef = {
  id: string;
  name: string;
  group: string;
  defaultUrl?: string;
  access?: ScrapeSourceAccess | string;
};

export type ScrapeSourceCard = {
  id: string;
  name: string;
  group: string;
  /** 直连 / 代理直连 / 代理过盾 */
  access?: ScrapeSourceAccess | string;
  enabled: boolean;
  baseUrl: string;
  cookie?: string;
  status: 'ok' | 'error' | 'unknown' | string;
  lastCheckedAt?: string | null;
  lastError?: string | null;
  /** 上次探测实际通道：direct / curl / flare */
  lastProbeVia?: 'direct' | 'curl' | 'flare' | string | null;
  retry?: number;
  cooldownUntil?: string | null;
  cooldownRemainingSec?: number;
};

export type ScrapeRegionProfile = {
  libraryRoot: string;
  writeTree: boolean | null;
  writeEmby: boolean | null;
  metaSources: string[];
  coverSources: string[];
  /** 四字段源优先级（schema≥3 以本区为准） */
  fieldPriority?: ScrapeFieldPriority;
};

/** 字段优先级：封面 / 中文标题 / 简介 / 制片方 / 女优 / 标签 / 系列 */
export type ScrapeFieldPriority = {
  cover: string[];
  titleZh: string[];
  outline: string[];
  studio: string[];
  actors: string[];
  tags: string[];
  series: string[];
};

export type ScrapeLibraryOption = { value: string; label: string };

export type ScrapeLibraryDirEntry = {
  name: string;
  path: string;
  absPath: string;
};

export type ScrapeLibraryBrowse = {
  path: string;
  absPath: string;
  parent: string | null;
  crumbs: Array<{ name: string; path: string }>;
  entries: ScrapeLibraryDirEntry[];
  selectable: boolean;
};

export type ScrapeTaskField =
  | 'cover'
  | 'titleZh'
  | 'outline'
  | 'studio'
  | 'actors'
  | 'tags'
  | 'series';

export type ScrapeTask = {
  id: string;
  name: string;
  regions: string[];
  maker?: string;
  prefix?: string;
  code?: string;
  mode: 'incremental' | 'force';
  fields: ScrapeTaskField[];
  /** 从索引物化复用的字段（仅勾选的才读取；不含封面） */
  localFields?: ScrapeTaskField[];
  /** maker-fs 监控：开启后须手动开始并跑完一轮才自动增量 */
  watchEnabled?: boolean;
  /** 后端：手动跑完后武装，暂停/取消解除 */
  watchArmed?: boolean;
  lastStatus?: string;
  updatedAt?: string;
  /** 最近一次导出统计（与进度卡一致） */
  done?: number;
  empty?: number;
  skipped?: number;
  /** 字段不全（黄）；暂停续跑不重试 */
  incomplete?: number;
  /** 网络/连不上等真正失败（红）；暂停续跑只重试此项 */
  failed?: number;
  total?: number;
  /** 各结果番号明细（点击统计框查看） */
  doneCodes?: string[];
  emptyCodes?: string[];
  skippedCodes?: string[];
  incompleteCodes?: string[];
  failedCodes?: string[];
};

export type CoverDownloadStrategy = 'priority' | 'size';

export type MetadataOptimizeLang = 'zh-CN' | 'zh-TW' | 'ja' | 'en';

export type MetadataOptimizeConfig = {
  /** 番号匹配时优先用色花堂中文标题 */
  useForumZhTitle: boolean;
  /** 用内置表规范化演员名、补充 javdb 链接 */
  enableActorMapping: boolean;
  /** 用内置表规范化标签 */
  enableTagMapping: boolean;
  /** 简介连续空行压成单行换行 */
  compactOutlineNewlines: boolean;
  /** 演员/标签映射语言 */
  mappingLanguage: MetadataOptimizeLang;
};

export const DEFAULT_METADATA_OPTIMIZE: MetadataOptimizeConfig = {
  useForumZhTitle: true,
  enableActorMapping: true,
  enableTagMapping: true,
  compactOutlineNewlines: true,
  mappingLanguage: 'zh-CN',
};

export type ScrapeConfig = {
  enabled: boolean;
  origin: string;
  /** 容器内相对路径，如 data/library */
  libraryRoot?: string;
  /** 项目内绝对路径（展示用） */
  libraryAbs?: string;
  libraryOptions?: ScrapeLibraryOption[];
  /** FlareSolverr /v1，如 http://192.168.2.38:8181/v1 */
  flareSolverrUrl?: string;
  /** HTTP(S) 代理，如 http://127.0.0.1:7890 */
  proxyUrl?: string;
  /** 缩略图下载策略：priority=按源优先级；size=全候选比文件大小 */
  coverDownloadStrategy?: CoverDownloadStrategy;
  /** @deprecated 兼容旧字段；等于 max(快源, 慢源) */
  exportConcurrency?: number;
  /** 快源通道并发（不过盾），1–8，默认 4 */
  exportFastConcurrency?: number;
  /** 慢源通道并发（任务可并行，过盾排队单飞），1–8，默认 4 */
  exportSlowConcurrency?: number;
  /** 海报剪裁（七区模板 + 比例 + 增强开关） */
  posterCrop?: PosterCropConfig;
  /** 刮削后元数据优化 */
  metadataOptimize?: MetadataOptimizeConfig;
  writeTree?: boolean;
  writeEmby?: boolean;
  configured?: boolean;
  /** API 探测 origin/health 是否可达 */
  online?: boolean;
  updated_at?: string;
  sourceCatalog?: ScrapeSourceDef[];
  sources?: ScrapeSourceCard[];
  fieldPriority?: ScrapeFieldPriority;
  retry?: { defaultRetry?: number };
  /** 刮削方案标签：七区（有码/写真/无码/素人/FC2/国产/欧美） */
  kindLabels?: Record<string, string>;
  kindProfiles?: Record<string, ScrapeRegionProfile>;
  /** Emby 式刮削任务 */
  scrapeTasks?: ScrapeTask[];
  /** 数据源自动连通性探测时间（每天一次，串行） */
  sourcesLastAutoTestAt?: string | null;
  /** @deprecated 同 kind* */
  regionLabels?: Record<string, string>;
  regionProfiles?: Record<string, ScrapeRegionProfile>;
};

export type ScrapeExportEvent = {
  ts: string;
  phase: string;
  level?: 'info' | 'ok' | 'warn' | 'error' | string;
  text: string;
  code?: string;
  source?: string;
  ms?: number;
};

export type ScrapeExportDetail = {
  code?: string;
  kind?: string;
  region?: string;
  regionLabel?: string;
  path?: string;
  phase?: string;
  title?: string;
  titleZh?: string;
  originalTitle?: string;
  plot?: string;
  actors?: string[];
  genres?: string[];
  studio?: string;
  publisher?: string;
  premiered?: string;
  runtime?: number | string | null;
  director?: string;
  series?: string;
  userRating?: number | string | null;
  productId?: string;
  poster?: string;
  posterLocal?: string;
  coverLocal?: string;
  mosaic?: string;
  message?: string;
  sourceRuns?: Array<{
    id: string;
    ok: boolean;
    ms: number;
    mode?: string;
    error?: string;
  }>;
  fieldSources?: Record<string, string>;
  /** 字段最终来源 + 实测耗时 */
  fieldTimings?: Record<
    string,
    { id: string; ms: number; ok: boolean; mode?: string }
  >;
  exportFields?: string[];
  /** 该番号过程日志（成功队列点进时带上） */
  events?: ScrapeExportEvent[];
};

/** 进度页预览 library 内封面；rev=文件 mtime 破坏 iOS/PWA 图片缓存 */
export function scrapeExportFileUrl(
  rel: string,
  rev?: string | number | null,
): string {
  const q = new URLSearchParams({ rel });
  const v = String(rev ?? '').trim();
  if (v) q.set('v', v);
  return `${API_BASE}/scrape/export/file?${q}`;
}

/** 进度页封面：本地库 / 外链代理。无 rel 且无 url 时返回空（勿只传 code）。 */
export function scrapeExportImageUrl(opts: {
  code?: string;
  url?: string;
  rel?: string;
  rev?: string | number | null;
}): string {
  if (opts.rel) return scrapeExportFileUrl(opts.rel, opts.rev);
  const remote = String(opts.url || '').trim();
  if (!remote) return '';
  const q = new URLSearchParams();
  if (opts.code) q.set('code', opts.code);
  q.set('u', remote);
  return `${API_BASE}/scrape/export/img?${q}`;
}

/**
 * 外链封面 → 同源 /cover-proxy（服务端走 settings.proxyUrl）。
 * 已是 /api、相对路径或已代理的地址原样返回。
 */
export function proxiedCoverUrl(url: string | null | undefined): string {
  const s = String(url || '').trim();
  if (!s) return '';
  if (
    s.startsWith(`${API_BASE}/cover-proxy?`) ||
    s.startsWith(`${API_BASE}/scrape/export/img?`) ||
    s.includes('/cover-proxy?') ||
    s.includes('/scrape/export/img?')
  ) {
    return s;
  }
  // 本站相对路径：补上 API_BASE（如 /maker-fs/file/...）
  if (s.startsWith('/')) {
    if (s.startsWith(`${API_BASE}/`) || s === API_BASE) return s;
    return `${API_BASE}${s}`;
  }
  if (!/^https?:\/\//i.test(s)) return s;
  return `${API_BASE}/cover-proxy?url=${encodeURIComponent(s)}`;
}

export type ScrapeExportQueueItem = {
  taskId?: string;
  name?: string;
};

export type ScrapeExportStatus = {
  running: boolean;
  paused?: boolean;
  startedAt?: string;
  finishedAt?: string;
  message?: string;
  total?: number;
  done?: number;
  failed?: number;
  incomplete?: number;
  skipped?: number;
  /** 空目录 / 空号种子（无详情可刮） */
  empty?: number;
  /** 真正进入并发线程、正在刮削的数量（排队未开始的不算） */
  active?: number;
  /** 各结果番号明细（轮询可能截断；全量走 /scrape/export/codes） */
  doneCodes?: string[];
  emptyCodes?: string[];
  skippedCodes?: string[];
  incompleteCodes?: string[];
  failedCodes?: string[];
  /** 轮询未带全量番号列表 */
  codesTruncated?: boolean;
  activeCodes?: string[];
  /** 快源通道正在刮削的番号 */
  activeFastCodes?: string[];
  /** 慢源通道正在刮削的番号 */
  activeSlowCodes?: string[];
  /** 快源通道排队未开始 */
  pendingFast?: number;
  /** 慢源通道排队未开始 */
  pendingSlow?: number;
  fastSlots?: number;
  slowSlots?: number;
  current?: string;
  region?: string;
  /** 本次导出范围（以后端状态为准，勿仅信任务卡片缓存） */
  maker?: string;
  prefix?: string;
  codeFilter?: string;
  /** 当前正在跑的任务 id */
  taskId?: string;
  taskName?: string;
  /** 本次实际刮削模式（以后端为准） */
  force?: boolean;
  mode?: 'incremental' | 'force' | string;
  /** 等待依次执行的后续任务 */
  queue?: ScrapeExportQueueItem[];
  events?: ScrapeExportEvent[];
  currentDetail?: ScrapeExportDetail | null;
  exportFields?: string[];
  /** 服务重启后可断点续跑 */
  resumable?: boolean;
  /** 上次是暂停态落盘 */
  pauseSaved?: boolean;
  watchHold?: boolean;
};

export type ScrapeExportPreview = {
  count: number;
  sample: Array<{
    code: string;
    prefix: string;
    maker: string;
    region: string;
    coverUrl?: string | null;
  }>;
  libraryRoot: string;
};

export async function getScrape(): Promise<ScrapeConfig> {
  const res = await apiFetch('/settings/scrape');
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeConfig>;
  const data = json.data;
  return {
    ...data,
    posterCrop: normalizePosterCropClient(data?.posterCrop),
  };
}

/** 浏览项目 data/ 下真实目录（默认库路径） */
export async function browseScrapeLibraryDirs(
  path = 'data',
): Promise<ScrapeLibraryBrowse> {
  const q = new URLSearchParams({ path });
  const res = await apiFetch(`/settings/scrape/library-dirs?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeLibraryBrowse>;
  return json.data;
}

export async function putScrape(
  body: Partial<
    Pick<
      ScrapeConfig,
      | 'enabled'
      | 'origin'
      | 'libraryRoot'
      | 'flareSolverrUrl'
      | 'proxyUrl'
      | 'coverDownloadStrategy'
      | 'exportConcurrency'
      | 'exportFastConcurrency'
      | 'exportSlowConcurrency'
      | 'posterCrop'
      | 'metadataOptimize'
      | 'writeTree'
      | 'writeEmby'
      | 'kindProfiles'
      | 'regionProfiles'
      | 'sources'
      | 'fieldPriority'
      | 'retry'
      | 'scrapeTasks'
    >
  >,
): Promise<ScrapeConfig> {
  const res = await apiFetch('/settings/scrape', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeConfig>;
  const data = json.data;
  return {
    ...data,
    posterCrop: normalizePosterCropClient(data?.posterCrop),
  };
}

export async function testScrapeSources(ids?: string[]): Promise<{
  data: ScrapeConfig;
  message: string;
}> {
  const res = await apiFetch('/settings/scrape/sources/test', {
    method: 'POST',
    body: JSON.stringify({ ids: ids || null }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeConfig> & {
    message: string;
  };
  return { data: json.data, message: json.message };
}

export async function patchScrapeSource(
  id: string,
  patch: { enabled?: boolean; baseUrl?: string; retry?: number },
): Promise<ScrapeConfig> {
  const res = await apiFetch(`/settings/scrape/sources/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeConfig>;
  return json.data;
}

export async function testScrape(
  body?: { enabled?: boolean; origin?: string },
): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/scrape/test', {
    method: 'POST',
    body: JSON.stringify({
      enabled: body?.enabled ?? true,
      origin: body?.origin || '127.0.0.1:9210',
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & {
    message: string;
  };
  return { ok: Boolean(json.data?.ok), message: json.message };
}

export async function testScrapeFlareSolverr(body?: {
  origin?: string;
  flareSolverrUrl?: string;
  proxyUrl?: string;
  sampleUrl?: string;
}): Promise<{
  ok: boolean;
  sampleOk?: boolean | null;
  message: string;
}> {
  const res = await apiFetch('/settings/scrape/flaresolverr/test', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok?: boolean;
    sampleOk?: boolean | null;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    sampleOk: json.data?.sampleOk,
    message: json.message,
  };
}

export type FlareMonitorSnapshot = {
  ok: boolean;
  flareSolverrUrl: string;
  reachable: boolean;
  sessions: number;
  ownedSession: string | null;
  orphanSessions: number;
  latencyAvgMs: number;
  latencyP95Ms: number;
  errorRate: number;
  trafficSample: number;
  cpuPercent: number | null;
  memPercent: number | null;
  memUsedMb: number | null;
  statsSource: string;
  level: 'ok' | 'warn' | 'critical' | 'down';
  reasons: string[];
  lastAction: string | null;
  lastActionAt: string | null;
  lastActionDetail: string | null;
  restartConfigured: boolean;
  autoEnabled: boolean;
  checkedAt: string;
};

export async function getFlareMonitor(): Promise<FlareMonitorSnapshot> {
  const res = await apiFetch('/settings/scrape/flaresolverr/monitor');
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<FlareMonitorSnapshot>;
  return json.data as FlareMonitorSnapshot;
}

export async function recycleFlareSolverr(): Promise<{
  message: string;
  data: FlareMonitorSnapshot & { destroyed?: number };
}> {
  const res = await apiFetch('/settings/scrape/flaresolverr/recycle', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<
    FlareMonitorSnapshot & { destroyed?: number }
  > & { message: string };
  return { message: json.message, data: json.data as FlareMonitorSnapshot };
}

export async function restartFlareSolverr(): Promise<{
  message: string;
  data: FlareMonitorSnapshot & { restartCmd?: string };
}> {
  const res = await apiFetch('/settings/scrape/flaresolverr/restart', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<
    FlareMonitorSnapshot & { restartCmd?: string }
  > & { message: string };
  return { message: json.message, data: json.data as FlareMonitorSnapshot };
}

export async function testScrapeProxy(body?: {
  origin?: string;
  proxyUrl?: string;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/scrape/proxy/test', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok?: boolean }> & {
    message: string;
  };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export async function fetchScrapeExportStatus(
  signal?: AbortSignal,
): Promise<ScrapeExportStatus> {
  // 默认不下发完整番号列表，避免数万级任务拖死轮询
  const res = await apiFetch('/scrape/export/status?codes=0', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

export async function fetchScrapeExportCodes(opts: {
  taskId?: string;
  bucket: 'done' | 'empty' | 'skipped' | 'failed' | 'incomplete' | 'active' | 'total';
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}): Promise<{ taskId: string; bucket: string; codes: string[]; total: number }> {
  const q = new URLSearchParams({
    bucket: opts.bucket === 'total' ? 'failed' : opts.bucket,
    limit: String(opts.limit ?? 50000),
    offset: String(opts.offset ?? 0),
  });
  if (opts.taskId) q.set('taskId', opts.taskId);
  const res = await apiFetch(`/scrape/export/codes?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    taskId?: string;
    bucket?: string;
    codes?: string[];
    total?: number;
  }>;
  return {
    taskId: String(json.data?.taskId || opts.taskId || ''),
    bucket: String(json.data?.bucket || opts.bucket),
    codes: Array.isArray(json.data?.codes) ? json.data.codes : [],
    total: Number(json.data?.total || 0),
  };
}

export async function fetchScrapeExportDetail(
  code: string,
  signal?: AbortSignal,
): Promise<ScrapeExportDetail> {
  const q = new URLSearchParams({ code: String(code || '').trim() });
  const res = await apiFetch(`/scrape/export/detail?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportDetail>;
  return json.data;
}

export async function fetchScrapeExportEvents(
  code: string,
  signal?: AbortSignal,
): Promise<ScrapeExportEvent[]> {
  const q = new URLSearchParams({ code: String(code || '').trim() });
  const res = await apiFetch(`/scrape/export/events?${q}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    code?: string;
    events?: ScrapeExportEvent[];
  }>;
  return Array.isArray(json.data?.events) ? json.data.events : [];
}

export async function startScrapeExport(body: {
  taskId?: string;
  name?: string;
  region?: string;
  regions?: string[];
  maker?: string;
  prefix?: string;
  code?: string;
  /** 多番号强制重刮（与 code 合并） */
  codes?: string[];
  force?: boolean;
  mode?: 'incremental' | 'force';
  /** 失败重试：后端清失败队列并只强制重刮失败番号 */
  retryFailed?: boolean;
  fields?: ScrapeTaskField[];
  localFields?: ScrapeTaskField[];
  signal?: AbortSignal;
}): Promise<ScrapeExportStatus> {
  const { signal, ...payload } = body;
  const res = await apiFetch('/scrape/export', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

export async function pauseScrapeExport(): Promise<ScrapeExportStatus> {
  const res = await apiFetch('/scrape/export/pause', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

export async function resumeScrapeExport(): Promise<ScrapeExportStatus> {
  const res = await apiFetch('/scrape/export/resume', { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

export async function clearScrapeExport(opts?: {
  taskId?: string;
}): Promise<ScrapeExportStatus> {
  const q = new URLSearchParams();
  const tid = String(opts?.taskId || '').trim();
  if (tid) q.set('taskId', tid);
  const qs = q.toString();
  const res = await apiFetch(`/scrape/export${qs ? `?${qs}` : ''}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

/** 重置任务卡：清该任务断点续跑，避免再次开始只刮残留几条 */
export async function resetScrapeExportCheckpoint(
  taskId: string,
): Promise<ScrapeExportStatus> {
  const tid = String(taskId || '').trim();
  if (!tid) throw new Error('缺少 taskId');
  const q = new URLSearchParams({ taskId: tid });
  const res = await apiFetch(`/scrape/export/reset-checkpoint?${q}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

/** 删除任务卡：清理该任务 SQLite 过程日志与结果番号 */
export async function purgeScrapeTaskLogs(
  taskId: string,
): Promise<{ taskId: string; events: number; codes: number }> {
  const tid = String(taskId || '').trim();
  if (!tid) throw new Error('缺少 taskId');
  const q = new URLSearchParams({ taskId: tid });
  const res = await apiFetch(`/scrape/export/purge-task?${q}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    taskId?: string;
    events?: number;
    codes?: number;
  }>;
  return {
    taskId: String(json.data?.taskId || tid),
    events: Number(json.data?.events || 0),
    codes: Number(json.data?.codes || 0),
  };
}

export async function cancelScrapeExportTask(
  taskId: string,
): Promise<ScrapeExportStatus> {
  const tid = String(taskId || '').trim();
  if (!tid) throw new Error('缺少 taskId');
  const q = new URLSearchParams({ taskId: tid });
  const res = await apiFetch(`/scrape/export/cancel?${q}`, { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportStatus>;
  return json.data;
}

export async function waitScrapeExport(opts?: {
  signal?: AbortSignal;
  intervalMs?: number;
  onTick?: (st: ScrapeExportStatus) => void;
}): Promise<ScrapeExportStatus> {
  const interval = Math.max(400, opts?.intervalMs ?? 900);
  const okIdle = new Set([
    'ok',
    'building',
    'queued',
    'scraping',
    'paused',
    'cancelling',
    'cancelled',
    'interrupted',
    '',
  ]);
  for (;;) {
    if (opts?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const st = await fetchScrapeExportStatus(opts?.signal);
    opts?.onTick?.(st);
    if (!st.running) {
      const msg = String(st.message || 'ok');
      if (msg && !okIdle.has(msg) && !msg.includes('无待刮削')) {
        throw new Error(msg);
      }
      return st;
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export async function previewScrapeExport(opts?: {
  region?: string;
  regions?: string[];
  maker?: string;
  prefix?: string;
  code?: string;
  signal?: AbortSignal;
}): Promise<ScrapeExportPreview> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  for (const r of opts?.regions || []) {
    if (r) q.append('regions', r);
  }
  if (opts?.maker) q.set('maker', opts.maker);
  if (opts?.prefix) q.set('prefix', opts.prefix);
  if (opts?.code) q.set('code', opts.code);
  const qs = q.toString();
  const res = await apiFetch(
    `/scrape/export/preview${qs ? `?${qs}` : ''}`,
    { signal: opts?.signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<ScrapeExportPreview>;
  return json.data;
}

export const testFlareSolverr = testScrapeFlareSolverr;


export type MakerFsRegionSummary = {
  id: string;
  label: string;
  dbRegion?: string;
  navPath?: string;
  prefixCount: number;
  makerCount?: number;
  codeCount?: number;
  dir?: string;
};

export type MakerFsManifest = {
  version: number;
  ready: boolean;
  updatedAt?: string;
  prefixCount?: number;
  coverCount?: number;
  root?: string;
  source?: string;
  scope?: string;
  regions?: MakerFsRegionSummary[];
};

export type MakerFsRegionsOverview = {
  version: number;
  updatedAt?: string;
  regionCount: number;
  regions: MakerFsRegionSummary[];
  ready?: boolean;
};

export type MakerFsRegionCatalog = {
  version: number;
  id: string;
  label: string;
  dbRegion?: string;
  navPath?: string;
  updatedAt?: string;
  prefixCount: number;
  makerCount?: number;
  codeCount?: number;
  prefixes: Array<{
    prefix: string;
    name?: string;
    type_name?: string;
    board_name?: string;
    path?: string[];
    codeCount?: number;
    custom?: boolean;
    /** 规范数字位数（抽码截断；欧美区不用） */
    pad?: number;
    padLocked?: boolean;
    /** digit_pad | western_date | fc2 | fc2ppv | date6 | alnum_id | fixed_std */
    codeFormat?: string;
    /** 后端按前缀配置检测；仅 digit_pad 可改位数 */
    padEditable?: boolean;
    shape?: string;
    /** 例：EBWH-001 / BLACKED.2026.01.15 / FC2-PPV-1234567 / CARIB-260115-001 */
    codeSample?: string;
    /** 片库聚合：女优（索引/刮削） */
    actors?: string[];
    /** 片库聚合：刮削标签 */
    tags?: string[];
    /** 片库聚合：系列 */
    series?: string[];
    /** 前缀代表作番号（卡片封面来源） */
    coverCode?: string;
    coverUrl?: string | null;
    coverUrls?: string[];
    posterLocal?: string | null;
    posterRev?: string | null;
  }>;
};

export type MakerFsRegionBuildProgress = {
  done?: number;
  total?: number;
  covers?: number;
  currentPrefix?: string;
  updatedAt?: string;
};

export type MakerFsAutoDailyConfig = {
  enabled: boolean;
  lastRunDate?: string;
  lastRunAt?: string;
  lastError?: string;
  starting?: boolean;
  lastResult?: {
    build?: { prefixes?: number; covers?: number; skipped?: number };
    materialize?: {
      written?: number;
      updated?: number;
      skipped?: number;
      total?: number;
    };
  } | null;
};

export type MakerFsBuildStatus = {
  running: boolean;
  startedAt?: string;
  finishedAt?: string;
  message?: string;
  phase?: string;
  prefixes?: number;
  prefixTotal?: number;
  covers?: number;
  skipped?: number;
  workers?: number;
  region?: string;
  currentPrefix?: string;
  updatedAt?: string;
  error?: string | null;
  ready?: boolean;
  regionProgress?: Record<string, MakerFsRegionBuildProgress>;
  autoDaily?: MakerFsAutoDailyConfig;
};

export type MakerFsPrefixCodeItem = {
  code: string;
  coverUrl?: string | null;
  coverUrls?: string[] | null;
  forumTitle?: string | null;
  forumActors?: string[] | null;
  source?: 'sehua' | 'bit';
  /** 刮削标签 */
  genres?: string[] | null;
  /** library 内刮削海报相对路径（优先展示） */
  posterLocal?: string | null;
  /** poster 文件版本（mtime-size），用于缓存破坏 */
  posterRev?: string | null;
  scraped?: boolean;
};

export type MakerFsPrefixCodesResult = {
  prefix: string;
  region?: string;
  total: number;
  offset: number;
  limit: number;
  items: MakerFsPrefixCodeItem[];
  /** 规范位数（digit_pad） */
  pad?: number;
  /** 样例：PREFIX-001 */
  codeSample?: string;
  updatedAt?: string;
  source?: string;
};

export async function fetchMakerFsManifest(
  signal?: AbortSignal,
): Promise<MakerFsManifest> {
  const res = await apiFetch('/maker-fs/manifest', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsManifest>).data;
}

export async function fetchMakerFsStatus(
  signal?: AbortSignal,
): Promise<MakerFsBuildStatus> {
  const res = await apiFetch('/maker-fs/status', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsBuildStatus>).data;
}

export async function fetchMakerFsAutoDaily(
  signal?: AbortSignal,
): Promise<MakerFsAutoDailyConfig> {
  const res = await apiFetch('/maker-fs/auto-daily', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsAutoDailyConfig>).data;
}

export async function putMakerFsAutoDaily(
  enabled: boolean,
  signal?: AbortSignal,
): Promise<MakerFsAutoDailyConfig> {
  const res = await apiFetch('/maker-fs/auto-daily', {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
    signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsAutoDailyConfig>).data;
}

export async function waitMakerFsBuild(opts?: {
  signal?: AbortSignal;
  intervalMs?: number;
  onTick?: (st: MakerFsBuildStatus) => void;
}): Promise<MakerFsBuildStatus> {
  const interval = Math.max(400, opts?.intervalMs ?? 900);
  for (;;) {
    if (opts?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const st = await fetchMakerFsStatus(opts?.signal);
    opts?.onTick?.(st);
    if (!st.running) {
      const msg = String(st.message || 'ok');
      // 整单失败才抛；「完成但有失败/触顶」仍返回给 UI 展示
      if (
        msg &&
        msg !== 'ok' &&
        msg !== 'building' &&
        msg !== 'queued' &&
        msg !== 'cancelling' &&
        !msg.startsWith('完成') &&
        !msg.startsWith('已取消')
      ) {
        throw new Error(msg);
      }
      return st;
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export async function fetchMakerFsRegions(
  signal?: AbortSignal,
): Promise<MakerFsRegionsOverview> {
  const res = await apiFetch('/maker-fs/regions', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionsOverview>).data;
}

export async function fetchMakerFsRegion(
  regionId: string,
  signal?: AbortSignal,
): Promise<MakerFsRegionCatalog> {
  const res = await apiFetch(`/maker-fs/regions/${encodeURIComponent(regionId)}`, {
    signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionCatalog>).data;
}

export async function addMakerFsRegionPrefix(opts: {
  regionId: string;
  prefix: string;
  boardName?: string;
  name?: string;
  signal?: AbortSignal;
}): Promise<MakerFsRegionCatalog> {
  const res = await apiFetch(
    `/maker-fs/regions/${encodeURIComponent(opts.regionId)}/prefixes`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prefix: opts.prefix,
        board_name: opts.boardName || '',
        name: opts.name || '',
      }),
      signal: opts.signal,
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionCatalog>).data;
}

export async function removeMakerFsRegionPrefix(opts: {
  regionId: string;
  prefix: string;
  signal?: AbortSignal;
}): Promise<MakerFsRegionCatalog> {
  const res = await apiFetch(
    `/maker-fs/regions/${encodeURIComponent(opts.regionId)}/prefixes/${encodeURIComponent(opts.prefix)}`,
    { method: 'DELETE', signal: opts.signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionCatalog>).data;
}

export async function resetMakerFsRegionPrefixes(
  regionId: string,
  signal?: AbortSignal,
): Promise<MakerFsRegionCatalog> {
  const res = await apiFetch(
    `/maker-fs/regions/${encodeURIComponent(regionId)}/prefixes/reset`,
    { method: 'POST', signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionCatalog>).data;
}

export async function fetchMakerFsPrefixCodes(opts: {
  prefix: string;
  region?: string;
  offset?: number;
  limit?: number;
  q?: string;
  signal?: AbortSignal;
}): Promise<MakerFsPrefixCodesResult | null> {
  const q = new URLSearchParams();
  if (opts.region) q.set('region', opts.region);
  q.set('offset', String(opts.offset ?? 0));
  q.set('limit', String(opts.limit ?? 100));
  const needle = String(opts.q || '').trim();
  if (needle) q.set('q', needle);
  const res = await apiFetch(
    `/maker-fs/prefixes/${encodeURIComponent(opts.prefix)}/codes?${q}`,
    { signal: opts.signal },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsPrefixCodesResult>).data;
}

export type PrefixResourceHit = {
  code: string;
  coverUrl: string | null;
  coverUrls: string[];
};

export type PrefixRangeResult = {
  prefix: string;
  from: number;
  to: number;
  pad: number;
  total: number;
  db_max?: number | null;
  source?: string;
  updated?: string;
  skip?: boolean;
  padLocked?: boolean;
  /** 规范样例，如 SONE-001 */
  sample?: string;
};

export type PrefixCoversResult = {
  prefix: string;
  items: PrefixResourceHit[];
};

export type MakerFsPrefixRange = PrefixRangeResult & {
  region?: string;
  updatedAt?: string;
};

export async function fetchPrefixRange(opts: {
  prefix: string;
  signal?: AbortSignal;
}): Promise<PrefixRangeResult> {
  const q = new URLSearchParams();
  q.set('prefix', opts.prefix);
  const res = await apiFetch(`/prefix-range?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixRangeResult>).data;
}

export async function fetchPrefixCovers(opts: {
  prefix: string;
  codes: string[];
  region?: string;
  signal?: AbortSignal;
}): Promise<PrefixCoversResult> {
  const q = new URLSearchParams();
  q.set('prefix', opts.prefix);
  q.set('codes', opts.codes.join(','));
  if (opts.region) q.set('region', opts.region);
  const res = await apiFetch(`/prefix-covers?${q}`, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCoversResult>).data;
}

export async function fetchMakerFsPrefixRange(opts: {
  prefix: string;
  region?: string;
  signal?: AbortSignal;
}): Promise<MakerFsPrefixRange | null> {
  const q = new URLSearchParams();
  if (opts.region) q.set('region', opts.region);
  const qs = q.toString();
  const res = await apiFetch(
    `/maker-fs/prefixes/${encodeURIComponent(opts.prefix)}/range${qs ? `?${qs}` : ''}`,
    { signal: opts.signal },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsPrefixRange>).data;
}

export async function putMakerFsPrefixRange(opts: {
  prefix: string;
  pad: number;
  lock?: boolean;
  region?: string;
  signal?: AbortSignal;
}): Promise<MakerFsPrefixRange> {
  const q = new URLSearchParams();
  q.set('pad', String(opts.pad));
  q.set('lock', opts.lock === false ? '0' : '1');
  if (opts.region) q.set('region', opts.region);
  const res = await apiFetch(
    `/maker-fs/prefixes/${encodeURIComponent(opts.prefix)}/range?${q}`,
    { method: 'PUT', signal: opts.signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsPrefixRange>).data;
}

export async function fetchMakerFsPrefixCovers(opts: {
  prefix: string;
  codes: string[];
  region?: string;
  signal?: AbortSignal;
}): Promise<PrefixCoversResult | null> {
  const q = new URLSearchParams();
  q.set('codes', opts.codes.join(','));
  if (opts.region) q.set('region', opts.region);
  const res = await apiFetch(
    `/maker-fs/prefixes/${encodeURIComponent(opts.prefix)}/covers?${q}`,
    { signal: opts.signal },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<PrefixCoversResult>).data;
}

/** 触发本地索引构建（后台）；sync=true 同步跑完（调试） */
export async function buildMakerFs(opts?: {
  limit?: number;
  maxCovers?: number;
  sync?: boolean;
  catalogsOnly?: boolean;
  workers?: number;
  skipFreshHours?: number;
  force?: boolean;
  region?: string;
  /** 单前缀强制重扫（须同时传 region） */
  prefix?: string;
  signal?: AbortSignal;
}): Promise<unknown> {
  const q = new URLSearchParams();
  if (opts?.limit) q.set('limit', String(opts.limit));
  if (opts?.maxCovers) q.set('maxCovers', String(opts.maxCovers));
  if (opts?.sync) q.set('sync', '1');
  if (opts?.catalogsOnly) q.set('catalogsOnly', '1');
  if (opts?.workers) q.set('workers', String(opts.workers));
  if (opts?.skipFreshHours != null) {
    q.set('skipFreshHours', String(opts.skipFreshHours));
  }
  if (opts?.force) q.set('force', '1');
  if (opts?.region) q.set('region', opts.region);
  if (opts?.prefix) q.set('prefix', opts.prefix);
  const res = await apiFetch(`/maker-fs/build?${q}`, {
    method: 'POST',
    signal: opts?.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<unknown>).data;
}

/** 本地片库同步状态 */
export type LibraryMaterializeStatus = {
  running: boolean;
  startedAt?: string;
  finishedAt?: string;
  message?: string;
  region?: string;
  total?: number;
  done?: number;
  written?: number;
  skipped?: number;
  updated?: number;
  removed?: number;
  errors?: number;
  currentCode?: string;
  updatedAt?: string;
};

export async function fetchLibraryMaterializeStatus(
  signal?: AbortSignal,
): Promise<LibraryMaterializeStatus> {
  // 防缓存：否则第二次同步会读到上一次 running:false / ok，误判完成或立刻抛错
  const q = `?_=${Date.now()}`;
  const res = await apiFetch(`/scrape/library/status${q}`, {
    signal,
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<LibraryMaterializeStatus>).data;
}

export async function materializeLibrary(opts?: {
  region?: string;
  sync?: boolean;
  /** 强制抢占僵死的同步任务 */
  force?: boolean;
  signal?: AbortSignal;
}): Promise<LibraryMaterializeStatus> {
  const q = new URLSearchParams();
  if (opts?.region) q.set('region', opts.region);
  if (opts?.sync) q.set('sync', '1');
  if (opts?.force) q.set('force', '1');
  const res = await apiFetch(`/scrape/library/materialize?${q}`, {
    method: 'POST',
    signal: opts?.signal,
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<LibraryMaterializeStatus>).data;
}

export async function waitLibraryMaterialize(opts?: {
  signal?: AbortSignal;
  intervalMs?: number;
  /** 本次任务 claim 返回的 startedAt；避免误用上一次的 ok 状态 */
  expectStartedAt?: string;
  onTick?: (st: LibraryMaterializeStatus) => void;
}): Promise<LibraryMaterializeStatus> {
  const interval = Math.max(400, opts?.intervalMs ?? 900);
  const expect = String(opts?.expectStartedAt || '').trim();
  let sawRunning = false;
  for (;;) {
    if (opts?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const st = await fetchLibraryMaterializeStatus(opts?.signal);
    opts?.onTick?.(st);
    if (st.running) {
      sawRunning = true;
    } else {
      const started = String(st.startedAt || '').trim();
      const finished = String(st.finishedAt || '').trim();
      const msg = String(st.message || 'ok');
      // 还在等本轮任务登记/跑完：startedAt 对不上时继续轮询
      if (expect && started && started !== expect) {
        await new Promise((r) => setTimeout(r, interval));
        continue;
      }
      if (expect && !sawRunning && !finished) {
        await new Promise((r) => setTimeout(r, interval));
        continue;
      }
      // queued 已改为「收集索引…」；兼容旧文案
      if (msg === 'queued' || msg === '收集索引…') {
        throw new Error(msg === 'queued' ? '收集索引超时，请重试' : `${msg}超时，请重试`);
      }
      if (msg !== 'ok') {
        throw new Error(msg);
      }
      return st;
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export async function fetchLibraryRegions(
  signal?: AbortSignal,
): Promise<MakerFsRegionsOverview> {
  const res = await apiFetch('/scrape/library/regions', { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionsOverview>).data;
}

export async function fetchLibraryRegion(
  regionId: string,
  signal?: AbortSignal,
): Promise<MakerFsRegionCatalog> {
  const res = await apiFetch(
    `/scrape/library/regions/${encodeURIComponent(regionId)}`,
    { signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsRegionCatalog>).data;
}

export async function fetchLibraryCodes(opts: {
  region: string;
  studio: string;
  prefix: string;
  offset?: number;
  limit?: number;
  q?: string;
  signal?: AbortSignal;
}): Promise<MakerFsPrefixCodesResult> {
  const q = new URLSearchParams();
  q.set('region', opts.region);
  q.set('studio', opts.studio);
  q.set('prefix', opts.prefix);
  if (opts.offset != null) q.set('offset', String(opts.offset));
  if (opts.limit != null) q.set('limit', String(opts.limit));
  if (opts.q) q.set('q', opts.q);
  const res = await apiFetch(`/scrape/library/codes?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MakerFsPrefixCodesResult>).data;
}

export type LibraryFacetItem = {
  name: string;
  count: number;
};

export type LibraryRegionFacets = {
  id: string;
  label: string;
  updatedAt?: string | null;
  scanned?: number;
  reused?: number;
  updated?: number;
  /** 片商目录 catalog 聚合女优 */
  actors?: LibraryFacetItem[];
  tags: LibraryFacetItem[];
  series: LibraryFacetItem[];
  source?: string;
  empty?: boolean;
  stale?: boolean;
};

export type LibraryFacetCodeItem = MakerFsPrefixCodeItem & {
  studio?: string;
  prefix?: string;
};

export type LibraryFacetCodesResult = {
  region: string;
  kind: 'tag' | 'series' | string;
  value: string;
  total: number;
  offset: number;
  limit: number;
  items: LibraryFacetCodeItem[];
  updatedAt?: string;
  source?: string;
};

export async function fetchLibraryRegionFacets(
  regionId: string,
  opts?: { rebuild?: boolean; sync?: boolean; signal?: AbortSignal },
): Promise<LibraryRegionFacets> {
  const q = new URLSearchParams();
  if (opts?.rebuild) q.set('rebuild', '1');
  if (opts?.sync) q.set('sync', '1');
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(
    `/scrape/library/regions/${encodeURIComponent(regionId)}/facets${suffix}`,
    { signal: opts?.signal },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<LibraryRegionFacets>).data;
}

export async function fetchLibraryFacetCodes(opts: {
  region: string;
  kind: 'tag' | 'series' | string;
  value: string;
  offset?: number;
  limit?: number;
  signal?: AbortSignal;
}): Promise<LibraryFacetCodesResult> {
  const q = new URLSearchParams();
  q.set('region', opts.region);
  q.set('kind', opts.kind);
  q.set('value', opts.value);
  if (opts.offset != null) q.set('offset', String(opts.offset));
  if (opts.limit != null) q.set('limit', String(opts.limit));
  const res = await apiFetch(`/scrape/library/facet-codes?${q}`, {
    signal: opts.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<LibraryFacetCodesResult>).data;
}

/* —— Media (TMDB / 豆瓣) —— */

export type MediaSourceId = 'tmdb' | 'douban';
export type MediaCategoryId = 'movie' | 'tv' | 'anime' | 'variety';

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
  cast?: string[];
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
      : `/media/tmdb/charts?${q}`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaChartResult>).data;
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
      : `/media/tmdb/${encodeURIComponent(opts.mediaType || 'movie')}/${encodeURIComponent(opts.id)}`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaItem>).data;
}

export async function fetchMediaRelated(opts: {
  mediaType: 'movie' | 'tv';
  id: string;
  signal?: AbortSignal;
}): Promise<MediaRelatedResult> {
  const path = `/media/tmdb/${encodeURIComponent(opts.mediaType)}/${encodeURIComponent(opts.id)}/related`;
  const res = await apiFetch(path, { signal: opts.signal });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<MediaRelatedResult>).data;
}
