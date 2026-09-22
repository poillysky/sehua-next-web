'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  getScrapActressProfile,
  listScrapLibraryEmbedPrefixes,
  type MakerCatalogSourceId,
  type ScrapActressProfile,
  type ScrapLibraryEmbedFacet,
  type ScrapLibraryEmbedItem,
  type ScrapLibraryEmbedPrefix,
  type ScrapLibraryEmbedRecommend,
} from '@/lib/api';
import { useTabNavigation } from '@/shell';
import { useStackCover } from '@/hooks/useStackCover';
import {
  isFc2DirectStudio,
  isFc2FoldersDirectItems,
  MAKER_ACTRESS_SORT_OPTS,
  MAKER_FACET_SORT_OPTS,
  MAKER_PREFIX_SORT_OPTS,
  MAKER_SORT_OPTS,
  type MakerFacetSortId,
  type MakerLibraryView,
  type MakerPrefixSortId,
  type MakerSortId,
} from './makersUi';
import { listScrapFavorites } from './scrapFavorites';
import { sortPrefixes } from './prefixSort';
import {
  MAKERS_PAGE_SIZE,
  type Stack,
} from './makersTypes';
import {
  putLruCache,
  scrollMakersDrillTop,
  scrollMakersHubTop,
  useMakersLoaders,
  type DrillCacheEntry,
  type HubCacheEntry,
} from './makersLoaders';
import {
  clearMakerSearchResults,
  openMakerFacetFromDetail,
  openMakerItem,
  openMakerSearch,
  openMakerStudioFromDetail,
  runMakerSemanticSearch,
} from './makersNav';

export type MakersScreenState = ReturnType<typeof useMakersScreen>;

