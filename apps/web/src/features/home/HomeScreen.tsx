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
import type { FeedSource } from '@/lib/mixedSearch';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { useTabNavigation } from '@/shell';
import { HomeSearchField } from './HomeSearchField';
import { P115PastePanel } from './P115PastePanel';
import { ResourceDetailBody } from './ResourceDetailBody';
import { ResourceCard } from './ResourceCard';
import { SearchFilters } from './SearchFilters';
import { SearchResultsLoading } from './SearchResultsLoading';
import { BitmagnetDetailBody } from '@/features/magnet/BitmagnetDetailBody';
import { MagnetCard } from '@/features/magnet/BitmagnetResultList';
import type { SearchSource } from './SourceSwitch';

type Mode = 'landing' | 'results';

function syncDetailUrl(hash: string | null, source?: FeedSource) {
  try {
    const url = new URL(window.location.href);
    if (hash) {
      url.searchParams.set('detail', hash);
      if (source === 'bitmagnet') url.searchParams.set('ds', 'bitmagnet');
      else url.searchParams.delete('ds');
    } else {
      url.searchParams.delete('detail');
      url.searchParams.delete('ds');
    }
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (
      `${window.location.pathname}${window.location.search}${window.location.hash}` !==
      next
    ) {
      window.history.replaceState(null, '', next);
    }
  } catch {
    /* ignore */
  }
}

