'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { BROWSE_PAGE_MAX, PREFIX_CODE_PAGE_SIZE } from '@/config/search';
import { resolveCoverDisplay } from '@/config/av-makers';
import {
  ensurePosterCropLoaded,
  objectPositionForCropMode,
  objectFitForCropMode,
  cropModeForRegion,
  frameAspectForCropMode,
  getPosterCropCached,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import {
  fetchLibraryFacetCodes,
  proxiedCoverUrl,
  scrapeExportFileUrl,
  type LibraryFacetCodeItem,
} from '@/lib/api';
import { makerFsIndexLines } from '@/lib/makerFsUi';
import { PrefixCodeGridSkeleton } from '@/features/boards/PrefixCodeGridSkeleton';

const FLAKY_COVER_HOST =
  /xms45\.com|imghost\.biz|gifyu\.com|imagetwist\.com/i;

type FacetCodesCache = {
  page: number;
  scrollTop: number;
  total: number;
  loaded: boolean;
  pages: Record<number, LibraryFacetCodeItem[]>;
};

const FACET_CODES_CACHE = new Map<string, FacetCodesCache>();

function facetCodesCacheKey(regionId: string, kind: string, value: string) {
  return `${regionId}|${kind}|${value}`;
}

function getFacetCodesCache(regionId: string, kind: string, value: string): FacetCodesCache {
  const key = facetCodesCacheKey(regionId, kind, value);
  let c = FACET_CODES_CACHE.get(key);
  if (!c) {
    c = { page: 1, scrollTop: 0, total: 0, loaded: false, pages: {} };
    FACET_CODES_CACHE.set(key, c);
  }
  return c;
}

function coversForHit(it: LibraryFacetCodeItem): string[] {
  const raw: string[] = [];
  const local = String(it.posterLocal || '').trim();
  if (local) raw.push(scrapeExportFileUrl(local, it.posterRev));
  const remote =
    it.coverUrls && it.coverUrls.length > 0
      ? [...it.coverUrls]
      : it.coverUrl
        ? [it.coverUrl]
        : [];
  for (const u of remote) {
    if (u && !raw.includes(u)) raw.push(u);
  }
  const urls = raw.filter(Boolean);
  const good = urls.filter((u) => !FLAKY_COVER_HOST.test(u));
  const flaky = urls.filter((u) => FLAKY_COVER_HOST.test(u));
  const ordered = good.length ? [...good, ...flaky] : flaky;
  return ordered.map((u) => proxiedCoverUrl(u)).filter(Boolean);
}

function facetHasCover(it: LibraryFacetCodeItem): boolean {
  if (String(it.posterLocal || '').trim()) return true;
  if (String(it.coverUrl || '').trim()) return true;
  return (it.coverUrls || []).some((u) => Boolean(String(u || '').trim()));
}

function filterFacetItems(items: LibraryFacetCodeItem[]): LibraryFacetCodeItem[] {
  return (items || []).filter((it) => {
    if (facetHasCover(it)) return true;
    if (String(it.forumTitle || '').trim()) return true;
    if ((it.forumActors || []).some((a) => String(a || '').trim())) return true;
    return false;
  });
}

function FacetTileCover({
  item,
  cropMode,
  fallbackPosition,
  loading,
}: {
  item: LibraryFacetCodeItem;
  cropMode?: import('@/lib/api').PosterCropMode;
  fallbackPosition: string;
  loading: 'lazy' | 'eager';
}) {
  const candidates = coversForHit(item);
  const [idx, setIdx] = useState(0);
  const [gone, setGone] = useState(false);
  const src = candidates[idx];

  useEffect(() => {
    setIdx(0);
    setGone(false);
  }, [item.code, item.posterLocal, item.posterRev, item.coverUrl]);

  if (!candidates.length || gone || !src) {
    // 无封面 URL / 本地 poster：不渲染占位图
    return null;
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt={item.code}
      src={src}
      loading={loading}
      decoding="async"
      referrerPolicy="no-referrer"
      style={{
        objectPosition: fallbackPosition,
        objectFit: objectFitForCropMode(cropMode),
      }}
      onError={() => {
        if (idx + 1 < candidates.length) setIdx(idx + 1);
        else setGone(true);
      }}
    />
  );
}

/**
 * 标签 / 系列下的番号格。
 */
export function MakerFacetCodesBody({
  regionId,
  kind,
  value,
  onOpenCode,
}: {
  regionId: string;
  kind: 'tag' | 'series' | string;
  value: string;
  onOpenCode: (code: string, studio: string, prefix: string) => void;
}) {
  const cached = getFacetCodesCache(regionId, kind, value);
  const [page, setPage] = useState(() => cached.page);
  const [total, setTotal] = useState(() => cached.total);
  const [items, setItems] = useState<LibraryFacetCodeItem[]>(
    () => cached.pages[cached.page] || [],
  );
  const [loading, setLoading] = useState(
    () => !cached.loaded && !(cached.pages[cached.page]?.length),
  );
  const [cropTick, setCropTick] = useState(0);
  const listScrollRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef(page);
  const pinToTop = useRef(false);
  const pendingScrollY = useRef<number | null>(null);
  const skipScrollRestore = useRef(true);

  pageRef.current = page;

  function scrollCache() {
    return getFacetCodesCache(regionId, kind, value);
  }

  function saveListScroll() {
    const el = listScrollRef.current;
    if (!el) return;
    const c = scrollCache();
    c.scrollTop = el.scrollTop;
    c.page = pageRef.current;
  }

  function tryRestoreListScroll(): boolean {
    const el = listScrollRef.current;
    if (!el || pendingScrollY.current == null) return true;
    const y = pendingScrollY.current;
    if (y <= 0) {
      pendingScrollY.current = null;
      return true;
    }
    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) return false;
    const target = Math.min(y, max);
    el.scrollTop = target;
    if (Math.abs(el.scrollTop - target) <= 2) {
      pendingScrollY.current = null;
      return true;
    }
    return false;
  }

  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setCropTick((n) => n + 1));
  }, []);

  useEffect(() => {
    pinToTop.current = true;
    skipScrollRestore.current = false;
    pendingScrollY.current = null;
    setPage(1);
    setItems([]);
    setTotal(0);
    setLoading(true);
  }, [regionId, kind, value]);

  useEffect(() => {
    const el = listScrollRef.current;
    if (!el) return;
    const onScroll = () => saveListScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      saveListScroll();
      el.removeEventListener('scroll', onScroll);
    };
  }, [regionId, kind, value]);

  useLayoutEffect(() => {
    if (skipScrollRestore.current) {
      pendingScrollY.current = scrollCache().scrollTop;
      skipScrollRestore.current = false;
      return;
    }
    if (pinToTop.current) {
      listScrollRef.current && (listScrollRef.current.scrollTop = 0);
      saveListScroll();
    }
  }, [regionId, kind, value, page]);

  useLayoutEffect(() => {
    if (loading) return;
    if (pinToTop.current) {
      if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
      saveListScroll();
      pinToTop.current = false;
      return;
    }
    tryRestoreListScroll();
  }, [items, loading, page]);

  useEffect(() => {
    if (pendingScrollY.current == null) return;
    const el = listScrollRef.current;
    if (!el) return;
    const attempt = () => tryRestoreListScroll();
    attempt();
    const ro = new ResizeObserver(attempt);
    ro.observe(el);
    const raf = requestAnimationFrame(attempt);
    const t1 = window.setTimeout(attempt, 60);
    const t2 = window.setTimeout(attempt, 200);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [items, loading, page, regionId, kind, value]);

  useEffect(() => {
    const c = getFacetCodesCache(regionId, kind, value);
    const safePage = Math.min(Math.max(page, 1), BROWSE_PAGE_MAX);
    if (safePage !== page) {
      setPage(safePage);
      return;
    }

    const cachedPage = c.pages[safePage];
    if (cachedPage) {
      setItems(cachedPage);
      setTotal(c.total);
      setLoading(false);
      return;
    }

    const ac = new AbortController();
    setLoading(true);
    const offset = (safePage - 1) * PREFIX_CODE_PAGE_SIZE;
    void fetchLibraryFacetCodes({
      region: regionId,
      kind,
      value,
      offset,
      limit: PREFIX_CODE_PAGE_SIZE,
      signal: ac.signal,
    })
      .then((data) => {
        if (ac.signal.aborted) return;
        const next = filterFacetItems(data.items || []);
        c.total = data.total || 0;
        c.loaded = true;
        c.pages[safePage] = next;
        setTotal(c.total);
        setItems(next);
      })
      .catch(() => {
        if (ac.signal.aborted) return;
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [regionId, kind, value, page]);

  function goPage(next: number) {
    pinToTop.current = true;
    skipScrollRestore.current = false;
    pendingScrollY.current = null;
    setPage(next);
  }

  const cropMode = (() => {
    void cropTick;
    return cropModeForRegion(regionId);
  })();
  const objectPosition = objectPositionForCropMode(cropMode);
  const tileAspect = frameAspectForCropMode(
    cropMode,
    getPosterCropCached().ratio,
  );
  const display = resolveCoverDisplay('');
  const gridCols = display.preferLandscape ? '2' : '3';

  const totalPages = Math.max(1, Math.ceil(total / PREFIX_CODE_PAGE_SIZE));
  const showPager = total > PREFIX_CODE_PAGE_SIZE;
  const showEmpty = !loading && total === 0;
  const showSkel = loading && items.length === 0;

  return (
    <div className="mk-facet-codes">
      <p className="app-hint" style={{ marginTop: 0, marginBottom: 8 }}>
        {loading && items.length === 0
          ? '读取番号…'
          : total > 0
            ? `${total} 个番号`
            : '暂无番号'}
      </p>
      <div className="prefix-grid-wrap" data-loading={loading ? '1' : '0'}>
        <div ref={listScrollRef} className="prefix-grid-scroll" data-ptr-scroll>
          {showEmpty ? (
            <div className="app-empty" style={{ padding: '24px 8px' }}>
              <p>该索引项下暂无番号</p>
            </div>
          ) : showSkel ? (
            <PrefixCodeGridSkeleton prefix="" count={12} />
          ) : (
            <div className="prefix-grid" data-cols={gridCols}>
              {items.map((it, index) => {
                const { actors, title } = makerFsIndexLines(it, regionId);
                const hasCover = facetHasCover(it);
                return (
                  <button
                    key={`${it.studio}|${it.prefix}|${it.code}`}
                    type="button"
                    className="prefix-tile"
                    onClick={() => {
                      saveListScroll();
                      onOpenCode(
                        it.code,
                        String(it.studio || ''),
                        String(it.prefix || ''),
                      );
                    }}
                  >
                    <span
                      className={
                        hasCover
                          ? 'prefix-tile__media'
                          : 'prefix-tile__media prefix-tile__media--nocover'
                      }
                      style={{ aspectRatio: tileAspect }}
                    >
                      {hasCover ? (
                        <>
                          <FacetTileCover
                            item={it}
                            cropMode={cropMode}
                            fallbackPosition={objectPosition}
                            loading={index < 8 ? 'eager' : 'lazy'}
                          />
                          <span className="prefix-tile__overlay">
                            {actors ? (
                              <span
                                className="prefix-tile__actors allow-select"
                                title={actors}
                              >
                                {actors}
                              </span>
                            ) : null}
                            <span className="prefix-tile__code allow-select">
                              {it.code}
                            </span>
                          </span>
                        </>
                      ) : (
                        <span className="prefix-tile__code prefix-tile__code--solo allow-select">
                          {it.code}
                        </span>
                      )}
                    </span>
                    {title ? (
                      <span className="prefix-tile__meta">
                        <span
                          className="prefix-tile__title allow-select"
                          title={title}
                        >
                          {title}
                        </span>
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {showPager ? (
          <nav className="prefix-pager" aria-label="翻页">
            <button
              type="button"
              className="prefix-pager__btn"
              disabled={page <= 1 || loading}
              onClick={() => goPage(Math.max(1, page - 1))}
            >
              上一页
            </button>
            <span className="prefix-pager__pos">
              {page} / {Math.min(totalPages, BROWSE_PAGE_MAX || totalPages)}
            </span>
            <button
              type="button"
              className="prefix-pager__btn"
              disabled={page >= totalPages || loading}
              onClick={() => goPage(page + 1)}
            >
              下一页
            </button>
          </nav>
        ) : null}
      </div>
    </div>
  );
}
