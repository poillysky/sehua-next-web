'use client';

import type { P115MakerRegionSource, P115SaveSource } from '@/lib/api';
import { P115_MAKER_REGION_SOURCES } from '@/lib/api';
import { clearP115AttachSubs, readP115AttachSubs } from '@/lib/p115AttachSubs';

/** 继承类保存来源：影视 / 片商六区跳转仓库后写入，
 *  仓库默认态 warehouse 不属于"继承来源"，不入此标记。 */
export type InheritedSaveSource = Exclude<P115SaveSource, 'warehouse'>;

export const P115_SAVE_SOURCE_KEY = 'nextweb:p115-save-source';

/** 顺序与 P115SaveSource 对齐，用于展示/切换 */
export const P115_SOURCE_ORDER: P115SaveSource[] = [
  'warehouse',
  'movie',
  'tv',
  ...P115_MAKER_REGION_SOURCES,
];

/** 保存来源 → 中文名（转存落点展示用） */
export const P115_SOURCE_LABEL: Record<P115SaveSource, string> = {
  warehouse: '仓库',
  movie: '电影',
  tv: '电视剧',
  japan_censored: '日本有码',
  japan_uncensored: '日本无码',
  japan_amateur: '素人',
  fc2: 'FC2',
  china: '国产',
  western: '欧美',
};

const INHERITED_SET: ReadonlySet<string> = new Set([
  'movie',
  'tv',
  ...P115_MAKER_REGION_SOURCES,
]);

function isInheritedSource(s: string | null): s is InheritedSaveSource {
  return s != null && INHERITED_SET.has(s);
}

function isMakerRegion(raw: string): raw is P115MakerRegionSource {
  return (P115_MAKER_REGION_SOURCES as string[]).includes(raw);
}

/** 兼容旧写入的 `media` → movie；`makers` → japan_censored */
function normalizeRaw(raw: string | null): P115SaveSource | null {
  if (raw === 'media') return 'movie';
  if (raw === 'makers') return 'japan_censored';
  if (raw === 'warehouse' || raw === 'movie' || raw === 'tv') return raw;
  if (raw && isMakerRegion(raw)) return raw;
  return null;
}

/** 刮削区 id / 标签 → 115 片商入口 */
export function p115SourceFromRegion(
  region: string | null | undefined,
): P115MakerRegionSource {
  const raw = String(region || '').trim().toLowerCase();
  if (!raw) return 'japan_censored';
  if (isMakerRegion(raw)) return raw;
  if (raw === 'japan_gravure' || raw === 'gravure' || raw.includes('有码')) {
    return 'japan_censored';
  }
  if (raw.includes('无码') && (raw.includes('日本') || raw === 'uncensored')) {
    return 'japan_uncensored';
  }
  if (raw.includes('素人') || raw === 'amateur') return 'japan_amateur';
  if (raw.includes('fc2')) return 'fc2';
  if (raw.includes('国产') || raw === 'china' || raw === 'domestic') return 'china';
  if (raw.includes('欧美') || raw === 'western' || raw === 'europe') return 'western';
  if (raw.includes('无码')) return 'japan_uncensored';
  return 'japan_censored';
}

/** 读取继承的保存来源（仅 movie/tv/六区）；warehouse 视为未继承 */
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

/**
 * 转存落点：override > session 继承 > 片商 attach.region 兜底 > warehouse。
 * 片商跳转后若 session 被清，仍可用 attach 里的分区。
 */
export function resolveP115SaveSource(
  override?: P115SaveSource | null,
): P115SaveSource {
  if (override) return override;
  const fromSession = readSaveSource('warehouse');
  if (fromSession !== 'warehouse') return fromSession;
  const region = readP115AttachSubs()?.region;
  if (region) return p115SourceFromRegion(region);
  return 'warehouse';
}

/** 写入保存来源（供影视/片商跳转仓库时调用） */
export function writeSaveSource(source: InheritedSaveSource | 'warehouse'): void {
  try {
    sessionStorage.setItem(P115_SAVE_SOURCE_KEY, source);
  } catch {
    /* ignore */
  }
}

/** 清除保存来源（回到 warehouse 默认态）；同步清片商 attach */
export function clearSaveSource(): void {
  try {
    sessionStorage.removeItem(P115_SAVE_SOURCE_KEY);
  } catch {
    /* ignore */
  }
  clearP115AttachSubs();
}
