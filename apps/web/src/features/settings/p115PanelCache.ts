/** 115 转存面板缓存：避免每次进入都「读取中…」 */

import type {
  P115Config,
  P115TargetFolder,
  P115Task,
  P115SaveSource,
} from '@/lib/api';
import { P115_MAKER_REGION_SOURCES } from '@/lib/api';

export type P115PanelTab = 'overview' | 'config' | 'tasks';

export type P115PanelSnapshot = {
  at: number;
  configured: boolean;
  hint: string;
  targets: Record<P115SaveSource, P115TargetFolder>;
  subsFolder: P115TargetFolder;
  subsLayered: boolean;
  tab: P115PanelTab;
  quota: number | null;
  quotaTotal: number | null;
  quotaError: string;
  spaceUsedText: string;
  spaceTotalText: string;
  spaceRemainText: string;
  spaceUsed: number | null;
  spaceTotal: number | null;
  tasks: P115Task[];
  tasksLoaded: boolean;
  tasksError: string;
};

const TTL_MS = 120_000;

let cache: P115PanelSnapshot | null = null;

export function getP115PanelCache(): P115PanelSnapshot | null {
  return cache;
}

export function isP115PanelCacheFresh(ttlMs = TTL_MS): boolean {
  return cache != null && Date.now() - cache.at < ttlMs;
}

export function setP115PanelCache(next: Omit<P115PanelSnapshot, 'at'>): void {
  cache = { ...next, at: Date.now() };
}

export function patchP115PanelCache(
  patch: Partial<Omit<P115PanelSnapshot, 'at'>>,
): void {
  if (!cache) return;
  cache = { ...cache, ...patch, at: Date.now() };
}

export function clearP115PanelCache(): void {
  cache = null;
}

export function emptyP115Targets(): Record<P115SaveSource, P115TargetFolder> {
  const base = {
    warehouse: { folderCid: '0', folderName: '' },
    movie: { folderCid: '0', folderName: '' },
    tv: { folderCid: '0', folderName: '' },
  } as Record<P115SaveSource, P115TargetFolder>;
  for (const key of P115_MAKER_REGION_SOURCES) {
    base[key] = { folderCid: '0', folderName: '' };
  }
  return base;
}

export function emptyP115SubsFolder(): P115TargetFolder {
  return { folderCid: '0', folderName: '' };
}

/** 从 getP115 结果写一版最小缓存（无配额时） */
export function cacheFromP115Config(
  data: P115Config,
  targets: Record<P115SaveSource, P115TargetFolder>,
  prev?: P115PanelSnapshot | null,
): void {
  setP115PanelCache({
    configured: Boolean(data.configured),
    hint: data.cookieHint || '',
    targets,
    subsFolder: data.subsFolder || prev?.subsFolder || emptyP115SubsFolder(),
    subsLayered: data.subsLayered ?? prev?.subsLayered ?? true,
    tab: prev?.tab && data.configured ? prev.tab : data.configured ? 'overview' : 'config',
    quota: data.quota ?? prev?.quota ?? null,
    quotaTotal: data.quotaTotal ?? prev?.quotaTotal ?? null,
    quotaError: data.quotaError || prev?.quotaError || '',
    spaceUsedText: String(data.spaceUsedText ?? prev?.spaceUsedText ?? ''),
    spaceTotalText: String(data.spaceTotalText ?? prev?.spaceTotalText ?? ''),
    spaceRemainText: String(data.spaceRemainText ?? prev?.spaceRemainText ?? ''),
    spaceUsed: data.spaceUsed ?? prev?.spaceUsed ?? null,
    spaceTotal: data.spaceTotal ?? prev?.spaceTotal ?? null,
    tasks: prev?.tasks ?? [],
    tasksLoaded: prev?.tasksLoaded ?? false,
    tasksError: prev?.tasksError ?? '',
  });
}
