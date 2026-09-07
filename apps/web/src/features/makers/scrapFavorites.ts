import type { MakerCatalogSourceId, ScrapLibraryEmbedItem } from '@/lib/api';
import { makerSourceLabel } from './makersUi';

const STORAGE_KEY = 'nextweb:scrap-favorites';

/** 与后端 region_meta / 库内 region 列对齐的别名 */
const REGION_ALIAS_MAP: Record<string, string[]> = {
  japan_censored: ['japan_censored', '日本有码', '有码'],
  japan_uncensored: ['japan_uncensored', '日本无码', '无码'],
  japan_amateur: ['japan_amateur', '日本素人', '素人'],
  japan_gravure: ['japan_gravure', '日本写真', '写真'],
  fc2: ['fc2', 'FC2'],
  china: ['china', '国产', '国产无码'],
  western: ['western', '欧美', '欧美无码'],
};

export type ScrapFavorite = ScrapLibraryEmbedItem & {
  favoritedAt: number;
  /** 收藏时所在片商 Tab（japan_censored 等） */
  hubRegion?: string;
};

function readAll(): ScrapFavorite[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row): row is ScrapFavorite => {
        if (!row || typeof row !== 'object') return false;
        const id = String((row as ScrapFavorite).itemId || '').trim();
        return Boolean(id);
      })
      .map((row) => ({
        ...row,
        favoritedAt: Number(row.favoritedAt) || 0,
      }));
  } catch {
    return [];
  }
}

function writeAll(rows: ScrapFavorite[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
}

export function favoriteRegionAliases(
  hubTab: MakerCatalogSourceId,
  label?: string,
): string[] {
  const mapped = REGION_ALIAS_MAP[hubTab] || [];
  const extra = [hubTab, label, makerSourceLabel(hubTab)].filter(Boolean) as string[];
  return [...new Set([...mapped, ...extra])];
}

function regionMatches(row: ScrapFavorite, keys: Set<string>): boolean {
  const candidates = [
    row.hubRegion,
    row.region,
  ]
    .map((s) => String(s || '').trim())
    .filter(Boolean);
  if (candidates.length === 0) return true;
  return candidates.some((c) => keys.has(c));
}

/** region 可能是 japan_censored / 有码 / 日本有码 */
export function listScrapFavorites(
  region?: string,
  aliases: string[] = [],
): ScrapFavorite[] {
  const all = readAll();
  const hub = String(region || '').trim() as MakerCatalogSourceId;
  const keys = new Set(
    [
      ...favoriteRegionAliases(hub),
      ...aliases,
    ]
      .map((s) => String(s || '').trim())
      .filter(Boolean),
  );
  const filtered =
    keys.size === 0 ? all : all.filter((r) => regionMatches(r, keys));
  return [...filtered].sort((a, b) => (b.favoritedAt || 0) - (a.favoritedAt || 0));
}

export function isScrapFavorite(itemId?: string | null): boolean {
  const id = String(itemId || '').trim();
  if (!id) return false;
  return readAll().some((r) => r.itemId === id);
}

export function toggleScrapFavorite(
  item: ScrapLibraryEmbedItem,
  hubRegion?: string,
): boolean {
  const id = String(item.itemId || '').trim();
  if (!id) return false;
  const all = readAll();
  const idx = all.findIndex((r) => r.itemId === id);
  if (idx >= 0) {
    all.splice(idx, 1);
    writeAll(all);
    return false;
  }
  const next: ScrapFavorite = {
    ...item,
    itemId: id,
    favoritedAt: Date.now(),
    hubRegion: String(hubRegion || '').trim() || undefined,
  };
  writeAll([next, ...all]);
  return true;
}
