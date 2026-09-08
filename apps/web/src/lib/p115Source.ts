'use client';

import type { P115SaveSource } from '@/lib/api';

/** 继承类保存来源：影视（movie/tv）/ 片商（makers）跳转仓库后写入，
 *  仓库默认态 warehouse 不属于"继承来源"，不入此标记。 */
export type InheritedSaveSource = Exclude<P115SaveSource, 'warehouse'>;

export const P115_SAVE_SOURCE_KEY = 'nextweb:p115-save-source';

/** 顺序与 P115SaveSource 对齐，用于展示/切换 */
export const P115_SOURCE_ORDER: P115SaveSource[] = [
  'warehouse',
  'movie',
  'tv',
  'makers',
];

/** 保存来源 → 中文名（转存落点展示用） */
export const P115_SOURCE_LABEL: Record<P115SaveSource, string> = {
  warehouse: '仓库',
  movie: '电影',
  tv: '电视剧',
  makers: '片商',
};

const INHERITED_SET: ReadonlySet<string> = new Set(['movie', 'tv', 'makers']);

function isInheritedSource(s: string | null): s is InheritedSaveSource {
  return s != null && INHERITED_SET.has(s);
}

/** 兼容旧写入的 `media` 别名 → movie */
function normalizeRaw(raw: string | null): P115SaveSource | null {
  if (raw === 'media') return 'movie';
  if (
    raw === 'warehouse' ||
    raw === 'movie' ||
    raw === 'tv' ||
    raw === 'makers'
  ) {
    return raw;
  }
  return null;
}

/** 读取继承的保存来源（仅 movie/tv/makers）；warehouse 视为未继承 */
export function readInheritedSaveSource(): InheritedSaveSource | null {
  try {
    const s = normalizeRaw(sessionStorage.getItem(P115_SAVE_SOURCE_KEY));
    return isInheritedSource(s) ? s : null;
  } catch {
    return null;
  }
}

/** 读取完整保存来源（含显式 warehouse / 兼容 media），读不到返回 fallback */
export function readSaveSource(fallback: P115SaveSource): P115SaveSource {
  try {
    return normalizeRaw(sessionStorage.getItem(P115_SAVE_SOURCE_KEY)) ?? fallback;
  } catch {
    return fallback;
  }
}

/** 写入保存来源（供影视/片商跳转仓库时调用） */
export function writeSaveSource(source: InheritedSaveSource | 'warehouse'): void {
  try {
    sessionStorage.setItem(P115_SAVE_SOURCE_KEY, source);
  } catch {
    /* ignore */
  }
}

/** 清除保存来源（回到 warehouse 默认态） */
export function clearSaveSource(): void {
  try {
    sessionStorage.removeItem(P115_SAVE_SOURCE_KEY);
  } catch {
    /* ignore */
  }
}
