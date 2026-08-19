'use client';

import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { CroppedCoverImg } from '@/components/cover/CroppedCoverImg';
import {
  fetchLibraryTileCovers,
  fetchLibraryTileCoversBatch,
  scrapeExportFileUrl,
  type LibraryTileCoverItem,
} from '@/lib/api';
import {
  ensurePosterCropLoaded,
  frameAspectForCropMode,
  getPosterCropCached,
  isPortraitCropMode,
  cropModeForRegion,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import { prefixHasCover, type MakerFsPrefixCover } from '@/lib/makerFsUi';

export type MakerPosterTileItem = MakerFsPrefixCover & {
  key: string;
  label: string;
  sub?: string;
  title?: string;
  /** 封面库：厂牌目录名 */
  coverStudio?: string;
  /** 封面库：前缀目录名；空则按 coverPrefixes 取最新前缀 */
  coverPrefix?: string;
  /** 厂牌卡：该厂前缀列表，用来找最新前缀 */
  coverPrefixes?: string[];
  onClick: () => void;
};

const PACK_LAST_KEY = 'mk-cover-pack-last:';
const packPromises = new Map<string, Promise<LibraryTileCoverItem[]>>();
const CoverBatchContext = createContext<
  Map<string, LibraryTileCoverItem[]> | null | undefined
>(undefined);

function packCacheKey(regionId: string, studio: string, prefix: string) {
  return `${regionId}|${studio}|${prefix}`;
}

function itemPackKey(regionId: string, it: MakerPosterTileItem) {
  const studio = String(it.coverStudio || '').trim();
  const prefix = String(it.coverPrefix || '').trim();
  return packCacheKey(regionId, studio, prefix);
}

function loadTileCoverPack(opts: {
  region: string;
  studio: string;
  prefix?: string;
  prefixes?: string[];
}): Promise<LibraryTileCoverItem[]> {
  const key = packCacheKey(
    opts.region,
    opts.studio,
    opts.prefix || (opts.prefixes || []).join(','),
  );
  let p = packPromises.get(key);
  if (!p) {
    p = fetchLibraryTileCovers(opts)
      .then((d) => {
        const items = Array.isArray(d.items) ? d.items : [];
        if (!items.length) packPromises.delete(key);
        return items;
      })
      .catch(() => {
        packPromises.delete(key);
        return [] as LibraryTileCoverItem[];
      });
    packPromises.set(key, p);
  }
  return p;
}

function readLastCover(key: string): MakerFsPrefixCover {
  try {
    const raw = localStorage.getItem(PACK_LAST_KEY + key);
    if (!raw) return {};
    const j = JSON.parse(raw) as MakerFsPrefixCover;
    if (!j || typeof j !== 'object') return {};
    if (!String(j.posterLocal || '').trim()) return {};
    return {
      posterLocal: j.posterLocal,
      posterRev: j.posterRev,
      coverCode: j.coverCode,
    };
  } catch {
    return {};
  }
}

function writeLastCover(key: string, cover: MakerFsPrefixCover) {
  try {
    localStorage.setItem(PACK_LAST_KEY + key, JSON.stringify(cover));
  } catch {
    /* ignore */
  }
}

function sameCover(a: MakerFsPrefixCover, b: MakerFsPrefixCover) {
  return (
    String(a.posterLocal || '') === String(b.posterLocal || '') &&
    String(a.posterRev || '') === String(b.posterRev || '')
  );
}

function useRegionPosterFrame(regionId: string) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setTick((n) => n + 1));
  }, []);
  void tick;
  const cropMode = cropModeForRegion(regionId);
  return {
    tileAspect: frameAspectForCropMode(cropMode, getPosterCropCached().ratio),
    gridCols: isPortraitCropMode(cropMode) ? '3' : '2',
  };
}

function PosterCover({
  cover,
  label,
  regionId,
  loading,
}: {
  cover: MakerFsPrefixCover;
  label: string;
  regionId: string;
  loading: 'lazy' | 'eager';
}) {
  const local = String(cover.posterLocal || '').trim()
    ? scrapeExportFileUrl(String(cover.posterLocal), cover.posterRev)
    : '';
  const remotes = [
    ...(cover.coverUrls || []),
    cover.coverUrl,
  ].filter((u): u is string => Boolean(String(u || '').trim()));
  return (
    <CroppedCoverImg
      src={local || remotes[0] || null}
      srcs={local ? remotes : remotes.slice(1)}
      region={regionId}
      alt={label}
      loading={loading}
      fetchPriority={loading === 'eager' ? 'high' : 'low'}
      sizes="120px"
    />
  );
}

function coverFromItem(it: LibraryTileCoverItem): MakerFsPrefixCover {
  const posterLocal = String(it.posterLocal || '').trim();
  if (!posterLocal) return {};
  return {
    posterLocal,
    posterRev: it.posterRev,
    coverCode: it.coverCode,
  };
}

function applyPackItems(
  packKey: string,
  items: LibraryTileCoverItem[],
  setCover: (c: MakerFsPrefixCover) => void,
) {
  const localItems = items.filter((it) => String(it.posterLocal || '').trim());
  const next = localItems.length ? coverFromItem(localItems[0]) : {};
  const last = readLastCover(packKey);
  if (sameCover(last, next)) return;
  writeLastCover(packKey, next);
  setCover(next);
}