export function useMakersScreen() {
  const tabCtx = useTabNavigation();
  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [hubTab, setHubTab] =
    useState<MakerCatalogSourceId>('japan_censored');
  const [libraryView, setLibraryView] = useState<MakerLibraryView>('recommended');
  const [itemSort, setItemSort] = useState<MakerSortId>('year');
  const [facetSort, setFacetSort] = useState<MakerFacetSortId>('count');
  /** 女优墙默认：年龄升序（小→大） */
  const [actressSort, setActressSort] = useState<MakerFacetSortId>('age');
  /** 厂牌→前缀：默认按发行先后（新→旧） */
  const [prefixSort, setPrefixSort] = useState<MakerPrefixSortId>('code');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [sortMenuOpen, setSortMenuOpen] = useState(false);
  const sortSlotRef = useRef<HTMLDivElement | null>(null);
  const [msg, setMsg] = useState('');
  const [items, setItems] = useState<ScrapLibraryEmbedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [, setPrefixes] = useState<ScrapLibraryEmbedPrefix[]>([]);
  const [facets, setFacets] = useState<ScrapLibraryEmbedFacet[]>([]);
  const [drillPrefixes, setDrillPrefixes] = useState<ScrapLibraryEmbedPrefix[]>(
    [],
  );
  const [, setDrillFacets] = useState<ScrapLibraryEmbedFacet[]>([]);
  const [drillTotal, setDrillTotal] = useState(0);
  const [drillLoading, setDrillLoading] = useState(false);
  const drillCacheRef = useRef(new Map<string, DrillCacheEntry>());
  /** 一级浏览方式内存缓存：切换 Tab 秒开 */
  const hubCacheRef = useRef(new Map<string, HubCacheEntry>());
  const putHubCache = useCallback(
    (key: string, payload: HubCacheEntry) => {
      putLruCache(hubCacheRef.current, key, payload, 64);
    },
    [],
  );
  const putDrillCache = useCallback(
    (key: string, payload: DrillCacheEntry) => {
      putLruCache(drillCacheRef.current, key, payload, 48);
    },
    [],
  );
  const loadedDrillKeyRef = useRef('');
  const [recommend, setRecommend] = useState<ScrapLibraryEmbedRecommend | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [snapRefreshing, setSnapRefreshing] = useState(false);
  const [actressProfile, setActressProfile] =
    useState<ScrapActressProfile | null>(null);
  const [actressProfileLoading, setActressProfileLoading] = useState(false);
  const [searchDraft, setSearchDraft] = useState('');
  const [searchHits, setSearchHits] = useState<ScrapLibraryEmbedItem[]>([]);
  const [searchStudios, setSearchStudios] = useState<ScrapLibraryEmbedFacet[]>(
    [],
  );
  const [searchPrefixes, setSearchPrefixes] = useState<
    ScrapLibraryEmbedPrefix[]
  >([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [favTick, setFavTick] = useState(0);
  const [hubPage, setHubPage] = useState(1);
  const [drillPage, setDrillPage] = useState(1);
  const loadSeq = useRef(0);

  const hubCover = useStackCover(
    stack.kind !== 'hub',
    `makers-hub-${hubTab}-${libraryView}`,
    'app-hub makers-hub media-hub-root',
  );

  const favoriteItems = useMemo(() => {
    return listScrapFavorites(hubTab);
  }, [hubTab, favTick]);

  const favoritePageItems = useMemo(() => {
    const start = (hubPage - 1) * MAKERS_PAGE_SIZE;
    return favoriteItems.slice(start, start + MAKERS_PAGE_SIZE);
  }, [favoriteItems, hubPage]);

  const hubTotalPages = Math.max(1, Math.ceil(total / MAKERS_PAGE_SIZE));
  const drillTotalPages = Math.max(1, Math.ceil(total / MAKERS_PAGE_SIZE));
  const favTotalPages = Math.max(
    1,
    Math.ceil(favoriteItems.length / MAKERS_PAGE_SIZE),
  );

  const folderStudio =
    stack.kind === 'folderStudio' || stack.kind === 'folderPrefix'
      ? stack.studio
      : stack.kind === 'detail' &&
          (stack.from.kind === 'folderStudio' ||
            stack.from.kind === 'folderPrefix')
        ? stack.from.studio
        : undefined;
  const folderPrefix =
    stack.kind === 'folderPrefix'
      ? stack.prefix
      : stack.kind === 'detail' && stack.from.kind === 'folderPrefix'
        ? stack.from.prefix
        : undefined;
  const facetKind =
    stack.kind === 'facet'
      ? stack.facet
      : stack.kind === 'detail' && stack.from.kind === 'facet'
        ? stack.from.facet
        : undefined;
  const facetValue =
    stack.kind === 'facet'
      ? stack.value
      : stack.kind === 'detail' && stack.from.kind === 'facet'
        ? stack.from.value
        : undefined;

  const showSortBar =
    libraryView !== 'recommended' && libraryView !== 'favorites';
  const isActressHubView = libraryView === 'tags';
  const activeFacetSort: MakerFacetSortId = isActressHubView
    ? actressSort
    : facetSort === 'age'
      ? 'count'
      : facetSort;
  const isItemSortView =
    libraryView === 'movies' ||
    (libraryView === 'folders' && isFc2FoldersDirectItems(hubTab)) ||
    stack.kind === 'folderPrefix' ||
    stack.kind === 'facet' ||
    (stack.kind === 'folderStudio' && isFc2DirectStudio(stack.studio)) ||
    (stack.kind === 'detail' &&
      (stack.from.kind === 'folderPrefix' ||
        stack.from.kind === 'facet' ||
        (stack.from.kind === 'folderStudio' &&
          isFc2DirectStudio(stack.from.studio))));
  const isPrefixSortView =
    (stack.kind === 'folderStudio' && !isFc2DirectStudio(stack.studio)) ||
    (stack.kind === 'detail' &&
      stack.from.kind === 'folderStudio' &&
      !isFc2DirectStudio(stack.from.studio));

  const { loadItems, loadRecommend, loadHubView, refreshFacetsSnapshot } =
    useMakersLoaders({
      hubTab,
      libraryView,
      itemSort,
      activeFacetSort,
      sortOrder,
      folderStudio,
      folderPrefix,
      facetKind,
      facetValue,
      hubPage,
      snapRefreshing,
      loadSeq,
      hubCacheRef,
      drillCacheRef,
      loadedDrillKeyRef,
      putHubCache,
      setLoading,
      setMsg,
      setItems,
      setTotal,
      setPrefixes,
      setFacets,
      setRecommend,
      setFavTick,
      setSnapRefreshing,
    });

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/makers') return;
    if (tabCtx.tabReselect > 0) {
      setStack({ kind: 'hub' });
      setLibraryView('recommended');
      setHubPage(1);
    }
  }, [tabCtx?.tabReselect, tabCtx?.activeTab]);

  // 筛选变化时回到第 1 页
  useEffect(() => {
    setHubPage(1);
  }, [hubTab, libraryView, itemSort, actressSort, facetSort, sortOrder]);

  // 女优钻取：加载基本信息（头像 / 别名 / 作品数）
  useEffect(() => {
    if (stack.kind !== 'facet' || stack.facet !== 'actress') {
      setActressProfile(null);
      setActressProfileLoading(false);
      return;
    }
    const name = String(stack.value || '').trim();
    if (!name) return;
    let cancelled = false;
    setActressProfileLoading(true);
    const seedPoster =
      stack.posterApi &&
      (stack.posterApi.includes('/_actress/') ||
        stack.posterApi.includes('%2F_actress%2F') ||
        stack.posterApi.includes('%2f_actress%2f'))
        ? stack.posterApi
        : undefined;
    setActressProfile({
      name,
      count: stack.count,
      posterApi: seedPoster,
      aliases: [],
    });
    void (async () => {
      try {
        const data = await getScrapActressProfile({
          name,
          region: hubTab,
        });
        if (cancelled) return;
        const apiPoster =
          data.posterApi &&
          (data.posterApi.includes('/_actress/') ||
            data.posterApi.includes('%2F_actress%2F') ||
            data.posterApi.includes('%2f_actress%2f'))
            ? data.posterApi
            : undefined;
        setActressProfile({
          ...data,
          posterApi: apiPoster || seedPoster,
          count:
            typeof data.count === 'number'
              ? data.count
              : stack.count,
        });
      } catch {
        if (!cancelled) {
          setActressProfile((prev) =>
            prev
              ? prev
              : {
                  name,
                  count: stack.count,
                  posterApi: seedPoster,
                },
          );
        }
      } finally {
        if (!cancelled) setActressProfileLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    stack.kind === 'facet' ? stack.facet : '',
    stack.kind === 'facet' ? stack.value : '',
    stack.kind === 'facet' ? stack.posterApi : '',
    stack.kind === 'facet' ? stack.count : undefined,
    hubTab,
  ]);

  // Hub 数据：不要依赖 stack.kind，否则详情返回会整页重载（闪烁 + 丢滚动）
  // 推荐页与分区顶栏无关，切换区时不要重拉
  const hubQueryKey = `${hubTab}|${libraryView}|${itemSort}|${activeFacetSort}|${sortOrder}`;
  const hubQueryKeyRef = useRef(hubQueryKey);
  useEffect(() => {
    if (libraryView === 'recommended') return;
    // 筛选刚变且页码尚未回到 1 时跳过，避免打旧 offset
    if (hubQueryKeyRef.current !== hubQueryKey) {
      hubQueryKeyRef.current = hubQueryKey;
      if (hubPage !== 1) return;
    }
    void loadHubView(hubPage);
  }, [hubQueryKey, hubPage, libraryView, loadHubView]);

  useEffect(() => {
    if (libraryView !== 'recommended') return;
    void loadRecommend();
  }, [libraryView, loadRecommend]);

  const goHubPage = useCallback(
    (next: number) => {
      setHubPage(next);
      scrollMakersHubTop();
    },
    [],
  );

  const goDrillPage = useCallback(
    (next: number) => {
      setDrillPage(next);
      scrollMakersDrillTop();
    },
    [],
  );
  // 文件夹中间层：厂牌下的前缀列表（FC2 / FC2-PPV 跳过，直接番号）
  const folderMidKey = useMemo(() => {
    if (stack.kind === 'folderStudio') {
      if (isFc2DirectStudio(stack.studio)) return '';
      return `fs|${hubTab}|${stack.studio}|${prefixSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderStudio') {
      if (isFc2DirectStudio(stack.from.studio)) return '';
      return `fs|${hubTab}|${stack.from.studio}|${prefixSort}|${sortOrder}`;
    }
    return '';
  }, [stack, hubTab, prefixSort, sortOrder]);

  useEffect(() => {
    drillCacheRef.current.clear();
    // 换区清掉分区相关的一级缓存；推荐跨区保留
    for (const key of [...hubCacheRef.current.keys()]) {
      if (key !== 'recommend') hubCacheRef.current.delete(key);
    }
    loadedDrillKeyRef.current = '';
  }, [hubTab]);

  useEffect(() => {
    if (!folderMidKey) return;
    const cached = drillCacheRef.current.get(folderMidKey);
    if (cached) {
      setDrillPrefixes(cached.prefixes);
      setDrillFacets(cached.facets);
      setDrillTotal(cached.total);
      setDrillLoading(false);
      return;
    }
    let cancelled = false;
    // 无缓存：先清空再拉，避免先闪上一个厂牌的前缀
    setDrillPrefixes([]);
    setDrillFacets([]);
    setDrillTotal(0);
    setDrillLoading(true);
    setMsg('');
    void (async () => {
      try {
        const studio = folderStudio || '';
        const rows = await listScrapLibraryEmbedPrefixes(hubTab, { studio });
        if (cancelled) return;
        const prefixes = sortPrefixes(rows, prefixSort, sortOrder);
        const payload = {
          prefixes,
          facets: [] as ScrapLibraryEmbedFacet[],
          total: rows.length,
        };
        putDrillCache(folderMidKey, payload);
        setDrillPrefixes(payload.prefixes);
        setDrillFacets(payload.facets);
        setDrillTotal(payload.total);
      } catch (e) {
        if (cancelled) return;
        setMsg(e instanceof Error ? e.message : '加载失败');
        setDrillPrefixes([]);
        setDrillFacets([]);
        setDrillTotal(0);
      } finally {
        if (!cancelled) setDrillLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    folderMidKey,
    hubTab,
    folderStudio,
    prefixSort,
    sortOrder,
    putDrillCache,
  ]);

  // 钻取列表：详情盖住时保持同一 drillKey，避免返回时重新拉数
  const drillLoadKey = useMemo(() => {
    if (stack.kind === 'folderStudio' && isFc2DirectStudio(stack.studio)) {
      return `${hubTab}|fs-items|${stack.studio}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'folderPrefix') {
      return `${hubTab}|fp|${stack.studio}|${stack.prefix}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'facet') {
      return `${hubTab}|facet|${stack.facet}|${stack.value}|${itemSort}|${sortOrder}`;
    }
    if (
      stack.kind === 'detail' &&
      stack.from.kind === 'folderStudio' &&
      isFc2DirectStudio(stack.from.studio)
    ) {
      return `${hubTab}|fs-items|${stack.from.studio}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderPrefix') {
      return `${hubTab}|fp|${stack.from.studio}|${stack.from.prefix}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'facet') {
      return `${hubTab}|facet|${stack.from.facet}|${stack.from.value}|${itemSort}|${sortOrder}`;
    }
    return '';
  }, [stack, hubTab, itemSort, sortOrder]);

  useEffect(() => {
    if (!drillLoadKey) return;
    setDrillPage(1);
    loadedDrillKeyRef.current = '';
    // 立刻清空旧列表，避免先闪「原页面」海报再换成真实结果
    setItems([]);
    setTotal(0);
    setLoading(true);
  }, [drillLoadKey]);

  useEffect(() => {
    if (!drillLoadKey) return;
    // 筛选刚变时先落到第 1 页，避免用旧页码打接口
    if (loadedDrillKeyRef.current === '' && drillPage !== 1) return;
    const key = `${drillLoadKey}|p${drillPage}`;
    if (loadedDrillKeyRef.current === key) return;
    const offset = (drillPage - 1) * MAKERS_PAGE_SIZE;
    void (async () => {
      await loadItems(offset);
      loadedDrillKeyRef.current = key;
    })();
    // 仅随 drillLoadKey / drillPage 变化拉取；loadItems 引用变化不触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drillLoadKey, drillPage]);

  const sortLabel = isItemSortView
    ? MAKER_SORT_OPTS.find((o) => o.id === itemSort)?.label || '名称'
    : isPrefixSortView
      ? MAKER_PREFIX_SORT_OPTS.find((o) => o.id === prefixSort)?.label || '先后'
      : (isActressHubView
          ? MAKER_ACTRESS_SORT_OPTS
          : MAKER_FACET_SORT_OPTS
        ).find((o) => o.id === activeFacetSort)?.label || '名称';

  useEffect(() => {
    if (!sortMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const el = sortSlotRef.current;
      if (!el) return;
      if (e.target instanceof Node && !el.contains(e.target)) {
        setSortMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSortMenuOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      window.removeEventListener('keydown', onKey);
    };
  }, [sortMenuOpen]);

  function pickSort(id: string) {
    if (isItemSortView) {
      const next = id as MakerSortId;
      if (itemSort === next) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setItemSort(next);
      setSortOrder(next === 'recent' || next === 'year' ? 'desc' : 'asc');
    } else if (isPrefixSortView) {
      const next = id as MakerPrefixSortId;
      if (prefixSort === next) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setPrefixSort(next);
      setSortOrder(next === 'name' ? 'asc' : 'desc');
    } else if (isActressHubView) {
      const next = id as MakerFacetSortId;
      if (actressSort === next) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setActressSort(next);
      // 年龄默认小→大；数量大→小；名称 A→Z
      setSortOrder(next === 'count' ? 'desc' : 'asc');
    } else {
      const next = id as MakerFacetSortId;
      if (facetSort === next) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setFacetSort(next === 'age' ? 'count' : next);
      setSortOrder(next === 'count' ? 'desc' : 'asc');
    }
    setSortMenuOpen(false);
  }

  const sortOpts = isItemSortView
    ? MAKER_SORT_OPTS
    : isPrefixSortView
      ? MAKER_PREFIX_SORT_OPTS
      : isActressHubView
        ? MAKER_ACTRESS_SORT_OPTS
        : MAKER_FACET_SORT_OPTS;
  const activeSortId = isItemSortView
    ? itemSort
    : isPrefixSortView
      ? prefixSort
      : activeFacetSort;

  async function runSemanticSearch(raw: string) {
    await runMakerSemanticSearch(raw, {
      hubTab,
      setSearchLoading,
      setSearchDone,
      setMsg,
      setSearchHits,
      setSearchPrefixes,
      setSearchStudios,
    });
  }

  function openItem(item: ScrapLibraryEmbedItem) {
    openMakerItem(item, { hubTab, stack, setHubTab, setStack });
  }

  function openFacetFromDetail(
    facet: 'genre' | 'tag' | 'actress',
    value: string,
    opts?: { posterApi?: string; count?: number },
  ) {
    openMakerFacetFromDetail(facet, value, {
      stack,
      setStack,
      posterApi: opts?.posterApi,
      count: opts?.count,
    });
  }

  function openStudioFromDetail(value: string) {
    openMakerStudioFromDetail(value, setStack);
  }

  function clearSearchResults() {
    clearMakerSearchResults({
      setSearchHits,
      setSearchStudios,
      setSearchPrefixes,
      setSearchDone,
    });
  }

  function openSearch() {
    openMakerSearch({
      setSearchDraft,
      setSearchHits,
      setSearchStudios,
      setSearchPrefixes,
      setSearchDone,
      setStack,
    });
  }

  return {
    stack,
    setStack,
    hubTab,
    setHubTab,
    libraryView,
    setLibraryView,
    actressSort,
    sortOrder,
    setSortOrder,
    sortMenuOpen,
    setSortMenuOpen,
    sortSlotRef,
    msg,
    setMsg,
    items,
    setItems,
    total,
    facets,
    drillPrefixes,
    drillTotal,
    drillLoading,
    recommend,
    loading,
    snapRefreshing,
    actressProfile,
    actressProfileLoading,
    searchDraft,
    setSearchDraft,
    searchHits,
    searchStudios,
    searchPrefixes,
    searchLoading,
    searchDone,
    setFavTick,
    hubPage,
    drillPage,
    hubCover,
    favoriteItems,
    favoritePageItems,
    hubTotalPages,
    drillTotalPages,
    favTotalPages,
    showSortBar,
    sortLabel,
    sortOpts,
    activeSortId,
    pickSort,
    goHubPage,
    goDrillPage,
    refreshFacetsSnapshot,
    runSemanticSearch,
    openItem,
    openFacetFromDetail,
    openStudioFromDetail,
    clearSearchResults,
    openSearch,
    pageSize: MAKERS_PAGE_SIZE,
  };
}
