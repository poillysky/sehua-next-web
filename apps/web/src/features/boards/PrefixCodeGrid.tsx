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
  isPortraitCropMode,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import { useCoverObjectPosition } from '@/hooks/useCoverObjectPosition';
import {
  fetchLibraryCodes,
  fetchMakerFsPrefixCodes,
  proxiedCoverUrl,
  scrapeExportFileUrl,
} from '@/lib/api';
import { makerFsIndexLines } from '@/lib/makerFsUi';
import { PrefixCodeGridSkeleton } from './PrefixCodeGridSkeleton';

type Hit = {
  code: string;
  coverUrl: string | null;
  coverUrls: string[];
  forumTitle?: string | null;
  forumActors?: string[] | null;
  /** library 内刮削海报相对路径，优先于远程封面 */
  posterLocal?: string | null;
  /** poster mtime-size，破坏 PWA/浏览器图片缓存 */
  posterRev?: string | null;
};

type PrefixCache = {
  page: number;
  total: number;
  loaded: boolean;
  pages: Record<number, Hit[]>;
  scrollTop: number;
};

/** 会话内缓存：library / maker-fs 已确认番号 */
const PREFIX_CACHE = new Map<string, PrefixCache>();
const CACHE_VER = 'library-codes-v6';

function cacheKey(prefix: string, region?: string, q?: string, studio?: string) {
  const p = String(prefix || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');
  const r = String(region || '').trim().toLowerCase();
  const s = String(studio || '').trim().toLowerCase();
  const needle = String(q || '').trim().toLowerCase();
  return `${CACHE_VER}:${p}|${r}|${s}|${needle}`;
}

function getCache(
  prefix: string,
  region?: string,
  q?: string,
  studio?: string,
): PrefixCache {
  const key = cacheKey(prefix, region, q, studio);
  let c = PREFIX_CACHE.get(key);
  if (!c) {
    c = { page: 1, total: 0, loaded: false, pages: {}, scrollTop: 0 };
    PREFIX_CACHE.set(key, c);
  }
  return c;
}

const FLAKY_COVER_HOST =
  /xms45\.com|imghost\.biz|gifyu\.com|imagetwist\.com/i;

function coversForHit(it: Hit): string[] {
  const raw: string[] = [];
  const local = String(it.posterLocal || '').trim();
  if (local) raw.push(scrapeExportFileUrl(local, it.posterRev));
  const remote =
    it.coverUrls?.length > 0
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
  // 外链走 cover-proxy（服务端用项目代理），本地 file URL 原样
  return ordered.map((u) => proxiedCoverUrl(u)).filter(Boolean);
}

function mapCodeItems(dataItems: unknown[]): Hit[] {
  return (dataItems || [])
    .map((raw) => {
      const it = raw as {
        code: string;
        coverUrl?: string | null;
        coverUrls?: string[] | null;
        forumTitle?: string | null;
        forumActors?: string[] | null;
        posterLocal?: string | null;
        posterRev?: string | null;
      };
      const urls =
        Array.isArray(it.coverUrls) && it.coverUrls.length
          ? [...it.coverUrls]
          : it.coverUrl
            ? [it.coverUrl]
            : [];
      const posterLocal = String(it.posterLocal || '').trim() || null;
      const posterRev = String(it.posterRev || '').trim() || null;
      return {
        code: it.code,
        coverUrl: it.coverUrl ?? null,
        coverUrls: urls,
        forumTitle: it.forumTitle ?? null,
        forumActors: it.forumActors ?? null,
        posterLocal,
        posterRev,
      };
    })
    .filter((it) => {
      // 空壳：无封面且无标题/女优 → 不展示
      if (hitHasCover(it)) return true;
      if (String(it.forumTitle || '').trim()) return true;
      if ((it.forumActors || []).some((a) => String(a || '').trim())) return true;
      return false;
    });
}

/** 有本地 poster 或封面 URL 才挂载封面组件，避免空壳目录无意义加载 */
function hitHasCover(it: {
  posterLocal?: string | null;
  coverUrl?: string | null;
  coverUrls?: string[] | null;
}): boolean {
  if (String(it.posterLocal || '').trim()) return true;
  if (String(it.coverUrl || '').trim()) return true;
  return (it.coverUrls || []).some((u) => Boolean(String(u || '').trim()));
}

/** 番号计数 */
export function PrefixCountBadge({
  total,
  loading,
  compact = false,
}: {
  total: number;
  loading: boolean;
  compact?: boolean;
}) {
  if (total > 0) {
    return (
      <p
        className={`prefix-count${compact ? ' prefix-count--nav' : ''}`}
        data-state="ready"
        title={`索引 ${total} 个番号`}
      >
        {compact ? (
          <span className="prefix-count__num">{total}</span>
        ) : (
          <>
            <span className="prefix-count__label">索引</span>
            <span className="prefix-count__num">{total}</span>
            <span className="prefix-count__label">个番号</span>
          </>
        )}
      </p>
    );
  }
  if (compact) return null;
  if (loading) {
    return (
      <p
        className="prefix-count"
        data-state="scanning"
        aria-live="polite"
        aria-busy="true"
        title="加载本地索引"
      >
        <span className="prefix-count__label">加载中</span>
      </p>
    );
  }
  return (
    <p className="prefix-count" data-state="empty" title="本地索引暂无番号">
      暂无索引
    </p>
  );
}

function PrefixTileCover({
  code,
  coverUrl,
  coverUrls,
  posterLocal,
  posterRev,
  cropMode,
  fallbackPosition,
  loading,
}: {
  code: string;
  coverUrl: string | null;
  coverUrls: string[];
  posterLocal?: string | null;
  posterRev?: string | null;
  cropMode?: import('@/lib/api').PosterCropMode;
  fallbackPosition: string;
  loading: 'lazy' | 'eager';
}) {
  const candidates = coversForHit({
    code,
    coverUrl,
    coverUrls,
    posterLocal,
    posterRev,
  });
  const [idx, setIdx] = useState(0);
  const [gone, setGone] = useState(false);
  const src = candidates[idx];
  const coverSig = `${posterLocal || ''}|${posterRev || ''}|${coverUrl || ''}|${coverUrls.join('|')}`;
  const objectPosition = useCoverObjectPosition(
    cropMode,
    gone ? null : src,
  );
  const pos = cropMode === 'face' ? objectPosition : fallbackPosition;
  const objectFit = objectFitForCropMode(cropMode);

  useEffect(() => {
    setIdx(0);
    setGone(false);
  }, [code, coverSig]);

  if (!candidates.length || gone || !src) {
    // 无封面 URL / 本地 poster：不渲染占位图
    return null;
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt={code}
      src={src}
      loading={loading}
      decoding="async"
      referrerPolicy="no-referrer"
      style={{ objectPosition: pos, objectFit }}
      onError={() => {
        if (idx + 1 < candidates.length) setIdx(idx + 1);
        else setGone(true);
      }}
    />
  );
}

/**
 * 番号封面格：传 studio 时读 library，否则读 maker-fs（设置页）。
 */
export function PrefixCodeGrid({
  prefix,
  region,
  studio,
  query = '',
  onOpenCode,
  onStatusChange,
}: {
  prefix: string;
  region?: string;
  /** 厂牌/作者目录名；有则走 library */
  studio?: string;
  /** 筛选番号 / 标题 / 女优 */
  query?: string;
  /** 不传则仅展示，不可点进搜库 */
  onOpenCode?: (code: string) => void;
  onStatusChange?: (status: { total: number; loading: boolean } | null) => void;
}) {
  const needle = String(query || '').trim();
  const studioKey = String(studio || '').trim();
  const cached = getCache(prefix, region, needle, studioKey);
  const [page, setPage] = useState(() => cached.page);
  const [total, setTotal] = useState(() => cached.total);
  const [items, setItems] = useState<Hit[]>(() => cached.pages[cached.page] || []);
  const [loading, setLoading] = useState(() => !cached.loaded && !(cached.pages[cached.page]?.length));
  const listScrollRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef(page);
  const skipScrollReset = useRef(true);
  const pinToTop = useRef(false);
  const pendingScrollY = useRef<number | null>(null);
  const display = resolveCoverDisplay(prefix);
  const prevNeedle = useRef(needle);
  const [cropTick, setCropTick] = useState(0);

  pageRef.current = page;

  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setCropTick((n) => n + 1));
  }, []);

  const cropMode = (() => {
    void cropTick;
    return region ? cropModeForRegion(region) : undefined;
  })();

  const objectPosition = (() => {
    void cropTick;
    if (cropMode) {
      return objectPositionForCropMode(cropMode);
    }
    return display.objectPosition;
  })();

  // 右侧/人脸：竖版框；不裁剪：一律横图结构
  const usePortraitFrame = isPortraitCropMode(cropMode);
  const tileAspect = (() => {
    void cropTick;
    return frameAspectForCropMode(cropMode, getPosterCropCached().ratio);
  })();
  const gridCols = usePortraitFrame ? '3' : '2';

  function scrollCache() {
    return getCache(prefix, region, needle, studioKey);
  }

  function saveListScroll() {
    const el = listScrollRef.current;
    if (!el) return;
    const c = scrollCache();
    c.scrollTop = el.scrollTop;
    c.page = pageRef.current;
  }

  /** 内容高度不足时不强行清 pending，等 ResizeObserver 再试 */
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

  function scrollListToTop() {
    const el = listScrollRef.current;
    if (!el) return;
    el.scrollTop = 0;
    saveListScroll();
  }

  function goPage(next: number) {
    pinToTop.current = true;
    skipScrollReset.current = false;
    setPage(next);
    scrollListToTop();
    requestAnimationFrame(scrollListToTop);
  }

  useEffect(() => {
    if (prevNeedle.current === needle) return;
    prevNeedle.current = needle;
    pinToTop.current = true;
    skipScrollReset.current = false;
    setPage(1);
  }, [needle]);

  useEffect(() => {
    const c = getCache(prefix, region, needle, studioKey);
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
    void (async () => {
      try {
        const data =
          studioKey && region
            ? await fetchLibraryCodes({
                region,
                studio: studioKey,
                prefix,
                q: needle || undefined,
                offset: (safePage - 1) * PREFIX_CODE_PAGE_SIZE,
                limit: PREFIX_CODE_PAGE_SIZE,
                signal: ac.signal,
              })
            : await fetchMakerFsPrefixCodes({
                prefix,
                region,
                q: needle || undefined,
                offset: (safePage - 1) * PREFIX_CODE_PAGE_SIZE,
                limit: PREFIX_CODE_PAGE_SIZE,
                signal: ac.signal,
              });
        if (ac.signal.aborted) return;
        if (!data) {
          c.total = 0;
          c.loaded = true;
          c.pages[safePage] = [];
          setTotal(0);
          setItems([]);
          return;
        }
        const next = mapCodeItems(data.items || []);
        c.total = data.total;
        c.loaded = true;
        c.pages[safePage] = next;
        setTotal(data.total);
        setItems(next);

        // 后台预取下一页，点「下一页」秒开
        const totalPages = Math.max(
          1,
          Math.ceil((data.total || 0) / PREFIX_CODE_PAGE_SIZE),
        );
        const nextPage = safePage + 1;
        if (
          nextPage <= totalPages &&
          nextPage <= BROWSE_PAGE_MAX &&
          !c.pages[nextPage]
        ) {
          const prefetchAc = ac;
          void (async () => {
            try {
              const more =
                studioKey && region
                  ? await fetchLibraryCodes({
                      region,
                      studio: studioKey,
                      prefix,
                      q: needle || undefined,
                      offset: (nextPage - 1) * PREFIX_CODE_PAGE_SIZE,
                      limit: PREFIX_CODE_PAGE_SIZE,
                      signal: prefetchAc.signal,
                    })
                  : await fetchMakerFsPrefixCodes({
                      prefix,
                      region,
                      q: needle || undefined,
                      offset: (nextPage - 1) * PREFIX_CODE_PAGE_SIZE,
                      limit: PREFIX_CODE_PAGE_SIZE,
                      signal: prefetchAc.signal,
                    });
              if (prefetchAc.signal.aborted || !more || c.pages[nextPage]) return;
              c.pages[nextPage] = mapCodeItems(more.items || []);
              c.total = more.total;
            } catch {
              /* 预取失败忽略 */
            }
          })();
        }
      } catch {
        if (!ac.signal.aborted) {
          setItems([]);
          setTotal(0);
        }
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
  }, [prefix, region, studioKey, page, needle]);

  useEffect(() => {
    const el = listScrollRef.current;
    if (!el) return;
    const onScroll = () => saveListScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      saveListScroll();
      el.removeEventListener('scroll', onScroll);
    };
  }, [prefix, region, needle, studioKey]);

  useLayoutEffect(() => {
    if (skipScrollReset.current) {
      pendingScrollY.current = scrollCache().scrollTop;
      skipScrollReset.current = false;
      return;
    }
    if (pinToTop.current) {
      scrollListToTop();
    }
  }, [page, prefix, region, studioKey, needle]);

  useLayoutEffect(() => {
    if (loading) return;
    if (pinToTop.current) {
      scrollListToTop();
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
  }, [items, loading, page, prefix, region, needle, studioKey]);

  const statusCbRef = useRef(onStatusChange);
  statusCbRef.current = onStatusChange;
  useEffect(() => {
    statusCbRef.current?.({ total, loading });
  }, [total, loading, prefix]);

  const totalPages = Math.max(1, Math.ceil(total / PREFIX_CODE_PAGE_SIZE));
  const showPager = total > PREFIX_CODE_PAGE_SIZE;
  const hasPrev = page > 1;
  const hasNext = page < totalPages;
  const showEmpty = !loading && total === 0;
  const showSkel = loading && items.length === 0;

  return (
    <div
      className="prefix-grid-wrap"
      data-loading={loading ? '1' : '0'}
      data-source="maker-fs"
    >
      <div ref={listScrollRef} className="prefix-grid-scroll" data-ptr-scroll>
        {showEmpty ? (
          <div className="app-empty" style={{ padding: '24px 8px' }}>
            <p>{needle ? '无匹配番号' : '本地索引暂无此番号'}</p>
            <p className="app-footnote" style={{ marginTop: 8 }}>
              {needle
                ? '试试番号、标题关键词'
                : '请到设置 → 本地索引扫库并同步本地片库后再看'}
            </p>
          </div>
        ) : showSkel ? (
          <PrefixCodeGridSkeleton prefix={prefix} count={12} />
        ) : (
          <div className="prefix-grid" data-cols={gridCols}>
            {items.map((it, index) => {
              const { actors, title } = makerFsIndexLines(it, region);
              const hasCover = hitHasCover(it);
              const tile = (
                <>
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
                        <PrefixTileCover
                          code={it.code}
                          coverUrl={it.coverUrl}
                          coverUrls={it.coverUrls}
                          posterLocal={it.posterLocal}
                          posterRev={it.posterRev}
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
                      <span className="prefix-tile__title allow-select" title={title}>
                        {title}
                      </span>
                    </span>
                  ) : null}
                </>
              );
              if (onOpenCode) {
                return (
                  <button
                    key={it.code}
                    type="button"
                    className="prefix-tile"
                    onClick={() => {
                      saveListScroll();
                      onOpenCode(it.code);
                    }}
                  >
                    {tile}
                  </button>
                );
              }
              return (
                <div key={it.code} className="prefix-tile prefix-tile--static">
                  {tile}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showPager ? (
        <nav className="prefix-pager" aria-label="翻页">
          <button
            type="button"
            className="app-btn-secondary"
            disabled={!hasPrev || loading}
            onClick={() => goPage(Math.max(1, page - 1))}
          >
            上一页
          </button>
          <span className="prefix-pager__n">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="app-btn-primary"
            disabled={!hasNext || loading}
            onClick={() => goPage(Math.min(totalPages, page + 1))}
          >
            下一页
          </button>
        </nav>
      ) : null}
    </div>
  );
}

export type PrefixGridStatus = { total: number; loading: boolean };