function useFolderCoverPack(
  regionId: string,
  studio: string | undefined,
  prefix: string | undefined,
  prefixes: string[] | undefined,
  enabled: boolean,
): MakerFsPrefixCover {
  const batch = useContext(CoverBatchContext);
  const prefixesKey = prefix || '';
  const packKey = studio ? packCacheKey(regionId, studio, prefixesKey) : '';
  const [cover, setCover] = useState<MakerFsPrefixCover>(() =>
    packKey ? readLastCover(packKey) : {},
  );

  useEffect(() => {
    if (!enabled || !studio || !packKey) return;
    if (!prefix && !(prefixes || []).length) return;
    let cancelled = false;
    let pending: Promise<LibraryTileCoverItem[]>;
    if (batch === undefined) {
      pending = loadTileCoverPack({
        region: regionId,
        studio,
        prefix: prefix || undefined,
        prefixes: prefix ? undefined : prefixes,
      });
    } else if (batch === null || !batch.has(packKey)) {
      return;
    } else {
      pending = Promise.resolve(batch.get(packKey) || []);
    }
    void pending.then((items) => {
      if (cancelled) return;
      applyPackItems(packKey, items, setCover);
    });
    return () => {
      cancelled = true;
    };
  }, [batch, enabled, packKey, prefix, prefixesKey, regionId, studio]);

  return cover;
}

function MakerPosterTile({
  item,
  regionId,
  tileAspect,
  loading,
  overlay,
}: {
  item: MakerPosterTileItem;
  regionId: string;
  tileAspect: string;
  loading: 'lazy' | 'eager';
  overlay: 'bottom' | 'center';
}) {
  const mediaRef = useRef<HTMLSpanElement>(null);
  const [inView, setInView] = useState(loading === 'eager');
  const studio = String(item.coverStudio || '').trim();
  const prefix = String(item.coverPrefix || '').trim();
  const prefixes = item.coverPrefixes;
  const packCover = useFolderCoverPack(
    regionId,
    studio || undefined,
    prefix,
    prefixes,
    inView,
  );
  const cover: MakerFsPrefixCover = studio ? packCover : item;
  const hasCover = prefixHasCover(cover);
  const overlayClass =
    overlay === 'center'
      ? 'prefix-tile__overlay prefix-tile__overlay--center'
      : 'prefix-tile__overlay';

  useEffect(() => {
    if (inView) return;
    const el = mediaRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: '280px 0px', threshold: 0.01 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [inView]);

  return (
    <button type="button" className="prefix-tile" onClick={item.onClick} title={item.label}>
      <span
        ref={mediaRef}
        className={
          hasCover
            ? 'prefix-tile__media'
            : 'prefix-tile__media prefix-tile__media--nocover'
        }
        style={{ aspectRatio: tileAspect }}
      >
        {hasCover ? (
          <>
            <PosterCover
              cover={cover}
              label={item.label}
              regionId={regionId}
              loading={loading}
            />
            <span className={overlayClass}>
              {item.sub ? (
                <span className="prefix-tile__actors allow-select" title={item.sub}>
                  {item.sub}
                </span>
              ) : null}
              <span className="prefix-tile__code allow-select">{item.label}</span>
            </span>
          </>
        ) : (
          <span className="prefix-tile__code prefix-tile__code--solo allow-select">
            {item.label}
          </span>
        )}
      </span>
      {item.title ? (
        <span className="prefix-tile__meta">
          <span className="prefix-tile__title allow-select" title={item.title}>
            {item.title}
          </span>
        </span>
      ) : null}
    </button>
  );
}

/** 厂牌 / 前缀浏览格：与番号 prefix-tile 同一套封面卡片 */
export function MakerPosterGrid({
  regionId,
  items,
  overlay = 'bottom',
}: {
  regionId: string;
  items: MakerPosterTileItem[];
  overlay?: 'bottom' | 'center';
}) {
  const { tileAspect, gridCols } = useRegionPosterFrame(regionId);
  const sig = useMemo(
    () => items.map((it) => itemPackKey(regionId, it)).join('\n'),
    [items, regionId],
  );
  const [packMap, setPackMap] = useState<Map<string, LibraryTileCoverItem[]> | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    const queries = items.map((it) => ({
      studio: it.coverStudio,
      prefix: it.coverPrefix || '',
      prefixes: it.coverPrefix ? undefined : it.coverPrefixes,
    }));
    if (!queries.some((q) => q.studio)) {
      setPackMap(new Map());
      return;
    }

    const FIRST = 6;
    const merge = (start: number, packs: LibraryTileCoverItem[][]) => {
      if (cancelled) return;
      setPackMap((prev) => {
        const m = new Map(prev || []);
        for (let j = 0; j < packs.length; j += 1) {
          const it = items[start + j];
          if (!it) continue;
          const k = itemPackKey(regionId, it);
          const covers = packs[j] || [];
          m.set(k, covers);
          packPromises.set(k, Promise.resolve(covers));
        }
        return m;
      });
    };

    void (async () => {
      try {
        const head = await fetchLibraryTileCoversBatch({
          region: regionId,
          queries: queries.slice(0, FIRST),
        });
        merge(0, head);
        if (cancelled || queries.length <= FIRST) return;
        const tail = await fetchLibraryTileCoversBatch({
          region: regionId,
          queries: queries.slice(FIRST),
        });
        merge(FIRST, tail);
      } catch {
        if (!cancelled) {
          setPackMap((prev) => prev || new Map());
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [regionId, sig]);

  return (
    <CoverBatchContext.Provider value={packMap}>
      <div
        className={`prefix-grid mk-browse-grid${overlay === 'center' ? ' mk-browse-grid--center' : ''}`}
        data-cols={gridCols}
      >
        {items.map((it, index) => (
          <MakerPosterTile
            key={it.key}
            item={it}
            regionId={regionId}
            tileAspect={tileAspect}
            loading={index < 6 ? 'eager' : 'lazy'}
            overlay={overlay}
          />
        ))}
      </div>
    </CoverBatchContext.Provider>
  );
}
