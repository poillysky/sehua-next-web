/**
 * 115 网盘（含任务清理、二维码登录）
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

export type P115MakerRegionSource =
  | 'japan_censored'
  | 'japan_uncensored'
  | 'japan_amateur'
  | 'fc2'
  | 'china'
  | 'western';

/** 115 转存入口：仓库 / 影视 + 片商六区（旧 `makers` 仅作兼容别名） */
export type P115SaveSource =
  | 'warehouse'
  | 'movie'
  | 'tv'
  | P115MakerRegionSource;

/** @deprecated 已拆为六区；读配置时仍可映射到各区 */
export type P115LegacySaveSource = 'makers' | 'media';

export const P115_MAKER_REGION_SOURCES: P115MakerRegionSource[] = [
  'japan_censored',
  'japan_uncensored',
  'japan_amateur',
  'fc2',
  'china',
  'western',
];

export type P115TargetFolder = {
  folderCid: string;
  folderName: string;
};

export type P115Config = {
  enabled: boolean;
  folderCid: string;
  folderName: string;
  label: string;
  targets?: Partial<
    Record<P115SaveSource | P115LegacySaveSource, P115TargetFolder>
  >;
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
  targets?: Partial<
    Record<P115SaveSource | P115LegacySaveSource, P115TargetFolder>
  >;
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