function syncSearchUrl(opts: {
  mode: Mode;
  keyword: string;
  browsing: boolean;
  sortType: SortType;
  matchMode: MatchMode;
  filterTime: FilterTime;
  filterSize: FilterSize;
  region?: string | null;
  searchSource?: SearchSource;
}) {
  try {
    const url = new URL(window.location.href);
    const detail = url.searchParams.get('detail');
    const ds = url.searchParams.get('ds');
    url.search = '';
    if (opts.mode === 'landing') {
      // keep empty
    } else if (opts.keyword.length >= SEARCH_KEYWORD_LENGTH_MIN) {
      url.searchParams.set('keyword', opts.keyword);
      url.searchParams.set('sortType', opts.sortType);
      url.searchParams.set('filterTime', opts.filterTime);
      url.searchParams.set('filterSize', opts.filterSize);
      url.searchParams.set('matchMode', opts.matchMode);
      if (opts.region) url.searchParams.set('region', opts.region);
      if (opts.searchSource === 'bitmagnet') {
        url.searchParams.set('src', 'bitmagnet');
      } else {
        url.searchParams.delete('src');
      }
    } else if (opts.browsing) {
      url.searchParams.set('browse', '1');
    }
    if (detail) url.searchParams.set('detail', detail);
    if (ds === 'bitmagnet') url.searchParams.set('ds', 'bitmagnet');
    const next = `${url.pathname}${url.search}${url.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (cur !== next) window.history.replaceState(null, '', next);
  } catch {
    /* ignore */
  }
}

/**
 * 搜索页 — 一关键字双库并行，色花堂 / Bitmagnet 分 Tab 展示
 */
export function HomeScreen() {
  const tabCtx = useTabNavigation();
  const [mode, setMode] = useState<Mode>('landing');
  const [draft, setDraft] = useState('');
  const [keyword, setKeyword] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const [sortType, setSortType] = useState<SortType>(DEFAULT_SORT_TYPE);
  const [matchMode, setMatchMode] = useState<MatchMode>(DEFAULT_MATCH_MODE);
  const [filterTime, setFilterTime] = useState<FilterTime>('all');
  const [filterSize, setFilterSize] = useState<FilterSize>('all');
  const [sehuaPage, setSehualPage] = useState(1);
  const [magnetPage, setMagnetPage] = useState(1);
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [magnetItems, setMagnetItems] = useState<MagnetHit[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [sehuaTotal, setSehualTotal] = useState(0);
  const [magnetTotal, setMagnetTotal] = useState(0);
  const [sehuaHasMore, setSehualHasMore] = useState(false);
  const [magnetHasMore, setMagnetHasMore] = useState(false);
  const [error, setError] = useState('');
  const [magnetError, setMagnetError] = useState('');
  const [sehuaLoading, setSehualLoading] = useState(false);
  const [magnetLoading, setMagnetLoading] = useState(false);
  const [sehuaLoadingMore, setSehualLoadingMore] = useState(false);
  const [magnetLoadingMore, setMagnetLoadingMore] = useState(false);
  const [msg, setMsg] = useState('');
  const [pasteOpen, setPasteOpen] = useState(false);
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const [detailSource, setDetailSource] = useState<FeedSource>('sehua');
  const [reloadToken, setReloadToken] = useState(0);
  const [searchRegion, setSearchRegion] = useState<string | null>(null);
  const [searchSource, setSearchSource] = useState<SearchSource>('sehua');
  const [costMs, setCostMs] = useState(0);
  const [magnetCostMs, setMagnetCostMs] = useState(0);
  const sehuaReqId = useRef(0);
  const magnetReqId = useRef(0);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const scrollBodyRef = useRef<HTMLDivElement | null>(null);
  const hydrated = useRef(false);
  const skipUrlWrite = useRef(false);

  const openSehualDetail = useCallback((hash: string) => {
    setDetailSource('sehua');
    setDetailHash(hash);
    syncDetailUrl(hash, 'sehua');
  }, []);

  const openMagnetDetail = useCallback((hash: string) => {
    setDetailSource('bitmagnet');
    setDetailHash(hash);
    syncDetailUrl(hash, 'bitmagnet');
  }, []);

  const closeDetail = useCallback(() => {
    setDetailHash(null);
    syncDetailUrl(null);
  }, []);

  function resetLists() {
    setItems([]);
    setMagnetItems([]);
    setKeywords([]);
    setSehualTotal(0);
    setMagnetTotal(0);
    setSehualHasMore(false);
    setMagnetHasMore(false);
    setError('');
    setMagnetError('');
    setCostMs(0);
    setMagnetCostMs(0);
  }

  const onSearchSourceChange = useCallback((next: SearchSource) => {
    setSearchSource(next);
    scrollBodyRef.current?.scrollTo({ top: 0 });
  }, []);

  function goLanding() {
    setMode('landing');
    setDraft('');
    setKeyword('');
    setBrowsing(false);
    setSearchRegion(null);
    setSearchSource('sehua');
    setSehualPage(1);
    setMagnetPage(1);
    resetLists();
    closeDetail();
  }

  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    try {
      const sp = new URLSearchParams(window.location.search);
      const kw = (sp.get('keyword') || '').trim();
      const browse = sp.get('browse') === '1';
      const detail = sp.get('detail');
      const ds = sp.get('ds') === 'bitmagnet' ? 'bitmagnet' : 'sehua';
      const src =
        sp.get('src') === 'bitmagnet' ? ('bitmagnet' as const) : ('sehua' as const);
      skipUrlWrite.current = true;
      if (kw.length >= SEARCH_KEYWORD_LENGTH_MIN) {
        setDraft(kw);
        setKeyword(kw);
        setBrowsing(false);
        setSortType(normalizeSortType(sp.get('sortType')));
        setMatchMode(normalizeMatchMode(sp.get('matchMode')));
        setFilterTime(normalizeFilterTime(sp.get('filterTime')));
        setFilterSize(normalizeFilterSize(sp.get('filterSize')));
        setSearchRegion(sp.get('region')?.trim() || null);
        setSearchSource(src);
        setSehualPage(1);
        setMagnetPage(1);
        setMode('results');
      } else if (browse) {
        setDraft('');
        setKeyword('');
        setBrowsing(true);
        setSearchSource('sehua');
        setSehualPage(1);
        setMode('results');
      }
      if (detail) {
        setDetailSource(ds);
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

  useEffect(() => {
    if (!hydrated.current || skipUrlWrite.current) return;
    if (tabCtx && tabCtx.activeTab !== '/') return;
    syncSearchUrl({
      mode,
      keyword,
      browsing,
      sortType,
      matchMode,
      filterTime,
      filterSize,
      region: searchRegion,
      searchSource,
    });
  }, [
    tabCtx?.activeTab,
    mode,
    keyword,
    browsing,
    sortType,
    matchMode,
    filterTime,
    filterSize,
    searchRegion,
    searchSource,
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
        const region = sessionStorage.getItem('nextweb:home-prefix-region');
        sessionStorage.removeItem('nextweb:home-search');
        sessionStorage.removeItem('nextweb:home-mode');
        sessionStorage.removeItem('nextweb:home-prefix-region');
        const next = key.trim();
        if (next.length < SEARCH_KEYWORD_LENGTH_MIN) return;
        setDraft(next);
        setKeyword(next);
        setBrowsing(false);
        setMatchMode('exact');
        setSortType(DEFAULT_SORT_TYPE);
        setFilterTime('all');
        setFilterSize('all');
        setSearchRegion(region?.trim() || null);
        setSehualPage(1);
        setMagnetPage(1);
        resetLists();
        closeDetail();
        setMode('results');
        setReloadToken((n) => n + 1);
      } catch {
        /* ignore */
      }
    };
    window.addEventListener('nextweb:home-search', onSearchEvent);
    return () => window.removeEventListener('nextweb:home-search', onSearchEvent);
  }, [closeDetail]);

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
    setSehualPage(1);
    setMagnetPage(1);
    resetLists();
    setMode('results');
    setReloadToken((n) => n + 1);
  }

  function browseLatest() {
    setDraft('');
    setKeyword('');
    setBrowsing(true);
    setSearchRegion(null);
    setSehualPage(1);
    setMagnetPage(1);
    setMagnetItems([]);
    setMagnetTotal(0);
    setMagnetHasMore(false);
    setMagnetError('');
    setMagnetLoading(false);
    setMagnetLoadingMore(false);
    setItems([]);
    setSehualTotal(0);
    setError('');
    setCostMs(0);
    setMode('results');
    setReloadToken((n) => n + 1);
  }

  const isKeywordSearch = !browsing && keyword.length >= SEARCH_KEYWORD_LENGTH_MIN;

  // 色花堂
  useEffect(() => {
    if (mode !== 'results') return;
    if (!browsing && keyword.length < SEARCH_KEYWORD_LENGTH_MIN) return;
    const id = ++sehuaReqId.current;
    const ac = new AbortController();
    const append = sehuaPage > 1;
    if (append) setSehualLoadingMore(true);
    else {
      setSehualLoading(true);
      setItems([]);
    }
    setError('');

    void (async () => {
      const t0 = performance.now();
      try {
        if (isKeywordSearch) {
          const region = searchRegion || undefined;
          const data = await fetchSearch({
            keyword,
            page: sehuaPage,
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
          if (id !== sehuaReqId.current) return;
          setItems((prev) => {
            if (!append) return data.resources;
            const seen = new Set(prev.map((x) => x.hash));
            return [
              ...prev,
              ...data.resources.filter((x) => !seen.has(x.hash)),
            ];
          });
          setKeywords(data.keywords?.length ? data.keywords : [keyword]);
          setSehualHasMore(data.has_more);
          if (!append) {
            setSehualTotal(data.total_count);
            setCostMs(Math.round(performance.now() - t0));
          }
          // 时间=全部时精确 COUNT 极慢；列表已有 has_more，延后/跳过总数
          if (!append && filterTime !== 'all') {
            void fetchSearch({
              keyword,
              page: sehuaPage,
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
                if (id !== sehuaReqId.current) return;
                setSehualTotal(c.total_count);
              })
              .catch(() => {});
          }
        } else {
          const data = await fetchBrowse({
            page: sehuaPage,
            pageSize: SEARCH_PAGE_SIZE,
            signal: ac.signal,
          });
          if (id !== sehuaReqId.current) return;
          setItems((prev) => {
            if (!append) return data.resources;
            const seen = new Set(prev.map((x) => x.hash));
            return [
              ...prev,
              ...data.resources.filter((x) => !seen.has(x.hash)),
            ];
          });
          setKeywords([]);
          setSehualTotal(data.total_count);
          setSehualHasMore(data.has_more);
          if (!append) setCostMs(Math.round(performance.now() - t0));
        }
      } catch (e) {
        if (
          ac.signal.aborted ||
          id !== sehuaReqId.current ||
          (e instanceof DOMException && e.name === 'AbortError') ||
          (e instanceof Error && e.name === 'AbortError')
        ) {
          return;
        }
        if (!append) {
          setItems([]);
          setSehualTotal(0);
        }
        setSehualHasMore(false);
        const m = e instanceof Error ? e.message : '加载失败';
        setError(m);
        setMsg(m === 'Not Found' ? '搜索接口未就绪，请重启 API 后再试' : m);
      } finally {
        if (id === sehuaReqId.current) {
          setSehualLoading(false);
          setSehualLoadingMore(false);
        }
      }
    })();

    return () => ac.abort();
  }, [
    mode,
    keyword,
    browsing,
    isKeywordSearch,
    sehuaPage,
    sortType,
    matchMode,
    filterTime,
    filterSize,
    reloadToken,
    searchRegion,
  ]);

  // Bitmagnet（仅关键词搜索，且当前选中 Bitmagnet 页签时才请求，避免拖慢色花堂）
  useEffect(() => {
    if (mode !== 'results' || !isKeywordSearch) {
      setMagnetLoading(false);
      setMagnetLoadingMore(false);
      return;
    }
    if (searchSource !== 'bitmagnet') {
      setMagnetLoading(false);
      setMagnetLoadingMore(false);
      return;
    }
    const id = ++magnetReqId.current;
    const ac = new AbortController();
    const append = magnetPage > 1;
    if (append) setMagnetLoadingMore(true);
    else {
      setMagnetLoading(true);
      setMagnetItems([]);
    }
    setMagnetError('');

    void (async () => {
      const t0 = performance.now();
      try {
        const data = await fetchMagnetSearch({
          keyword,
          page: magnetPage,
          sortType,
          filterTime,
          filterSize,
          signal: ac.signal,
        });
        if (id !== magnetReqId.current) return;
        const batch = data.items || [];
        setMagnetItems((prev) => {
          if (!append) return batch;
          const seen = new Set(
            prev.map((x) => x.hash || x.infoHash || x.path),
          );
          return [
            ...prev,
            ...batch.filter(
              (x) => !seen.has(x.hash || x.infoHash || x.path),
            ),
          ];
        });
        setMagnetHasMore(Boolean(data.hasMore));
        if (!append) {
          setMagnetTotal(data.total ?? batch.length);
          setMagnetCostMs(data.costMs || Math.round(performance.now() - t0));
        }
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
  }, [
    mode,
    isKeywordSearch,
    keyword,
    magnetPage,
    sortType,
    filterTime,
    filterSize,
    reloadToken,
    searchSource,
  ]);

  const activeSource: SearchSource = browsing ? 'sehua' : searchSource;
  const resultKeywords = keywords.length ? keywords : keyword ? [keyword] : [];
  const activeItems = activeSource === 'sehua' ? items : magnetItems;
  const activeLoading =
    activeSource === 'sehua'
      ? sehuaLoading && items.length === 0
      : magnetLoading && magnetItems.length === 0;
  const activeLoadingMore =
    activeSource === 'sehua' ? sehuaLoadingMore : magnetLoadingMore;
  const activeHasMore = activeSource === 'sehua' ? sehuaHasMore : magnetHasMore;
  const activeEmpty =
    !activeLoading &&
    activeItems.length === 0 &&
    !(activeSource === 'sehua'
      ? sehuaLoading
      : isKeywordSearch && magnetLoading);

  useEffect(() => {
    if (mode !== 'results' || detailHash) return;
    if (!activeHasMore || activeLoading || activeLoadingMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        if (activeSource === 'sehua') {
          if (sehuaHasMore) setSehualPage((p) => p + 1);
        } else if (magnetHasMore) {
          setMagnetPage((p) => p + 1);
        }
      },
      { root: scrollBodyRef.current, rootMargin: '240px 0px', threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [
    mode,
    detailHash,
    activeHasMore,
    activeLoading,
    activeLoadingMore,
    activeSource,
    sehuaHasMore,
    magnetHasMore,
    activeItems.length,
  ]);

  const hint = isKeywordSearch
    ? activeSource === 'sehua'
      ? (() => {
          const parts: string[] = [];
          if (sehuaLoading && sehuaTotal === 0) parts.push('加载中…');
          else parts.push(`${sehuaTotal} 条`);
          if (costMs > 0) parts.push(`${costMs}ms`);
          if (searchRegion) parts.push('分区');
          return parts.join(' · ');
        })()
      : (() => {
          const parts: string[] = [];
          if (magnetLoading && magnetTotal === 0) parts.push('加载中…');
          else if (magnetError && magnetTotal === 0) parts.push('不可用');
          else parts.push(`${magnetTotal} 条`);
          if (magnetCostMs > 0) parts.push(`${magnetCostMs}ms`);
          return parts.join(' · ');
        })()
    : sehuaTotal > 0
      ? `最新 · ${sehuaTotal} 条`
      : '最新资源';

  function onFilterChange<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setSehualPage(1);
      setMagnetPage(1);
      resetLists();
    };
  }

  const searchField = (opts: { size: 'hero' | 'compact' }) => (
    <HomeSearchField
      draft={draft}
      size={opts.size}
      busy={activeLoading && !activeLoadingMore}
      onDraftChange={setDraft}
      onSubmit={() => submitSearch()}
      onClear={() => {
        setDraft('');
        if (opts.size === 'compact' && !browsing) goLanding();
      }}
    />
  );

  return (
    <div className="app-stack-root">
      {mode === 'landing' ? (
        <div className="home-landing">
          <div className="home-landing__toolbar" role="toolbar" aria-label="快捷操作">
            <button type="button" className="home-landing__chip" onClick={browseLatest}>
              <span className="home-landing__chip-ico" aria-hidden>
                <Sparkles size={13} strokeWidth={2.4} />
              </span>
              <span className="home-landing__chip-txt">最新</span>
            </button>
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
            <p className="home-landing__sub">片名 · 番号 · 关键词 · 双库同搜</p>
            {searchField({ size: 'hero' })}
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
            {searchField({ size: 'compact' })}
          </header>

          <div className="app-body home-search-body" ref={scrollBodyRef}>
            {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}

            {isKeywordSearch ? (
              <SearchFilters
                sortType={sortType}
                matchMode={matchMode}
                filterTime={filterTime}
                filterSize={filterSize}
                showMatch
                showSource
                searchSource={searchSource}
                onSearchSourceChange={onSearchSourceChange}
                onSortType={onFilterChange(setSortType)}
                onMatchMode={onFilterChange(setMatchMode)}
                onFilterTime={onFilterChange(setFilterTime)}
                onFilterSize={onFilterChange(setFilterSize)}
              />
            ) : null}

            <p className="app-hint">{hint}</p>
            {isKeywordSearch &&
            activeSource === 'bitmagnet' &&
            magnetError &&
            magnetTotal === 0 ? (
              <p className="app-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
                Bitmagnet：{magnetError}
              </p>
            ) : null}

            {activeLoading ? (
              <SearchResultsLoading keyword={isKeywordSearch ? keyword : undefined} />
            ) : activeSource === 'sehua' && error && items.length === 0 ? (
              <div className="app-error">
                <p>{error}</p>
                <p className="app-error-hint">请到「设置」检查资源库配置</p>
                <div className="app-actions" style={{ justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="app-btn-secondary"
                    onClick={() => {
                      setSehualPage(1);
                      setReloadToken((n) => n + 1);
                    }}
                  >
                    重试
                  </button>
                </div>
              </div>
            ) : activeEmpty ? (
              <div className="app-empty">
                <p>{isKeywordSearch ? '没有匹配结果' : '暂无资源'}</p>
                {isKeywordSearch ? (
                  <p className="app-footnote" style={{ marginTop: 8 }}>
                    试试更短的关键词，或放宽筛选
                  </p>
                ) : null}
              </div>
            ) : (
              <>
                <div className="bm-result-list">
                  {activeSource === 'sehua'
                    ? items.map((item) => (
                        <ResourceCard
                          key={item.hash}
                          item={item}
                          keywords={resultKeywords}
                          cropRegion={searchRegion || undefined}
                          onOpen={openSehualDetail}
                        />
                      ))
                    : magnetItems.map((item) => (
                        <MagnetCard
                          key={item.hash || item.infoHash || item.path}
                          item={item}
                          keywords={resultKeywords}
                          onOpen={openMagnetDetail}
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
                  {!activeHasMore && activeItems.length > 0 ? (
                    <p className="home-infinite__end">已全部加载</p>
                  ) : null}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {detailHash ? (
        <AppPush title="详情" onBack={closeDetail}>
          {detailSource === 'bitmagnet' ? (
            <BitmagnetDetailBody hash={detailHash} />
          ) : (
            <ResourceDetailBody hash={detailHash} />
          )}
        </AppPush>
      ) : null}

      {pasteOpen ? <P115PastePanel onBack={() => setPasteOpen(false)} /> : null}
    </div>
  );
}
