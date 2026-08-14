'use client';

import { useEffect, useRef, useState } from 'react';
import { AppPush } from '@/components/ui/AppPush';
import { SEARCH_PAGE_SIZE } from '@/config/search';
import { ResourceCard } from '@/features/home/ResourceCard';
import { ResourceDetailBody } from '@/features/home/ResourceDetailBody';
import { SearchResultsLoading } from '@/features/home/SearchResultsLoading';
import type { SearchSource } from '@/features/home/SourceSwitch';
import { MagnetCard } from '@/features/magnet/BitmagnetResultList';
import { BitmagnetDetailBody } from '@/features/magnet/BitmagnetDetailBody';
import { getBrowsePreferences } from '@/hooks/useBrowsePreferences';
import { fetchMagnetSearch, fetchSearch, type MagnetHit } from '@/lib/api';
import { filterByBrowsePrefs } from '@/lib/browsePreferFilter';
import type { ResourceItem } from '@/types/resource';
import { MakerCodeMetaCard } from './MakerCodeMetaCard';

const POOL_PAGE_SIZE = 40;
const MAX_POOL_PAGES = 5;

/**
 * 片商番号：色花 + Bitmagnet 并行搜索，分 Tab 切换展示（对齐首页双库列表）。
 */
export function MakerCodeSearchBody({
  code,
  region,
  cropRegion,
  prefsTick = 0,
  applyBrowsePrefs = false,
}: {
  code: string;
  region?: string;
  cropRegion?: string;
  prefsTick?: number;
  applyBrowsePrefs?: boolean;
}) {
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [magnetItems, setMagnetItems] = useState<MagnetHit[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [magnetTotal, setMagnetTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [magnetHasMore, setMagnetHasMore] = useState(false);
  const [magnetPage, setMagnetPage] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [magnetLoading, setMagnetLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [magnetLoadingMore, setMagnetLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [magnetError, setMagnetError] = useState('');
  const [costMs, setCostMs] = useState(0);
  const [magnetCostMs, setMagnetCostMs] = useState(0);
  const [hint, setHint] = useState('');
  const [searchSource, setSearchSource] = useState<SearchSource>('sehua');
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const [magnetDetailHash, setMagnetDetailHash] = useState<string | null>(null);
  const poolRef = useRef<ResourceItem[]>([]);
  const reqId = useRef(0);
  const magnetReqId = useRef(0);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPage(1);
    setMagnetPage(1);
    setItems([]);
    setMagnetItems([]);
    setTotal(0);
    setMagnetTotal(0);
    setHasMore(false);
    setMagnetHasMore(false);
    setError('');
    setMagnetError('');
    setCostMs(0);
    setMagnetCostMs(0);
    setHint('');
    setSearchSource('sehua');
    poolRef.current = [];
    setDetailHash(null);
    setMagnetDetailHash(null);
  }, [code, region, prefsTick, applyBrowsePrefs]);

  useEffect(() => {
    const id = ++reqId.current;
    const ac = new AbortController();
    const t0 = performance.now();

    void (async () => {
      setLoading(true);
      try {
        async function pullPool(useRegion: string | undefined) {
          const pool: ResourceItem[] = [];
          const seen = new Set<string>();
          let kws: string[] = [];
          for (let p = 1; p <= MAX_POOL_PAGES; p += 1) {
            const data = await fetchSearch({
              keyword: code,
              page: p,
              pageSize: POOL_PAGE_SIZE,
              matchMode: 'exact',
              sortType: 'default',
              filterTime: 'all',
              filterSize: 'all',
              withTotalCount: false,
              preferChinese: false,
              preferCrack: false,
              region: useRegion,
              signal: ac.signal,
            });
            if (id !== reqId.current) return null;
            if (data.keywords?.length) kws = data.keywords;
            for (const item of data.resources || []) {
              const h = String(item.hash || '');
              if (h && seen.has(h)) continue;
              if (h) seen.add(h);
              pool.push(item);
            }
            if (!data.has_more) break;
            if (pool.length >= SEARCH_PAGE_SIZE * 2) break;
          }
          return { pool, kws };
        }

        let useRegion = region || undefined;
        let pulled = await pullPool(useRegion);
        if (!pulled) return;

        if (pulled.pool.length === 0 && useRegion) {
          useRegion = undefined;
          pulled = await pullPool(undefined);
          if (!pulled) return;
          if (pulled.pool.length > 0) {
            setHint('本分区无帖，已扩大到全库精确匹配');
          }
        }

        let list = pulled.pool;
        let prefsNote = '';
        if (applyBrowsePrefs) {
          const prefs = getBrowsePreferences();
          if (prefs.preferChinese || prefs.preferCrack) {
            const filtered = filterByBrowsePrefs(list, prefs);
            if (filtered.length > 0) {
              list = filtered;
            } else if (list.length > 0) {
              prefsNote = '中文·破解过滤后为空，已显示全部命中';
            }
          }
        }

        if (id !== reqId.current) return;
        poolRef.current = list;
        setKeywords(pulled.kws.length ? pulled.kws : [code]);
        setTotal(list.length);
        setCostMs(Math.round(performance.now() - t0));
        if (prefsNote) setHint((h) => (h ? `${h}；${prefsNote}` : prefsNote));
        const slice = list.slice(0, SEARCH_PAGE_SIZE);
        setItems(slice);
        setHasMore(slice.length < list.length);
        setPage(1);
      } catch (e) {
        if (
          ac.signal.aborted ||
          id !== reqId.current ||
          (e instanceof DOMException && e.name === 'AbortError')
        ) {
          return;
        }
        setItems([]);
        setTotal(0);
        setError(e instanceof Error ? e.message : '搜索失败');
        setHasMore(false);
      } finally {
        if (id === reqId.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    })();

    return () => ac.abort();
  }, [code, region, prefsTick, applyBrowsePrefs]);

  useEffect(() => {
    const id = ++magnetReqId.current;
    const ac = new AbortController();
    const append = magnetPage > 1;
    if (append) setMagnetLoadingMore(true);
    else {
      setMagnetLoading(true);
      setMagnetItems([]);
    }

    void (async () => {
      const t0 = performance.now();
      try {
        const data = await fetchMagnetSearch({
          keyword: code,
          page: magnetPage,
          sortType: 'default',
          filterTime: 'all',
          filterSize: 'all',
          signal: ac.signal,
        });
        if (id !== magnetReqId.current) return;
        const batch = data.items || [];
        setMagnetItems((prev) => {
          if (!append) return batch;
          const seen = new Set(prev.map((x) => x.hash || x.infoHash || x.path));
          return [
            ...prev,
            ...batch.filter((x) => !seen.has(x.hash || x.infoHash || x.path)),
          ];
        });
        setMagnetHasMore(Boolean(data.hasMore));
        if (!append) {
          setMagnetTotal(data.total ?? batch.length);
          setMagnetCostMs(data.costMs || Math.round(performance.now() - t0));
        }
        setMagnetError('');
      } catch (e) {
        if (
          ac.signal.aborted ||
          id !== magnetReqId.current ||
          (e instanceof DOMException && e.name === 'AbortError') ||
          (e instanceof Error && e.name === 'AbortError')
        ) {
          return;
        }
        if (!append) {
          setMagnetItems([]);
          setMagnetTotal(0);
        }
        setMagnetHasMore(false);
        setMagnetError(e instanceof Error ? e.message : 'Bitmagnet 搜索失败');
      } finally {
        if (id === magnetReqId.current) {
          setMagnetLoading(false);
          setMagnetLoadingMore(false);
        }
      }
    })();

    return () => ac.abort();
  }, [code, magnetPage, prefsTick]);

  useEffect(() => {
    if (page <= 1) return;
    setLoadingMore(true);
    const pool = poolRef.current;
    const slice = pool.slice(0, page * SEARCH_PAGE_SIZE);
    setItems(slice);
    setHasMore(slice.length < pool.length);
    setLoadingMore(false);
  }, [page]);

  const resultKeywords = keywords.length ? keywords : [code];
  const activeLoading =
    searchSource === 'sehua'
      ? loading && items.length === 0
      : magnetLoading && magnetItems.length === 0;
  const activeLoadingMore =
    searchSource === 'sehua' ? loadingMore : magnetLoadingMore;
  const activeHasMore =
    searchSource === 'sehua' ? hasMore : magnetHasMore;
  const activeEmpty =
    !activeLoading &&
    (searchSource === 'sehua' ? items.length === 0 : magnetItems.length === 0) &&
    !(searchSource === 'sehua' ? loading : magnetLoading);

  useEffect(() => {
    if (!activeHasMore || activeLoading || activeLoadingMore) return;
    if (detailHash || magnetDetailHash) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        if (searchSource === 'sehua') {
          if (hasMore) setPage((p) => p + 1);
        } else if (magnetHasMore) {
          setMagnetPage((p) => p + 1);
        }
      },
      { root: scrollRef.current, rootMargin: '240px 0px', threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [
    activeHasMore,
    activeLoading,
    activeLoadingMore,
    hasMore,
    magnetHasMore,
    searchSource,
    items.length,
    magnetItems.length,
    detailHash,
    magnetDetailHash,
  ]);

  function onSourceChange(next: SearchSource) {
    setSearchSource(next);
    scrollRef.current?.scrollTo({ top: 0 });
  }

  const sehuaTabLabel =
    loading && total === 0 ? '色花堂…' : `色花堂 ${total}`;
  const btTabLabel =
    magnetLoading && magnetTotal === 0
      ? 'Bt…'
      : magnetError && magnetTotal === 0
        ? 'Bt —'
        : `Bt ${magnetTotal}`;

  const statusHint = (() => {
    const parts: string[] = [];
    if (searchSource === 'sehua') {
      parts.push(loading && total === 0 ? '色花搜索中…' : `色花 ${total}`);
    } else {
      if (magnetLoading && magnetTotal === 0) parts.push('BT 搜索中…');
      else if (magnetError && magnetTotal === 0) parts.push('BT 不可用');
      else parts.push(`BT ${magnetTotal}`);
    }
    const ms =
      searchSource === 'sehua' ? costMs : Math.max(costMs, magnetCostMs);
    if (ms > 0) parts.push(`${ms}ms`);
    return parts.join(' · ');
  })();

  return (
    <>
      <div className="mk-code-search" ref={scrollRef}>
        <MakerCodeMetaCard code={code} region={cropRegion || region} />

        <div className="mk-dual-tabs" role="tablist" aria-label="搜索来源">
          <button
            type="button"
            role="tab"
            aria-selected={searchSource === 'sehua'}
            className={`mk-dual-tabs__btn${searchSource === 'sehua' ? ' is-active' : ''}`}
            onClick={() => onSourceChange('sehua')}
          >
            {sehuaTabLabel}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={searchSource === 'bitmagnet'}
            className={`mk-dual-tabs__btn${searchSource === 'bitmagnet' ? ' is-active' : ''}`}
            onClick={() => onSourceChange('bitmagnet')}
          >
            {btTabLabel}
          </button>
        </div>

        <p className="app-hint" style={{ marginTop: 0 }}>
          {statusHint}
        </p>
        {hint ? (
          <p className="app-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
            {hint}
          </p>
        ) : null}
        {searchSource === 'bitmagnet' && magnetError && magnetTotal === 0 ? (
          <p className="app-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
            Bitmagnet：{magnetError}
          </p>
        ) : null}

        {activeLoading ? (
          <SearchResultsLoading keyword={code} />
        ) : searchSource === 'sehua' && error && items.length === 0 ? (
          <div className="app-error">
            <p>{error}</p>
          </div>
        ) : activeEmpty ? (
          <div className="app-empty">
            <p>没有匹配结果</p>
            <p className="app-footnote" style={{ marginTop: 8 }}>
              可切换另一库，或到首页用不精确匹配再试
            </p>
          </div>
        ) : (
          <>
            <div className="bm-result-list">
              {searchSource === 'sehua'
                ? items.map((item) => (
                    <ResourceCard
                      key={item.hash}
                      item={item}
                      keywords={resultKeywords}
                      cropRegion={cropRegion || region}
                      onOpen={setDetailHash}
                    />
                  ))
                : magnetItems.map((item) => (
                    <MagnetCard
                      key={item.hash || item.infoHash || item.path}
                      item={item}
                      keywords={resultKeywords}
                      onOpen={setMagnetDetailHash}
                    />
                  ))}
            </div>
            <div className="home-infinite">
              <div
                ref={sentinelRef}
                className="home-infinite__sentinel"
                aria-hidden
              />
              {activeLoadingMore ? (
                <p className="app-loading">加载更多…</p>
              ) : null}
              {!activeHasMore &&
              (searchSource === 'sehua'
                ? items.length > 0
                : magnetItems.length > 0) ? (
                <p className="home-infinite__end">已全部加载</p>
              ) : null}
            </div>
          </>
        )}
      </div>

      {detailHash ? (
        <AppPush title="详情" onBack={() => setDetailHash(null)}>
          <ResourceDetailBody hash={detailHash} />
        </AppPush>
      ) : null}
      {magnetDetailHash ? (
        <AppPush title="详情" onBack={() => setMagnetDetailHash(null)}>
          <BitmagnetDetailBody hash={magnetDetailHash} />
        </AppPush>
      ) : null}
    </>
  );
}
