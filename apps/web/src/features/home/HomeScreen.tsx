'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ClipboardPaste, Sparkles } from 'lucide-react';
import {
  DEFAULT_MATCH_MODE,
  DEFAULT_SORT_TYPE,
  SEARCH_KEYWORD_LENGTH_MIN,
  SEARCH_PAGE_SIZE,
  normalizeFilterSize,
  normalizeFilterTime,
  normalizeMatchMode,
  normalizeSortType,
} from '@/config/search';
import {
  fetchBrowse,
  fetchMagnetSearch,
  fetchSearch,
  type MagnetHit,
} from '@/lib/api';
import type {
  FilterSize,
  FilterTime,
  MatchMode,
  ResourceItem,
  SortType,
} from '@/types/resource';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { useTabNavigation } from '@/shell';
import { HomeSearchField } from './HomeSearchField';
import { P115PastePanel } from './P115PastePanel';
import { ResourceCard } from './ResourceCard';
import { ResourceDetailBody } from './ResourceDetailBody';
import { SearchFilters } from './SearchFilters';
import { SearchResultsLoading } from './SearchResultsLoading';
import type { SearchSource } from './SourceSwitch';
import { LemonResultList } from '@/features/magnet/LemonResultList';

type Mode = 'landing' | 'results';

function parseSource(v?: string | null): SearchSource {
  return v === 'lemon' ? 'lemon' : 'sehua';
}

function syncDetailUrl(hash: string | null) {
  try {
    const url = new URL(window.location.href);
    if (hash) url.searchParams.set('detail', hash);
    else url.searchParams.delete('detail');
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== next) {
      window.history.replaceState(null, '', next);
    }
  } catch {
    /* ignore */
  }
}

