'use client';

import { useEffect, useRef, useState } from 'react';
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

function coversForHit(it: LibraryFacetCodeItem): string[] {
  const raw: string[] = [];
  const local = String(it.posterLocal || '').trim();
  if (local) raw.push(scrapeExportFileUrl(local));
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
  }, [item.code, item.posterLocal, item.coverUrl]);

  if (!candidates.length || gone || !src) {
    return <span className="prefix-tile__empty" aria-hidden />;
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
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<LibraryFacetCodeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [cropTick, setCropTick] = useState(0);
  const listScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setCropTick((n) => n + 1));
  }, []);

  useEffect(() => {
    setPage(1);
    setItems([]);
    setTotal(0);
  }, [regionId, kind, value]);

  useEffect(() => {
    const ac = new AbortController();
    const offset = (page - 1) * PREFIX_CODE_PAGE_SIZE;
    setLoading(true);
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
        setTotal(data.total || 0);
        setItems(data.items || []);
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

  useEffect(() => {
    listScrollRef.current?.scrollTo({ top: 0 });
  }, [page]);

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
  const gridCols = display.cols || 2;

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
              <p>该分类下暂无番号</p>
            </div>
          ) : showSkel ? (
            <PrefixCodeGridSkeleton prefix="" count={12} />
          ) : (
            <div className="prefix-grid" data-cols={gridCols}>
              {items.map((it, index) => {
                const { actors, title } = makerFsIndexLines(it, regionId);
                return (
                  <button
                    key={`${it.studio}|${it.prefix}|${it.code}`}
                    type="button"
                    className="prefix-tile"
                    onClick={() =>
                      onOpenCode(
                        it.code,
                        String(it.studio || ''),
                        String(it.prefix || ''),
                      )
                    }
                  >
                    <span
                      className="prefix-tile__media"
                      style={{ aspectRatio: tileAspect }}
                    >
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
              onClick={() => setPage((p) => Math.max(1, p - 1))}
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
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </nav>
        ) : null}
      </div>
    </div>
  );
}
