import type { MakerCatalogSourceId, ScrapLibraryEmbedItem } from '@/lib/api';
import {
  addScrapFavoriteServer,
  listScrapFavoritesServer,
  removeScrapFavoriteServer,
} from '@/lib/api';
import { makerSourceLabel } from './makersUi';

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

/**
 * 服务端持久化 + 内存缓存。
 * 收藏的唯一事实来源在服务端（按登录账号）；本地仅缓存以保持 UI 同步读取。
 */
let cache: ScrapFavorite[] = [];
let cacheLoaded = false;
let loadPromise: Promise<void> | null = null;
/** 并发去抖：同一批 toggle 串行落库，避免响应乱序覆盖缓存 */
let writeChain: Promise<void> = Promise.resolve();

const LEGACY_STORAGE_KEY = 'nextweb:scrap-favorites';
/** 迁移进行中去重；是否还需迁移以 localStorage 是否仍有键为准 */
let migratePromise: Promise<void> | null = null;

function readLegacyFavoriteRows(): ScrapFavorite[] | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      return null;
    }
    return parsed as ScrapFavorite[];
  } catch {
    try {
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return null;
  }
}

/**
 * 一次性迁移：把旧版浏览器 localStorage 收藏导入服务端。
 * 仅全部成功（或无需导入）后清除本地键；失败项保留，下次加载可重试。
 */
async function migrateLegacyFavorites(): Promise<void> {
  if (typeof window === 'undefined') return;
  if (migratePromise) return migratePromise;

  const rows = readLegacyFavoriteRows();
  if (rows === null) return;
  if (!rows.length) {
    try {
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return;
  }

  migratePromise = (async () => {
    const serverIds = new Set(cache.map((r) => r.itemId));
    const pending = rows.filter((r) => {
      const id = String(r.itemId || '').trim();
      return Boolean(id) && !serverIds.has(id);
    });

    if (!pending.length) {
      try {
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      } catch {
        /* ignore */
      }
      return;
    }

    const failed: ScrapFavorite[] = [];
    for (const row of pending) {
      const id = String(row.itemId || '').trim();
      try {
        await writeChain;
        const task = addScrapFavoriteServer(row, row.hubRegion).then(() => {
          if (cache.some((c) => c.itemId === id)) return;
          cache = [
            {
              ...row,
              itemId: id,
              favoritedAt: Number(row.favoritedAt) || 0,
            },
            ...cache,
          ];
        });
        writeChain = task.then(
          () => undefined,
          () => undefined,
        );
        await task;
      } catch {
        failed.push(row);
      }
    }

    try {
      if (failed.length === 0) {
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      } else {
        // 仅保留失败项，下次 ensure 可继续补传
        localStorage.setItem(LEGACY_STORAGE_KEY, JSON.stringify(failed));
      }
    } catch {
      /* ignore storage errors */
    }
  })().finally(() => {
    migratePromise = null;
  });

  return migratePromise;
}

function _normalizeRows(rows: ScrapFavorite[]): ScrapFavorite[] {
  return rows
    .filter((row) => {
      if (!row || typeof row !== 'object') return false;
      return Boolean(String((row as ScrapFavorite).itemId || '').trim());
    })
    .map((row) => ({
      ...row,
      itemId: String(row.itemId || '').trim(),
      favoritedAt: Number(row.favoritedAt) || 0,
    }));
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
  // 无地区信息：仅在未按地区过滤时展示；有 keys 时不匹配，避免串到所有 tab
  if (candidates.length === 0) return keys.size === 0;
  return candidates.some((c) => keys.has(c));
}

/** 从服务端拉取该账号的全部收藏（应用内已登录）。幂等，可并发安全调用。 */
export function ensureScrapFavoritesLoaded(): Promise<void> {
  if (cacheLoaded) {
    // 缓存已就绪时仍尝试补迁：上次失败会保留 localStorage 键
    return migrateLegacyFavorites();
  }
  if (loadPromise) return loadPromise;
  loadPromise = listScrapFavoritesServer()
    .then(async (rows) => {
      cache = _normalizeRows(rows as unknown as ScrapFavorite[]);
      cacheLoaded = true;
      // 迁移旧浏览器收藏（幂等：仅服务端缺少的才补）
      await migrateLegacyFavorites();
    })
    .catch(() => {
      // 失败不标记已加载，下次进入收藏可重试
      cacheLoaded = false;
    })
    .finally(() => {
      loadPromise = null;
    });
  return loadPromise;
}

/** 强制刷新（账号切换/手动重试用）。 */
export function refreshScrapFavorites(): Promise<void> {
  cacheLoaded = false;
  loadPromise = null;
  return ensureScrapFavoritesLoaded();
}

/** 登出 / 换号时清空内存缓存，避免串号。 */
export function clearScrapFavoritesCache(): void {
  cache = [];
  cacheLoaded = false;
  loadPromise = null;
  migratePromise = null;
}

/** region 可能是 japan_censored / 有码 / 日本有码 */
export function listScrapFavorites(
  region?: string,
  aliases: string[] = [],
): ScrapFavorite[] {
  const all = cache;
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
  return cache.some((r) => r.itemId === id);
}

function _applyLocalToggle(item: ScrapFavorite, favorited: boolean) {
  const idx = cache.findIndex((r) => r.itemId === item.itemId);
  if (favorited) {
    if (idx < 0) cache = [item, ...cache];
    else cache = cache.map((r) => (r.itemId === item.itemId ? item : r));
  } else if (idx >= 0) {
    cache = cache.filter((r) => r.itemId !== item.itemId);
  }
}

/**
 * 切换收藏（服务端为真相）。resolve 的 boolean = 切换后的收藏状态。
 * 落库失败时不改动缓存并抛错，由调用方 toast。
 */
export function toggleScrapFavorite(
  item: ScrapLibraryEmbedItem,
  hubRegion?: string,
): Promise<boolean> {
  const id = String(item.itemId || '').trim();
  const nextFavorited = !isScrapFavorite(id);
  // 串行化，避免并发写乱序
  const task = writeChain.then(async () => {
    if (nextFavorited) {
      const fav: ScrapFavorite = {
        ...item,
        itemId: id,
        favoritedAt: Date.now(),
        hubRegion: String(hubRegion || '').trim() || undefined,
      };
      await addScrapFavoriteServer(item, hubRegion);
      _applyLocalToggle(fav, true);
      return true;
    }
    await removeScrapFavoriteServer(id);
    _applyLocalToggle({ itemId: id } as ScrapFavorite, false);
    return false;
  });
  writeChain = task.then(
    () => undefined,
    () => undefined,
  );
  return task;
}

/** 一次性加载入口（供 MakersScreen 挂载时调用）。 */
export function primeScrapFavorites(): Promise<void> {
  return ensureScrapFavoritesLoaded();
}