function syncSearchUrl(opts: {
  mode: Mode;
  source: SearchSource;
  keyword: string;
  browsing: boolean;
  sortType: SortType;
  matchMode: MatchMode;
  filterTime: FilterTime;
  filterSize: FilterSize;
  region?: string | null;
}) {
  try {
    const url = new URL(window.location.href);
    const detail = url.searchParams.get('detail');
    url.search = '';
    if (opts.source === 'lemon') url.searchParams.set('source', 'lemon');
    if (opts.mode === 'landing') {
      // only source maybe
    } else if (opts.keyword.length >= SEARCH_KEYWORD_LENGTH_MIN) {
      url.searchParams.set('keyword', opts.keyword);
      if (opts.source === 'sehua') {
        url.searchParams.set('sortType', opts.sortType);
        url.searchParams.set('matchMode', opts.matchMode);
        url.searchParams.set('filterTime', opts.filterTime);
        url.searchParams.set('filterSize', opts.filterSize);
        if (opts.region) url.searchParams.set('region', opts.region);
      }
    } else if (opts.source === 'sehua' && opts.browsing) {
      url.searchParams.set('browse', '1');
    }
    if (detail) url.searchParams.set('detail', detail);
    const next = `${url.pathname}${url.search}${url.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (cur !== next) window.history.replaceState(null, '', next);
  } catch {
    /* ignore */
  }
}

/**
 * 搜索页 — 色花落地 + 色花堂/柠檬双源
 */
export function HomeScreen() {
  const tabCtx = useTabNavigation();
  const [mode, setMode] = useState<Mode>('landing');
  const [source, setSource] = useState<SearchSource>('sehua');
  const [draft, setDraft] = useState('');
  const [keyword, setKeyword] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const [sortType, setSortType] = useState<SortType>(DEFAULT_SORT_TYPE);
  const [matchMode, setMatchMode] = useState<MatchMode>(DEFAULT_MATCH_MODE);
  const [filterTime, setFilterTime] = useState<FilterTime>('all');
  const [filterSize, setFilterSize] = useState<FilterSize>('all');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [lemonItems, setLemonItems] = useState<MagnetHit[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [msg, setMsg] = useState('');
  const [pasteOpen, setPasteOpen] = useState(false);
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [searchRegion, setSearchRegion] = useState<string | null>(null);
  const [costMs, setCostMs] = useState(0);
  const reqId = useRef(0);
  const lemonPageRef = useRef(1);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const scrollBodyRef = useRef<HTMLDivElement | null>(null);
  const hydrated = useRef(false);
  const skipUrlWrite = useRef(false);

  const openDetail = useCallback((hash: string) => {
    setDetailHash(hash);
    syncDetailUrl(hash);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailHash(null);
    syncDetailUrl(null);
  }, []);

  function resetLists() {
    setItems([]);
    setLemonItems([]);
    setKeywords([]);
    setTotal(0);
    setHasMore(false);
    setError('');
    setCostMs(0);
  }

  function goLanding() {
    setMode('landing');
    setDraft('');
    setKeyword('');
    setBrowsing(false);
    setSearchRegion(null);
    setPage(1);
    resetLists();
    closeDetail();
  }

  // URL 恢复搜索态
  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    try {
      const sp = new URLSearchParams(window.location.search);
      const kw = (sp.get('keyword') || '').trim();
      const browse = sp.get('browse') === '1';
      const src = parseSource(sp.get('source'));
      const detail = sp.get('detail');
      skipUrlWrite.current = true;
      setSource(src);
      if (kw.length >= SEARCH_KEYWORD_LENGTH_MIN) {
        setDraft(kw);
        setKeyword(kw);
        setBrowsing(false);
        setSortType(normalizeSortType(sp.get('sortType')));
        setMatchMode(normalizeMatchMode(sp.get('matchMode')));
        setFilterTime(normalizeFilterTime(sp.get('filterTime')));
        setFilterSize(normalizeFilterSize(sp.get('filterSize')));
        setSearchRegion(sp.get('region')?.trim() || null);
        setPage(1);
        setMode('results');
      } else if (browse && src === 'sehua') {
        setDraft('');
        setKeyword('');
        setBrowsing(true);
        setPage(1);
        setMode('results');
      }
      if (detail) {
        setDetailHash(decodeURIComponent(detail));
        if (kw.length < SEARCH_KEYWORD_LENGTH_MIN && !browse) {
          setMode('results');
          setBrowsing(true);
        }
      }
      queueMicrotask(() => {
        skipUrlWrite.current = false;
      });
    } catch {
      skipUrlWrite.current = false;
    }
  }, []);

  // 写回 URL（不含无限滚动 page）
  useEffect(() => {
    if (!hydrated.current || skipUrlWrite.current) return;
    if (tabCtx && tabCtx.activeTab !== '/') return;
    syncSearchUrl({
      mode,
      source,
      keyword,
      browsing,
      sortType,
      matchMode,
      filterTime,
      filterSize,
      region: searchRegion,
    });
  }, [
    tabCtx?.activeTab,
    mode,
    source,
    keyword,
    browsing,
    sortType,
    matchMode,
    filterTime,
    filterSize,
    searchRegion,
  ]);

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/') return;
    if (tabCtx.tabReselect > 0) goLanding();
  }, [tabCtx?.tabReselect]);

  useEffect(() => {
    const onSearchEvent = () => {
      try {
        const key = sessionStorage.getItem('nextweb:home-search');
        if (!key) return;
        const modeFlag = sessionStorage.getItem('nextweb:home-mode');
        const region = sessionStorage.getItem('nextweb:home-prefix-region');
        sessionStorage.removeItem('nextweb:home-search');
        sessionStorage.removeItem('nextweb:home-mode');
        sessionStorage.removeItem('nextweb:home-prefix-region');
        const next = key.trim();
        if (next.length < SEARCH_KEYWORD_LENGTH_MIN) return;
        setSource('sehua');
        setDraft(next);
        setKeyword(next);
        setBrowsing(false);
        setMatchMode('exact');
        setSortType(DEFAULT_SORT_TYPE);
        setFilterTime('all');
        setFilterSize('all');
        setSearchRegion(region?.trim() || null);
        setPage(1);
        resetLists();
        closeDetail();
        setMode('results');
        setReloadToken((n) => n + 1);
        void modeFlag;
      } catch {
        /* ignore */
      }
    };
    window.addEventListener('nextweb:home-search', onSearchEvent);
    return () => window.removeEventListener('nextweb:home-search', onSearchEvent);
  }, [closeDetail]);

  function changeSource(next: SearchSource) {
    if (next === source) return;
    setSource(next);
    setPage(1);
    setSearchRegion(null);
    resetLists();
    if (mode === 'results') {
      if (keyword.length >= SEARCH_KEYWORD_LENGTH_MIN) {
        setBrowsing(false);
        setReloadToken((n) => n + 1);
      } else if (next === 'lemon') {
        setMode('landing');
      }
    }
  }

  function submitSearch(raw?: string) {
    const next = (raw ?? draft).trim();
    if (!next) return;
    if (next.length < SEARCH_KEYWORD_LENGTH_MIN) {
      setMsg(`请输入至少 ${SEARCH_KEYWORD_LENGTH_MIN} 个字符`);
      return;
    }
    setDraft(next);
    setKeyword(next);
    setBrowsing(false);
    setSearchRegion(null);
    setPage(1);
    resetLists();
    setMode('results');
    setReloadToken((n) => n + 1);
  }

  function browseLatest() {
    if (source !== 'sehua') {
      setMsg('浏览最新仅支持色花堂');
      return;
    }
    setDraft('');
    setKeyword('');
    setBrowsing(true);
    setSearchRegion(null);
    setPage(1);
    resetLists();
    setMode('results');
    setReloadToken((n) => n + 1);
  }

  // 柠檬：第 1 页；更多用按钮
  useEffect(() => {
    if (mode !== 'results' || source !== 'lemon') return;
    if (keyword.length < SEARCH_KEYWORD_LENGTH_MIN) return;
    const id = ++reqId.current;
    const ac = new AbortController();
    lemonPageRef.current = 1;
    setLoading(true);
    setLoadingMore(false);
    setLemonItems([]);
    setError('');
    setHasMore(false);

    (async () => {
      const t0 = performance.now();
      try {
        const data = await fetchMagnetSearch({
          keyword,
          page: 1,
          signal: ac.signal,
        });
        if (id !== reqId.current) return;
        const batch = data.items || [];
        setLemonItems(batch);
        setTotal(batch.length);
        setHasMore(Boolean(data.hasMore));
        setCostMs(data.costMs || Math.round(performance.now() - t0));
        if (!batch.length) setMsg('没有匹配结果');
      } catch (e) {
        if (
          ac.signal.aborted ||
          id !== reqId.current ||
          (e instanceof DOMException && e.name === 'AbortError') ||
          (e instanceof Error && e.name === 'AbortError')
        ) {
          return;
        }
        setLemonItems([]);
        setTotal(0);
        setHasMore(false);
        const m = e instanceof Error ? e.message : '加载失败';
        setError(m);
        setMsg(m);
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    })();

    return () => ac.abort();
  }, [mode, source, keyword, reloadToken]);

  async function loadMoreLemon() {
    if (source !== 'lemon' || loading || loadingMore || !hasMore) return;
    const next = lemonPageRef.current + 1;
    setLoadingMore(true);
    try {
      const data = await fetchMagnetSearch({ keyword, page: next });
      const batch = data.items || [];
      lemonPageRef.current = next;
      setLemonItems((prev) => {
        const seen = new Set(prev.map((x) => x.path));
        return [...prev, ...batch.filter((x) => !seen.has(x.path))];
      });
      setTotal((prev) => prev + batch.length);
      setHasMore(Boolean(data.hasMore));
      if (!batch.length) setHasMore(false);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoadingMore(false);
    }
  }

  // 色花堂拉取
  useEffect(() => {
    if (mode !== 'results') return;
    if (source === 'lemon') return;
    const id = ++reqId.current;
    const ac = new AbortController();
    const append = page > 1;
    if (append) setLoadingMore(true);
    else {
      setLoading(true);
      setItems([]);
    }
    setError('');

    (async () => {
      const t0 = performance.now();
      try {
        if (!browsing && keyword.length >= SEARCH_KEYWORD_LENGTH_MIN) {
          const region = searchRegion || undefined;
          const data = await fetchSearch({
            keyword,
            page,
            pageSize: SEARCH_PAGE_SIZE,
            sortType,
            filterTime,
            filterSize,
            matchMode,
            withTotalCount: false,
            preferChinese: false,
            preferCrack: false,
            region,
            signal: ac.signal,
          });
          if (id !== reqId.current) return;
          setItems((prev) => (append ? [...prev, ...data.resources] : data.resources));
          setKeywords(data.keywords?.length ? data.keywords : [keyword]);
          setHasMore(data.has_more);
          if (!append) {
            setTotal(data.total_count);
            setCostMs(Math.round(performance.now() - t0));
          }

          if (!append) {
            void fetchSearch({
              keyword,
              page,
              pageSize: SEARCH_PAGE_SIZE,
              sortType,
              filterTime,
              filterSize,
              matchMode,
              countOnly: true,
              preferChinese: false,
              preferCrack: false,
              region,
              signal: ac.signal,
            })
              .then((c) => {
                if (id !== reqId.current) return;
                setTotal(c.total_count);
              })
              .catch(() => {});
          }
        } else {
          const data = await fetchBrowse({
            page,
            pageSize: SEARCH_PAGE_SIZE,
            signal: ac.signal,
          });
          if (id !== reqId.current) return;
          setItems((prev) => (append ? [...prev, ...data.resources] : data.resources));
          setKeywords([]);
          setTotal(data.total_count);
          setHasMore(data.has_more);
          if (!append) setCostMs(Math.round(performance.now() - t0));
        }
      } catch (e) {
        if (
          ac.signal.aborted ||
          id !== reqId.current ||
          (e instanceof DOMException && e.name === 'AbortError') ||
          (e instanceof Error && e.name === 'AbortError')
        ) {
          return;
        }
        if (!append) {
          setItems([]);
          setTotal(0);
        }
        setHasMore(false);
        const m = e instanceof Error ? e.message : '加载失败';
        setError(m);
        setMsg(m === 'Not Found' ? '搜索接口未就绪，请重启 API 后再试' : m);
      } finally {
        if (id === reqId.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    })();

    return () => ac.abort();
  }, [
    mode,
    source,
    keyword,
    browsing,
    page,
    sortType,
    matchMode,
    filterTime,
    filterSize,
    reloadToken,
    searchRegion,
  ]);

  // 色花堂无限滚动
  useEffect(() => {
    if (mode !== 'results' || source !== 'sehua' || detailHash) return;
    if (!hasMore || loading || loadingMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setPage((p) => p + 1);
        }
      },
      { root: scrollBodyRef.current, rootMargin: '240px 0px', threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [mode, source, detailHash, hasMore, loading, loadingMore, items.length]);

  const isKeywordSearch = !browsing && keyword.length >= SEARCH_KEYWORD_LENGTH_MIN;
  const hint =
    source === 'lemon'
      ? total > 0
        ? `已加载 ${total} 条${costMs > 0 ? ` · ${costMs}ms` : ''}`
        : '磁力柠檬'
      : isKeywordSearch
        ? total > 0
          ? `找到 ${total} 条${costMs > 0 ? ` · ${costMs}ms` : ''}${searchRegion ? ' · 分区' : ''}`
          : '搜索结果'
        : '最新资源';

  function onFilterChange<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
      resetLists();
    };
  }

  const searchField = (opts: { size: 'hero' | 'compact'; showSource: boolean }) => (
    <HomeSearchField
      draft={draft}
      size={opts.size}
      busy={loading && !loadingMore}
      showSource={opts.showSource}
      source={source}
      onSourceChange={changeSource}
      onDraftChange={setDraft}
      onSubmit={() => submitSearch()}
      onClear={() => {
        setDraft('');
        if (opts.size === 'compact' && source === 'lemon') {
          goLanding();
          return;
        }
        if (opts.size === 'compact' && !browsing) goLanding();
      }}
    />
  );

  return (
    <div className="app-stack-root">
      {mode === 'landing' ? (
        <div className="home-landing">
          <div className="home-landing__toolbar" role="toolbar" aria-label="快捷操作">
            {source === 'sehua' ? (
              <button type="button" className="home-landing__chip" onClick={browseLatest}>
                <span className="home-landing__chip-ico" aria-hidden>
                  <Sparkles size={13} strokeWidth={2.4} />
                </span>
                <span className="home-landing__chip-txt">最新</span>
              </button>
            ) : null}
            <button
              type="button"
              className="home-landing__chip"
              onClick={() => setPasteOpen(true)}
            >
              <span className="home-landing__chip-ico" aria-hidden>
                <ClipboardPaste size={13} strokeWidth={2.4} />
              </span>
              <span className="home-landing__chip-txt">转存</span>
            </button>
          </div>
          <div className="home-landing__hero">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="home-landing__rose"
              src="/brand/logo.png"
              alt=""
              width={156}
              height={156}
              decoding="async"
            />
            <h1 className="home-landing__title">资源仓库</h1>
            <p className="home-landing__sub">片名 · 番号 · 关键词</p>
            {searchField({ size: 'hero', showSource: true })}
          </div>
          {msg ? (
            <div className="home-landing__msg">
              <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="home-search-screen" aria-hidden={detailHash != null}>
          <header className="home-results-header">
            <button
              type="button"
              className="home-results-brand"
              onClick={goLanding}
              aria-label="回资源仓库首页"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                className="home-results-brand__logo"
                src="/brand/logo.png"
                alt=""
                width={44}
                height={44}
                decoding="async"
              />
            </button>
            {searchField({ size: 'compact', showSource: false })}
          </header>

          <div className="app-body home-search-body" ref={scrollBodyRef}>
            {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}

            {source === 'sehua' && isKeywordSearch ? (
              <SearchFilters
                sortType={sortType}
                matchMode={matchMode}
                filterTime={filterTime}
                filterSize={filterSize}
                onSortType={onFilterChange(setSortType)}
                onMatchMode={onFilterChange(setMatchMode)}
                onFilterTime={onFilterChange(setFilterTime)}
                onFilterSize={onFilterChange(setFilterSize)}
              />
            ) : null}

            <p className="app-hint">{hint}</p>

            {loading &&
            ((source === 'sehua' && items.length === 0) ||
              (source === 'lemon' && lemonItems.length === 0)) ? (
              <SearchResultsLoading keyword={isKeywordSearch ? keyword : undefined} />
            ) : error &&
              ((source === 'sehua' && items.length === 0) ||
                (source === 'lemon' && lemonItems.length === 0)) ? (
              <div className="app-error">
                <p>{error}</p>
                {source === 'sehua' ? (
                  <p className="app-error-hint">请到「设置 → 资源数据库」配置 DSN</p>
                ) : (
                  <p className="app-error-hint">柠檬代搜需本机已装浏览器内核</p>
                )}
                <div className="app-actions" style={{ justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="app-btn-secondary"
                    onClick={() => {
                      setPage(1);
                      setReloadToken((n) => n + 1);
                    }}
                  >
                    重试
                  </button>
                </div>
              </div>
            ) : source === 'sehua' ? (
              items.length === 0 ? (
                <div className="app-empty">
                  <p>{isKeywordSearch ? '没有匹配结果' : '暂无资源'}</p>
                  {isKeywordSearch ? (
                    <p className="app-footnote" style={{ marginTop: 8 }}>
                      试试更短的关键词，或放宽筛选
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="resource-list">
                  {items.map((item) => (
                    <ResourceCard
                      key={item.hash}
                      item={item}
                      keywords={keywords}
                      cropRegion={searchRegion || undefined}
                      onOpen={openDetail}
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
              )
            ) : lemonItems.length === 0 ? (
              <div className="app-empty">
                <p>没有匹配结果</p>
              </div>
            ) : (
              <>
                <LemonResultList
                  keyword={keyword}
                  items={lemonItems}
                  onItemsChange={setLemonItems}
                />
                <div className="home-infinite">
                  {hasMore ? (
                    <button
                      type="button"
                      className={`home-lemon-more${loadingMore ? ' is-loading' : ''}`}
                      disabled={loadingMore}
                      onClick={() => void loadMoreLemon()}
                    >
                      {loadingMore ? (
                        <>
                          <span className="home-lemon-more__spin" aria-hidden />
                          加载中…
                        </>
                      ) : (
                        '加载更多'
                      )}
                    </button>
                  ) : (
                    <p className="home-infinite__end">没有更多了</p>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {detailHash ? (
        <AppPush title="详情" onBack={closeDetail}>
          <ResourceDetailBody hash={detailHash} />
        </AppPush>
      ) : null}

      {pasteOpen ? <P115PastePanel onBack={() => setPasteOpen(false)} /> : null}
    </div>
  );
}
