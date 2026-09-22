'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DEFAULT_MATCH_MODE,
  DEFAULT_SORT_TYPE,
  SEARCH_KEYWORD_LENGTH_MIN,
  BROWSE_LATEST_MAX,
  BROWSE_LATEST_PAGE_SIZE,
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
import { useTabNavigation } from '@/shell';
import { useStackCover } from '@/hooks/useStackCover';
import { clearSaveSource } from '@/lib/p115Source';
import {
  usePullToRefresh,
  finishPullToRefresh,
} from '@/hooks/usePullToRefresh';
import type { SearchSource } from './SourceSwitch';
import { syncDetailUrl, syncSearchUrl, type HomeMode } from './urlSync';

export type HomeScreenState = ReturnType<typeof useHomeScreen>;

export function useHomeScreen() {
  const tabCtx = useTabNavigation();
  const [mode, setMode] = useState<HomeMode>('landing');
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
  const [chatOpen, setChatOpen] = useState(false);
  const [boardsOpen, setBoardsOpen] = useState(false);
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const [detailSource, setDetailSource] = useState<FeedSource>('sehua');
  const [reloadToken, setReloadToken] = useState(0);
  const [searchRegion, setSearchRegion] = useState<string | null>(null);
  const [searchSource, setSearchSource] = useState<SearchSource>('sehua');
  const [costMs, setCostMs] = useState(0);
  const [magnetCostMs, setMagnetCostMs] = useState(0);
  const sehuaReqId = useRef(0);
  const magnetReqId = useRef(0);
  /** 已完成的查询指纹：同条件切回来源时跳过重复请求 */
  const sehuaDoneKeyRef = useRef('');
  const magnetDoneKeyRef = useRef('');
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const overlayOpen = Boolean(detailHash || pasteOpen || chatOpen || boardsOpen);
  const mainCover = useStackCover(
    overlayOpen,
    'home-main',
    'home-stack-main',
  );
  const scrollBodyRef = useRef<HTMLDivElement | null>(null);
  const hydrated = useRef(false);
  const skipUrlWrite = useRef(false);

  // iOS 下拉刷新：仅列表态（results）启用，刷新时重置分页重拉
  usePullToRefresh({
    scrollRef: scrollBodyRef,
    disabled: mode !== 'results' || Boolean(detailHash),
    onRefresh: () => {
      setSehualPage(1);
      setMagnetPage(1);
      setReloadToken((n) => n + 1);
    },
  });

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
    sehuaDoneKeyRef.current = '';
    magnetDoneKeyRef.current = '';
  }

  const onSearchSourceChange = useCallback((next: SearchSource) => {
    setSearchSource(next);
    if (next === 'sehua') setSehualPage(1);
    else setMagnetPage(1);
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
    try {
      clearSaveSource();
    } catch {
      /* ignore */
    }
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
        const srcRaw = sessionStorage.getItem('nextweb:home-search-source');
        sessionStorage.removeItem('nextweb:home-search');
        sessionStorage.removeItem('nextweb:home-mode');
        sessionStorage.removeItem('nextweb:home-prefix-region');
        sessionStorage.removeItem('nextweb:home-search-source');
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
        if (srcRaw === 'bitmagnet' || srcRaw === 'sehua') {
          setSearchSource(srcRaw);
        }
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
    try {
      clearSaveSource();
    } catch {
      /* ignore */
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
    try {
      clearSaveSource();
    } catch {
      /* ignore */
    }
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

  // 色花堂：浏览始终拉；关键词仅当前来源为色花堂时搜
  useEffect(() => {
    if (mode !== 'results') return;
    if (!browsing && keyword.length < SEARCH_KEYWORD_LENGTH_MIN) return;
    if (isKeywordSearch && searchSource !== 'sehua') {
      setSehualLoading(false);
      setSehualLoadingMore(false);
      return;
    }
    const queryKey = isKeywordSearch
      ? `kw|${keyword}|${sehuaPage}|${sortType}|${matchMode}|${filterTime}|${filterSize}|${searchRegion || ''}|${reloadToken}`
      : `browse|${sehuaPage}|${reloadToken}`;
    if (sehuaPage === 1 && sehuaDoneKeyRef.current === queryKey) {
      setSehualLoading(false);
      setSehualLoadingMore(false);
      return;
    }
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
            sehuaDoneKeyRef.current = queryKey;
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
            pageSize: BROWSE_LATEST_PAGE_SIZE,
            signal: ac.signal,
          });
          if (id !== sehuaReqId.current) return;
          const baseCount = append ? items.length : 0;
          setItems((prev) => {
            if (!append) return data.resources.slice(0, BROWSE_LATEST_MAX);
            const seen = new Set(prev.map((x) => x.hash));
            return [
              ...prev,
              ...data.resources.filter((x) => !seen.has(x.hash)),
            ].slice(0, BROWSE_LATEST_MAX);
          });
          setKeywords([]);
          const added = append
            ? data.resources.filter(
                (x) => !items.some((p) => p.hash === x.hash),
              ).length
            : Math.min(data.resources.length, BROWSE_LATEST_MAX);
          const loaded = Math.min(BROWSE_LATEST_MAX, baseCount + added);
          const apiTotal = Number(data.total_count) || loaded;
          setSehualTotal(Math.min(apiTotal, BROWSE_LATEST_MAX));
          setSehualHasMore(
            Boolean(data.has_more) && loaded < BROWSE_LATEST_MAX,
          );
          if (!append) {
            setCostMs(Math.round(performance.now() - t0));
            sehuaDoneKeyRef.current = queryKey;
          }
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
          // 失败不写 doneKey，切回同一源时可重试
        }
        setSehualHasMore(false);
        const m = e instanceof Error ? e.message : '加载失败';
        const softTimeout =
          /statement timeout|canceling statement|搜索超时|色花堂搜索超时/i.test(
            m,
          );
        setError(m);
        setMsg(
          softTimeout
            ? '色花堂搜索超时，可换关键词或稍后再试'
            : m === 'Not Found'
              ? '搜索接口未就绪，请重启 API 后再试'
              : m,
        );
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
    searchSource,
  ]);

  // Bitmagnet：仅当前来源为 Bt 时搜索
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
    const queryKey = `kw|${keyword}|${magnetPage}|${sortType}|${filterTime}|${filterSize}|${reloadToken}`;
    if (magnetPage === 1 && magnetDoneKeyRef.current === queryKey) {
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
          magnetDoneKeyRef.current = queryKey;
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
          // 失败不写 doneKey，切回同一源时可重试
        }
        setMagnetHasMore(false);
        setMagnetError(e instanceof Error && e.message ? e.message : 'Bitmagnet 搜索失败');
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

  // 下拉刷新完成后收起指示器（首屏加载态结束即代表新数据已拉取）
  useEffect(() => {
    if (mode !== 'results') return;
    const loading =
      activeSource === 'sehua' ? sehuaLoading : magnetLoading;
    if (!loading) {
      finishPullToRefresh(scrollBodyRef);
    }
  }, [activeSource, sehuaLoading, magnetLoading, mode]);

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
    ? (() => {
        if (searchSource === 'bitmagnet') {
          if (magnetLoading && magnetTotal === 0 && magnetItems.length === 0) {
            return magnetError ? 'Bt 不可用' : 'Bt…';
          }
          return magnetError && magnetTotal === 0
            ? 'Bt 不可用'
            : `Bt ${magnetTotal}`;
        }
        if (sehuaLoading && sehuaTotal === 0 && items.length === 0) {
          return '色花堂…';
        }
        const base = `色花堂 ${sehuaTotal}`;
        return searchRegion ? `${base} · 分区` : base;
      })()
    : sehuaTotal > 0
      ? `最新 · ${Math.min(sehuaTotal, BROWSE_LATEST_MAX)} 条`
      : '最新资源';

  function onFilterChange<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setSehualPage(1);
      setMagnetPage(1);
      resetLists();
    };
  }

  return {
    mode,
    draft,
    setDraft,
    keyword,
    browsing,
    sortType,
    setSortType,
    matchMode,
    setMatchMode,
    filterTime,
    setFilterTime,
    filterSize,
    setFilterSize,
    items,
    magnetItems,
    msg,
    setMsg,
    pasteOpen,
    setPasteOpen,
    chatOpen,
    setChatOpen,
    boardsOpen,
    setBoardsOpen,
    detailHash,
    detailSource,
    searchRegion,
    searchSource,
    costMs,
    magnetCostMs,
    sentinelRef,
    mainCover,
    scrollBodyRef,
    openSehualDetail,
    openMagnetDetail,
    closeDetail,
    onSearchSourceChange,
    goLanding,
    submitSearch,
    browseLatest,
    isKeywordSearch,
    activeSource,
    resultKeywords,
    activeItems,
    activeLoading,
    activeLoadingMore,
    activeHasMore,
    activeEmpty,
    hint,
    onFilterChange,
    error,
    magnetError,
    magnetTotal,
    sehuaLoading,
    setSehualPage,
    setReloadToken,
  };
}
