'use client';

import { useEffect, useRef, useState } from 'react';
import { AppPush } from '@/components/ui/AppPush';
import { SEARCH_PAGE_SIZE } from '@/config/search';
import { ResourceCard } from '@/features/home/ResourceCard';
import { ResourceDetailBody } from '@/features/home/ResourceDetailBody';
import { SearchResultsLoading } from '@/features/home/SearchResultsLoading';
import { getBrowsePreferences } from '@/hooks/useBrowsePreferences';
import { fetchSearch } from '@/lib/api';
import { filterByBrowsePrefs } from '@/lib/browsePreferFilter';
import type { ResourceItem } from '@/types/resource';
import { MakerCodeMetaCard } from './MakerCodeMetaCard';

const POOL_PAGE_SIZE = 40;
const MAX_POOL_PAGES = 5;

/**
 * 片商内番号库搜：精确匹配 + 分区。
 * 本地索引 ≠ 库搜命中：索引只保证扫到过封面/标题；库搜还受分区与中文·破解影响。
 * 对齐色花：先拉无倾向底池，倾向在本地投影；空则回退。
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
  /** 七区 id，用于封面裁剪；缺省回退 region / 详情 region */
  cropRegion?: string;
  prefsTick?: number;
  applyBrowsePrefs?: boolean;
}) {
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [costMs, setCostMs] = useState(0);
  const [hint, setHint] = useState('');
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const poolRef = useRef<ResourceItem[]>([]);
  const reqId = useRef(0);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPage(1);
    setItems([]);
    setTotal(0);
    setHasMore(false);
    setError('');
    setCostMs(0);
    setHint('');
    poolRef.current = [];
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

        // 分区裁板后空：回退全库精确匹配（索引封面板与库搜板可能不一致）
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
    if (page <= 1) return;
    setLoadingMore(true);
    const pool = poolRef.current;
    const slice = pool.slice(0, page * SEARCH_PAGE_SIZE);
    setItems(slice);
    setHasMore(slice.length < pool.length);
    setLoadingMore(false);
  }, [page]);

  useEffect(() => {
    if (!hasMore || loading || loadingMore || detailHash) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setPage((p) => p + 1);
        }
      },
      { root: scrollRef.current, rootMargin: '240px 0px', threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loading, loadingMore, items.length, detailHash]);

  return (
    <>
      <div className="mk-code-search" ref={scrollRef}>
        <MakerCodeMetaCard code={code} region={cropRegion || region} />
        <p className="app-hint" style={{ marginTop: 0 }}>
          {loading && items.length === 0
            ? '搜索中…'
            : total > 0
              ? `找到 ${total} 条${costMs > 0 ? ` · ${costMs}ms` : ''}${region ? ' · 分区' : ''}`
              : '搜索结果'}
        </p>
        {hint ? (
          <p className="app-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
            {hint}
          </p>
        ) : null}
        {loading && items.length === 0 ? (
          <SearchResultsLoading keyword={code} />
        ) : error && items.length === 0 ? (
          <div className="app-error">
            <p>{error}</p>
          </div>
        ) : items.length === 0 ? (
          <div className="app-empty">
            <p>没有匹配结果</p>
            <p className="app-footnote" style={{ marginTop: 8 }}>
              本地索引有封面≠资源库有帖。可到首页用不精确匹配再试
            </p>
          </div>
        ) : (
          <div className="resource-list">
            {items.map((item) => (
              <ResourceCard
                key={item.hash}
                item={item}
                keywords={keywords}
                cropRegion={region}
                onOpen={setDetailHash}
              />
            ))}
            <div className="home-infinite">
              <div ref={sentinelRef} className="home-infinite__sentinel" aria-hidden />
              {loadingMore ? <p className="app-loading">加载更多…</p> : null}
              {!hasMore && items.length > 0 ? (
                <p className="home-infinite__end">已全部加载</p>
              ) : null}
            </div>
          </div>
        )}
      </div>
      {detailHash ? (
        <AppPush title="详情" onBack={() => setDetailHash(null)}>
          <ResourceDetailBody hash={detailHash} />
        </AppPush>
      ) : null}
    </>
  );
}
