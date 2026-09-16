'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ArrowDown, ArrowUp, Check, ChevronRight, RefreshCw, Search, X } from 'lucide-react';
import {
  getScrapActressProfile,
  listScrapLibraryEmbedFacets,
  listScrapLibraryEmbedItems,
  listScrapLibraryEmbedPrefixes,
  listScrapLibraryEmbedRecommend,
  refreshScrapLibraryEmbedFacetsSnapshot,
  searchScrapLibraryEmbed,
  type MakerCatalogSourceId,
  type ScrapActressProfile,
  type ScrapLibraryEmbedFacet,
  type ScrapLibraryEmbedItem,
  type ScrapLibraryEmbedPrefix,
  type ScrapLibraryEmbedRecommend,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { useTabNavigation } from '@/shell';
import { useStackCover } from '@/hooks/useStackCover';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import {
  makerSourceLabel,
  MAKER_ACTRESS_SORT_OPTS,
  MAKER_FACET_SORT_OPTS,
  MAKER_KIND_TABS,
  MAKER_LIBRARY_VIEWS,
  MAKER_PREFIX_SORT_OPTS,
  MAKER_SORT_OPTS,
  type MakerFacetSortId,
  type MakerLibraryView,
  type MakerPrefixSortId,
  type MakerSortId,
} from './makersUi';
import { ScrapPosterCard } from './ScrapPosterCard';
import { ScrapActressCard, ScrapCollageCard, ScrapTagCard } from './ScrapCollageCard';
import { ScrapActressProfileHeader } from './ScrapActressProfileHeader';
import { ScrapDetailBody } from './ScrapDetailBody';
import {
  listScrapFavorites,
  ensureScrapFavoritesLoaded,
} from './scrapFavorites';

type DrillStack =
  | { kind: 'hub' }
  | { kind: 'search' }
  /** 文件夹：厂牌 → 前缀 → 番号 */
  | { kind: 'folderStudio'; studio: string }
  | { kind: 'folderPrefix'; studio: string; prefix: string }
  | {
      kind: 'facet';
      facet: 'genre' | 'tag' | 'actress';
      value: string;
      /** 从详情芯片跳转时，返回可回到该条目 */
      fromDetail?: ScrapLibraryEmbedItem;
      /** 女优入口预填（减少头闪烁） */
      posterApi?: string;
      count?: number;
    };

type Stack =
  | DrillStack
  | { kind: 'detail'; item: ScrapLibraryEmbedItem; from: DrillStack };

// 女优墙 4 列、文件夹/合集 3 列：用 48 避免满页末行空格
const PAGE_SIZE = 48;

function prefixCodeRank(code: string): number {
  const m = String(code || '')
    .trim()
    .toUpperCase()
    .match(/(\d+)\s*$/);
  return m ? Number.parseInt(m[1], 10) : 0;
}

function sortPrefixes(
  rows: ScrapLibraryEmbedPrefix[],
  sortId: MakerPrefixSortId,
  order: 'asc' | 'desc',
): ScrapLibraryEmbedPrefix[] {
  const mul = order === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sortId === 'count') {
      return (
        (a.count - b.count) * mul || a.prefix.localeCompare(b.prefix, 'zh')
      );
    }
    if (sortId === 'code') {
      // 先后：主力线永远优先，再比发行年 / 入库时间
      const la = Number(a.lineRank ?? 99);
      const lb = Number(b.lineRank ?? 99);
      if (la !== lb) return la - lb;
      const ya = Number(a.latestYear || 0);
      const yb = Number(b.latestYear || 0);
      if (ya !== yb) return (ya - yb) * mul;
      const ta = Date.parse(String(a.latestAt || '')) || 0;
      const tb = Date.parse(String(b.latestAt || '')) || 0;
      if (ta !== tb) return (ta - tb) * mul;
      const ra = prefixCodeRank(a.latestCode || '');
      const rb = prefixCodeRank(b.latestCode || '');
      if (ra !== rb) return (ra - rb) * mul;
      return a.prefix.localeCompare(b.prefix, 'zh');
    }
    return a.prefix.localeCompare(b.prefix, 'zh') * mul;
  });
}

export function MakersScreen() {
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
  const [prefixes, setPrefixes] = useState<ScrapLibraryEmbedPrefix[]>([]);
  const [facets, setFacets] = useState<ScrapLibraryEmbedFacet[]>([]);
  const [drillPrefixes, setDrillPrefixes] = useState<ScrapLibraryEmbedPrefix[]>(
    [],
  );
  const [drillFacets, setDrillFacets] = useState<ScrapLibraryEmbedFacet[]>([]);
  const [drillTotal, setDrillTotal] = useState(0);
  const [drillLoading, setDrillLoading] = useState(false);
  const drillCacheRef = useRef(
    new Map<
      string,
      {
        prefixes: ScrapLibraryEmbedPrefix[];
        facets: ScrapLibraryEmbedFacet[];
        total: number;
      }
    >(),
  );
  /** 一级浏览方式内存缓存：切换 Tab 秒开 */
  const hubCacheRef = useRef(
    new Map<
      string,
      {
        items: ScrapLibraryEmbedItem[];
        facets: ScrapLibraryEmbedFacet[];
        total: number;
        recommend: ScrapLibraryEmbedRecommend | null;
      }
    >(),
  );
  const putHubCache = useCallback(
    (
      key: string,
      payload: {
        items: ScrapLibraryEmbedItem[];
        facets: ScrapLibraryEmbedFacet[];
        total: number;
        recommend: ScrapLibraryEmbedRecommend | null;
      },
    ) => {
      const m = hubCacheRef.current;
      if (m.has(key)) m.delete(key);
      m.set(key, payload);
      while (m.size > 64) {
        const oldest = m.keys().next().value;
        if (oldest == null) break;
        m.delete(oldest);
      }
    },
    [],
  );
  const putDrillCache = useCallback(
    (
      key: string,
      payload: {
        prefixes: ScrapLibraryEmbedPrefix[];
        facets: ScrapLibraryEmbedFacet[];
        total: number;
      },
    ) => {
      const m = drillCacheRef.current;
      if (m.has(key)) m.delete(key);
      m.set(key, payload);
      while (m.size > 48) {
        const oldest = m.keys().next().value;
        if (oldest == null) break;
        m.delete(oldest);
      }
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
    const start = (hubPage - 1) * PAGE_SIZE;
    return favoriteItems.slice(start, start + PAGE_SIZE);
  }, [favoriteItems, hubPage]);

  const hubTotalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const drillTotalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const favTotalPages = Math.max(
    1,
    Math.ceil(favoriteItems.length / PAGE_SIZE),
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
    stack.kind === 'folderPrefix' ||
    stack.kind === 'facet' ||
    (stack.kind === 'detail' &&
      (stack.from.kind === 'folderPrefix' || stack.from.kind === 'facet'));
  const isPrefixSortView =
    stack.kind === 'folderStudio' ||
    (stack.kind === 'detail' && stack.from.kind === 'folderStudio');

  const loadItems = useCallback(
    async (offset: number) => {
      const seq = ++loadSeq.current;
      setLoading(true);
      setMsg('');
      // 筛选切换时先清空，避免旧列表闪一下，也不要用黑底空屏
      if (offset === 0) setItems([]);
      try {
        const page = await listScrapLibraryEmbedItems({
          region: hubTab,
          prefix: folderPrefix,
          studio: folderStudio,
          actress: facetKind === 'actress' ? facetValue : undefined,
          genre: facetKind === 'genre' ? facetValue : undefined,
          tag: facetKind === 'tag' ? facetValue : undefined,
          sort: itemSort,
          order: sortOrder,
          offset,
          limit: PAGE_SIZE,
        });
        if (seq !== loadSeq.current) return;
        setTotal(page.total);
        setItems(page.items || []);
      } catch (e) {
        if (seq !== loadSeq.current) return;
        setItems([]);
        setTotal(0);
        setMsg(e instanceof Error ? e.message : '刮削库加载失败');
      } finally {
        if (seq === loadSeq.current) setLoading(false);
      }
    },
    [
      hubTab,
      folderStudio,
      folderPrefix,
      facetKind,
      facetValue,
      itemSort,
      sortOrder,
    ],
  );

  const loadRecommend = useCallback(async () => {
    const cacheKey = 'recommend';
    const cached = hubCacheRef.current.get(cacheKey);
    if (cached?.recommend) {
      setRecommend(cached.recommend);
      setItems([]);
      setPrefixes([]);
      setFacets([]);
      setTotal(cached.total);
      setLoading(false);
      return;
    }
    const seq = ++loadSeq.current;
    setLoading(true);
    setMsg('');
    setItems([]);
    setPrefixes([]);
    setFacets([]);
    setTotal(0);
    try {
      const data = await listScrapLibraryEmbedRecommend();
      if (seq !== loadSeq.current) return;
      setRecommend(data);
      setTotal(data.total || 0);
      putHubCache(cacheKey, {
        items: [],
        facets: [],
        total: data.total || 0,
        recommend: data,
      });
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setRecommend(null);
      setMsg(e instanceof Error ? e.message : '加载失败');
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [putHubCache]);

  const scrollHubTop = useCallback(() => {
    const el =
      (document.querySelector('.makers-hub__scroll') as HTMLElement | null) ||
      (document.querySelector('.app-hub__scroll') as HTMLElement | null);
    el?.scrollTo({ top: 0 });
  }, []);

  const scrollDrillTop = useCallback(() => {
    const el = document.querySelector(
      '.app-push__body',
    ) as HTMLElement | null;
    el?.scrollTo({ top: 0 });
  }, []);

  const loadHubView = useCallback(
    async (pageNum: number) => {
      if (libraryView === 'recommended') return;
      const cacheKey = `${hubTab}|${libraryView}|${itemSort}|${activeFacetSort}|${sortOrder}|${pageNum}`;
      if (libraryView !== 'favorites') {
        const cached = hubCacheRef.current.get(cacheKey);
        if (cached) {
          setItems(cached.items);
          setFacets(cached.facets);
          setRecommend(null);
          setPrefixes([]);
          setTotal(cached.total);
          setLoading(false);
          return;
        }
      }
      const seq = ++loadSeq.current;
      setLoading(true);
      setMsg('');
      setItems([]);
      setRecommend(null);
      setPrefixes([]);
      setFacets([]);
      const offset = (pageNum - 1) * PAGE_SIZE;
      try {
        if (libraryView === 'movies') {
          const page = await listScrapLibraryEmbedItems({
            region: hubTab,
            sort: itemSort,
            order: sortOrder,
            offset,
            limit: PAGE_SIZE,
          });
          if (seq !== loadSeq.current) return;
          const nextItems = page.items || [];
          setItems(nextItems);
          setTotal(page.total);
          putHubCache(cacheKey, {
            items: nextItems,
            facets: [],
            total: page.total,
            recommend: null,
          });
        } else if (
          libraryView === 'folders' ||
          libraryView === 'genres' ||
          libraryView === 'tags'
        ) {
          const kind =
            libraryView === 'folders'
              ? 'studio'
              : libraryView === 'genres'
                ? 'genre'
                : 'actress';
          const page = await listScrapLibraryEmbedFacets({
            region: hubTab,
            kind,
            sort: activeFacetSort,
            order: sortOrder,
            offset,
            limit: PAGE_SIZE,
          });
          if (seq !== loadSeq.current) return;
          const nextFacets = page.facets || [];
          setFacets(nextFacets);
          setTotal(page.total);
          putHubCache(cacheKey, {
            items: [],
            facets: nextFacets,
            total: page.total,
            recommend: null,
          });
        } else if (libraryView === 'favorites') {
          await ensureScrapFavoritesLoaded();
          if (seq !== loadSeq.current) return;
          setFavTick((t) => t + 1);
          setTotal(listScrapFavorites(hubTab).length);
        }
      } catch (e) {
        if (seq !== loadSeq.current) return;
        setMsg(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (seq === loadSeq.current) setLoading(false);
      }
    },
    [hubTab, libraryView, itemSort, activeFacetSort, sortOrder, putHubCache],
  );

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
  // 推荐页与七区无关，切换区时不要重拉
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
      scrollHubTop();
    },
    [scrollHubTop],
  );

  const refreshFacetsSnapshot = useCallback(async () => {
    if (snapRefreshing) return;
    setSnapRefreshing(true);
    setMsg('');
    try {
      const data = await refreshScrapLibraryEmbedFacetsSnapshot({
        allRegions: true,
      });
      drillCacheRef.current.clear();
      hubCacheRef.current.clear();
      loadedDrillKeyRef.current = '';
      const counts = data.kinds || {};
      const nRegions = Array.isArray(data.regions) ? data.regions.length : 0;
      const parts = [
        nRegions > 1 ? `${nRegions} 区` : '',
        counts.recommend != null ? `推荐 ${counts.recommend}` : '',
        counts.moviesWarm != null ? `影片首页 ${counts.moviesWarm}` : '',
        counts.studio != null ? `厂牌 ${counts.studio}` : '',
        counts.genre != null ? `标签 ${counts.genre}` : '',
        counts.actress != null ? `女优 ${counts.actress}` : '',
      ].filter(Boolean);
      setMsg(
        parts.length
          ? `快照已更新（${parts.join(' · ')}）`
          : '快照已更新',
      );
      if (libraryView === 'recommended') {
        await loadRecommend();
      } else if (
        libraryView === 'folders' ||
        libraryView === 'genres' ||
        libraryView === 'tags' ||
        libraryView === 'movies'
      ) {
        await loadHubView(hubPage);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '刷新快照失败');
    } finally {
      setSnapRefreshing(false);
    }
  }, [snapRefreshing, libraryView, hubPage, loadHubView, loadRecommend]);

  const goDrillPage = useCallback(
    (next: number) => {
      setDrillPage(next);
      scrollDrillTop();
    },
    [scrollDrillTop],
  );
  // 文件夹中间层：厂牌下的前缀列表
  const folderMidKey = useMemo(() => {
    if (stack.kind === 'folderStudio') {
      return `fs|${hubTab}|${stack.studio}|${prefixSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderStudio') {
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
    if (stack.kind === 'folderPrefix') {
      return `${hubTab}|fp|${stack.studio}|${stack.prefix}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'facet') {
      return `${hubTab}|facet|${stack.facet}|${stack.value}|${itemSort}|${sortOrder}`;
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
    const offset = (drillPage - 1) * PAGE_SIZE;
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

  const OrderIcon = sortOrder === 'asc' ? ArrowUp : ArrowDown;

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

  const sortDropdown = sortMenuOpen ? (
    <div className="makers-sort-dropdown" role="listbox" aria-label="排序">
      {sortOpts.map((opt) => {
        const active = activeSortId === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            role="option"
            aria-selected={active}
            className={
              active
                ? 'makers-sort-dropdown__btn is-active'
                : 'makers-sort-dropdown__btn'
            }
            onClick={() => pickSort(opt.id)}
          >
            <span className="makers-sort-dropdown__check" aria-hidden>
              {active ? <Check size={15} strokeWidth={2.5} /> : null}
            </span>
            <span className="makers-sort-dropdown__label">{opt.label}</span>
            {active ? (
              <OrderIcon
                className="makers-sort-dropdown__dir"
                size={15}
                strokeWidth={2.4}
                aria-hidden
              />
            ) : (
              <span className="makers-sort-dropdown__dir" aria-hidden />
            )}
          </button>
        );
      })}
    </div>
  ) : null;

  const combinedSortBtn = (
    visible: boolean,
    className = 'makers-view-switch__sort',
  ) =>
    visible ? (
      <button
        type="button"
        className={className}
        aria-label={`排序：${sortLabel}${sortOrder === 'asc' ? '升序' : '降序'}`}
        aria-expanded={sortMenuOpen}
        aria-haspopup="listbox"
        onClick={() => setSortMenuOpen((o) => !o)}
      >
        <span>{sortLabel}</span>
        <OrderIcon size={14} strokeWidth={2.4} aria-hidden />
      </button>
    ) : null;

  async function runSemanticSearch(raw: string) {
    const q = raw.trim();
    if (q.length < SEARCH_KEYWORD_LENGTH_MIN) {
      setMsg(`请输入至少 ${SEARCH_KEYWORD_LENGTH_MIN} 个字`);
      return;
    }
    setSearchLoading(true);
    setSearchDone(false);
    setMsg('');
    try {
      const [page, prefixes, studioPage] = await Promise.all([
        listScrapLibraryEmbedItems({
          region: hubTab,
          q,
          offset: 0,
          limit: PAGE_SIZE,
        }),
        listScrapLibraryEmbedPrefixes(hubTab, { q, limit: 24 }).catch(
          () => [] as ScrapLibraryEmbedPrefix[],
        ),
        listScrapLibraryEmbedFacets({
          region: hubTab,
          kind: 'studio',
          q,
          sort: 'count',
          order: 'desc',
          limit: 24,
        }).catch(() => ({ facets: [] as ScrapLibraryEmbedFacet[], total: 0 })),
      ]);
      let hits = page.items || [];
      if (hits.length < 8) {
        try {
          const semantic = await searchScrapLibraryEmbed({
            query: q,
            limit: 24,
            region: hubTab,
          });
          const seen = new Set(
            hits.map((h) => String(h.itemId || h.code || '')),
          );
          for (const h of semantic) {
            const key = String(h.itemId || h.code || '');
            if (!key || seen.has(key)) continue;
            seen.add(key);
            hits.push(h);
          }
        } catch {
          /* 语义失败仍展示关键字结果 */
        }
      }
      setSearchHits(hits);
      setSearchPrefixes(prefixes || []);
      setSearchStudios(studioPage.facets || []);
      setSearchDone(true);
    } catch (e) {
      setSearchHits([]);
      setSearchPrefixes([]);
      setSearchStudios([]);
      setSearchDone(true);
      setMsg(e instanceof Error ? e.message : '搜索失败');
    } finally {
      setSearchLoading(false);
    }
  }

  function currentDrill(): DrillStack {
    if (stack.kind === 'detail') return stack.from;
    if (stack.kind === 'hub') return { kind: 'hub' };
    if (stack.kind === 'search') return { kind: 'search' };
    if (stack.kind === 'folderStudio') {
      return { kind: 'folderStudio', studio: stack.studio };
    }
    if (stack.kind === 'folderPrefix') {
      return {
        kind: 'folderPrefix',
        studio: stack.studio,
        prefix: stack.prefix,
      };
    }
    return {
      kind: 'facet',
      facet: stack.facet,
      value: stack.value,
      fromDetail: stack.fromDetail,
    };
  }

  function openItem(item: ScrapLibraryEmbedItem) {
    const rid = String(item.region || '').trim();
    if (
      rid &&
      MAKER_KIND_TABS.some((t) => t.id === rid) &&
      rid !== hubTab
    ) {
      setHubTab(rid as typeof hubTab);
    }
    setStack({ kind: 'detail', item, from: currentDrill() });
  }

  function openFacetFromDetail(
    facet: 'genre' | 'tag' | 'actress',
    value: string,
    opts?: { posterApi?: string; count?: number },
  ) {
    const name = String(value || '').trim();
    if (!name) return;
    const fromDetail = stack.kind === 'detail' ? stack.item : undefined;
    setStack({
      kind: 'facet',
      facet,
      value: name,
      fromDetail,
      posterApi: opts?.posterApi,
      count: opts?.count,
    });
  }

  function openStudioFromDetail(value: string) {
    const name = String(value || '').trim();
    if (!name) return;
    setStack({ kind: 'folderStudio', studio: name });
  }

  const wall = (
    wallItems: ScrapLibraryEmbedItem[],
    empty: string,
    opts?: { loading?: boolean },
  ) => (
    <>
      {opts?.loading ? (
        <div className="media-wall media-wall--skel makers-hub__wall" aria-hidden>
          {Array.from({ length: 9 }).map((_, i) => (
            <span key={i} className="makers-poster-skel" />
          ))}
        </div>
      ) : null}
      {!opts?.loading && wallItems.length === 0 ? (
        <p className="media-empty makers-hub__empty allow-select">{empty}</p>
      ) : null}
      {!opts?.loading && wallItems.length > 0 ? (
        <div className="media-wall makers-hub__wall">
          {wallItems.map((item, i) => (
            <ScrapPosterCard
              key={String(item.itemId || item.code)}
              item={item}
              eager={i < 18}
              onClick={() => openItem(item)}
            />
          ))}
        </div>
      ) : null}
    </>
  );

  const hubPager =
    !loading &&
    (libraryView === 'movies' ||
      libraryView === 'folders' ||
      libraryView === 'genres' ||
      libraryView === 'tags') &&
    total > PAGE_SIZE ? (
      <div className="media-chart__pager">
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={hubPage <= 1}
          onClick={() => goHubPage(Math.max(1, hubPage - 1))}
        >
          上一页
        </button>
        <span className="media-chart__page-meta">
          {hubPage} / {hubTotalPages}
        </span>
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={hubPage >= hubTotalPages}
          onClick={() => goHubPage(Math.min(hubTotalPages, hubPage + 1))}
        >
          下一页
        </button>
      </div>
    ) : null;

  const favPager =
    !loading &&
    libraryView === 'favorites' &&
    favoriteItems.length > PAGE_SIZE ? (
      <div className="media-chart__pager">
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={hubPage <= 1}
          onClick={() => goHubPage(Math.max(1, hubPage - 1))}
        >
          上一页
        </button>
        <span className="media-chart__page-meta">
          {Math.min(hubPage, favTotalPages)} / {favTotalPages}
        </span>
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={hubPage >= favTotalPages}
          onClick={() => goHubPage(Math.min(favTotalPages, hubPage + 1))}
        >
          下一页
        </button>
      </div>
    ) : null;

  const drillPager =
    !loading && total > PAGE_SIZE ? (
      <div className="media-chart__pager">
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={drillPage <= 1}
          onClick={() => goDrillPage(Math.max(1, drillPage - 1))}
        >
          上一页
        </button>
        <span className="media-chart__page-meta">
          {drillPage} / {drillTotalPages}
        </span>
        <button
          type="button"
          className="media-chart__page-btn"
          disabled={drillPage >= drillTotalPages}
          onClick={() => goDrillPage(Math.min(drillTotalPages, drillPage + 1))}
        >
          下一页
        </button>
      </div>
    ) : null;

  function shelfRail(
    railKey: string,
    title: string,
    children: ReactNode,
    onMore?: () => void,
  ) {
    return (
      <section key={railKey} className="media-shelf makers-shelf">
        <button
          type="button"
          className="media-shelf__head"
          onClick={onMore}
          disabled={!onMore}
        >
          <span className="media-shelf__title">{title}</span>
          {onMore ? (
            <span className="media-shelf__more">
              全部
              <ChevronRight size={15} strokeWidth={2.25} aria-hidden />
            </span>
          ) : (
            <span />
          )}
        </button>
        <div className="media-shelf__rail makers-shelf__rail">{children}</div>
      </section>
    );
  }

  function viewMetaLabel() {
    const base = makerSourceLabel(hubTab);
    if (loading) return `${base} · 加载中…`;
    switch (libraryView) {
      case 'recommended':
        return loading ? '推荐 · 加载中…' : '推荐 · 七区最新';
      case 'folders':
        return `${base} · ${total} 个厂牌`;
      case 'genres':
        return `${base} · ${total} 个标签`;
      case 'tags':
        return `${base} · ${total} 位女优`;
      case 'favorites':
        return `${base} · ${favoriteItems.length} 项收藏`;
      default:
        return `${base} · 共 ${total} 项`;
    }
  }

  const hubBody = () => {
    if (libraryView === 'favorites') {
      if (loading) {
        return (
          <div className="media-wall media-wall--skel makers-hub__wall" aria-hidden>
            {Array.from({ length: 9 }).map((_, i) => (
              <span key={i} className="makers-poster-skel" />
            ))}
          </div>
        );
      }
      if (favoriteItems.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">
            这里空空如也
            <br />
            <span className="makers-hub__empty-hint">
              在影片详情页点「收藏」即可加入
            </span>
          </p>
        );
      }
      return (
        <>
          {wall(favoritePageItems, '这里空空如也')}
          {favPager}
        </>
      );
    }
    if (libraryView === 'recommended') {
      if (loading) {
        return (
          <div className="makers-hub__shelves" aria-hidden>
            {MAKER_KIND_TABS.map((tab) => (
              <section key={tab.id} className="media-shelf makers-shelf">
                <div className="media-shelf__head">
                  <span className="media-shelf__title">
                    {tab.label} · 最近刮削
                  </span>
                  <span className="media-shelf__more" />
                </div>
                <div className="media-shelf__rail makers-shelf__rail media-shelf__rail--skel">
                  {Array.from({ length: 5 }).map((_, j) => (
                    <span key={j} className="makers-poster-skel" />
                  ))}
                </div>
              </section>
            ))}
          </div>
        );
      }
      const shelves =
        recommend?.shelves && recommend.shelves.length > 0
          ? [...recommend.shelves].sort((a, b) => {
              const ai = MAKER_KIND_TABS.findIndex((t) => t.id === a.region);
              const bi = MAKER_KIND_TABS.findIndex((t) => t.id === b.region);
              return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
            })
          : recommend?.latest?.length
            ? [
                {
                  region: hubTab,
                  label: makerSourceLabel(hubTab),
                  latest: recommend.latest,
                },
              ]
            : [];
      if (shelves.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">
            暂无推荐内容
          </p>
        );
      }
      return (
        <div className="makers-hub__shelves">
          {shelves.map((shelf) => {
            const title =
              MAKER_KIND_TABS.find((t) => t.id === shelf.region)?.label ||
              shelf.label ||
              shelf.region;
            const items = shelf.latest || [];
            if (items.length === 0) return null;
            return shelfRail(
              shelf.region || title,
              `${title} · 最近刮削`,
              items.map((item, i) => (
                <ScrapPosterCard
                  key={`${shelf.region}-${String(item.itemId || item.code)}`}
                  item={item}
                  eager={i < 6}
                  onClick={() => openItem(item)}
                />
              )),
              () => {
                if (MAKER_KIND_TABS.some((t) => t.id === shelf.region)) {
                  setHubTab(shelf.region as typeof hubTab);
                }
                setLibraryView('movies');
              },
            );
          })}
        </div>
      );
    }
    if (libraryView === 'folders') {
      if (loading) {
        return (
          <div className="makers-collage-grid makers-collage-grid--skel" aria-hidden>
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className="makers-collage-skel" />
            ))}
          </div>
        );
      }
      if (facets.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">
            暂无厂牌
          </p>
        );
      }
      return (
        <>
          <div className="makers-collage-grid">
            {facets.map((f) => (
              <ScrapCollageCard
                key={f.name}
                title={f.name}
                count={f.count}
                blurb={f.blurb}
                posterApi={f.posterApi}
                coverUrl={f.coverUrl}
                onClick={() =>
                  setStack({ kind: 'folderStudio', studio: f.name })
                }
              />
            ))}
          </div>
          {hubPager}
        </>
      );
    }
    if (libraryView === 'genres') {
      if (loading) {
        return (
          <div className="makers-tag-card-grid makers-tag-card-grid--skel" aria-hidden>
            {Array.from({ length: 15 }).map((_, i) => (
              <span key={i} className="makers-tag-card-skel" />
            ))}
          </div>
        );
      }
      if (facets.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">暂无标签</p>
        );
      }
      return (
        <>
          <div className="makers-tag-card-grid">
            {facets.map((f) => (
              <ScrapTagCard
                key={f.name}
                title={f.name}
                count={f.count}
                onClick={() =>
                  setStack({
                    kind: 'facet',
                    facet: 'genre',
                    value: f.name,
                  })
                }
              />
            ))}
          </div>
          {hubPager}
        </>
      );
    }
    if (libraryView === 'tags') {
      if (loading) {
        return (
          <div
            className="makers-actress-grid makers-actress-grid--skel"
            aria-hidden
          >
            {Array.from({ length: 8 }).map((_, i) => (
              <span key={i} className="makers-actress-skel" />
            ))}
          </div>
        );
      }
      if (facets.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">暂无女优</p>
        );
      }
      return (
        <>
          <div className="makers-actress-grid">
            {facets.map((f) => (
              <ScrapActressCard
                key={f.name}
                title={f.name}
                count={f.count}
                posterApi={f.posterApi}
                posterApis={f.posterApis}
                coverUrl={f.coverUrl}
                onClick={() =>
                  setStack({
                    kind: 'facet',
                    facet: 'actress',
                    value: f.name,
                    posterApi: f.posterApi,
                    count: f.count,
                  })
                }
              />
            ))}
          </div>
          {hubPager}
        </>
      );
    }
    return (
      <>
        {wall(
          items,
          `「${makerSourceLabel(hubTab)}」刮削库暂无条目，请先在设置同步向量`,
          { loading },
        )}
        {hubPager}
      </>
    );
  };

  const hub = (
    <div {...hubCover}>
      <div className="makers-hub__wash" aria-hidden />
      <div
        className={
          sortMenuOpen && showSortBar
            ? 'makers-hub__top media-hub__top is-sort-open'
            : 'makers-hub__top media-hub__top'
        }
      >
        <div className="media-hub__top-row">
          <p className="makers-hub__meta allow-select">{viewMetaLabel()}</p>
          <h1 className="app-hub__title">片商</h1>
          <div className="makers-hub__top-actions">
            <button
              type="button"
              className={
                snapRefreshing
                  ? 'media-hub__search-btn makers-hub__refresh-btn is-busy'
                  : 'media-hub__search-btn makers-hub__refresh-btn'
              }
              aria-label="刷新浏览快照"
              title="刷新七区厂牌/标签/女优 + 推荐 + 影片首页快照"
              disabled={snapRefreshing}
              onClick={() => {
                void refreshFacetsSnapshot();
              }}
            >
              <span
                className={
                  snapRefreshing
                    ? 'makers-hub__refresh-spin is-spinning'
                    : 'makers-hub__refresh-spin'
                }
                aria-hidden
              >
                <RefreshCw size={17} strokeWidth={2.4} />
              </span>
            </button>
            <button
              type="button"
              className="media-hub__search-btn"
              aria-label="搜索刮削库"
              onClick={() => {
                setSearchDraft('');
                setSearchHits([]);
                setSearchStudios([]);
                setSearchPrefixes([]);
                setSearchDone(false);
                setStack({ kind: 'search' });
              }}
            >
              <Search size={17} strokeWidth={2.4} aria-hidden />
            </button>
          </div>
        </div>
        <div
          className="media-source-switch makers-kind-switch"
          role="tablist"
          aria-label="媒体库"
        >
          {MAKER_KIND_TABS.map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={hubTab === s.id}
              className={
                hubTab === s.id
                  ? 'media-source-switch__btn is-active'
                  : 'media-source-switch__btn'
              }
              onClick={() => {
                setHubTab(s.id);
                if (stack.kind !== 'hub') setStack({ kind: 'hub' });
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="makers-view-row">
          <div
            className="media-source-switch makers-view-switch"
            role="tablist"
            aria-label="浏览方式"
          >
            {MAKER_LIBRARY_VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                role="tab"
                aria-selected={libraryView === v.id}
                className={
                  libraryView === v.id
                    ? 'media-source-switch__btn is-active'
                    : 'media-source-switch__btn'
                }
                onClick={() => {
                  setLibraryView(v.id);
                  if (v.id === 'tags') {
                    // 女优墙默认年龄升序（小→大）
                    setSortOrder(
                      actressSort === 'count' ? 'desc' : 'asc',
                    );
                  }
                  if (stack.kind !== 'hub') setStack({ kind: 'hub' });
                }}
              >
                {v.label}
              </button>
            ))}
          </div>
          <div className="makers-view-row__sort-slot" ref={sortSlotRef}>
            {combinedSortBtn(showSortBar, 'makers-view-row__sort') || (
              <span
                className="makers-view-row__sort makers-view-row__sort--ghost"
                aria-hidden
              >
                <span>名称</span>
                <OrderIcon size={14} strokeWidth={2.4} />
              </span>
            )}
            {showSortBar ? sortDropdown : null}
          </div>
        </div>
      </div>

      <div className="app-hub__scroll media-hub makers-hub__scroll">
        <div className="makers-library-panel" key={`${hubTab}-${libraryView}`}>
          {hubBody()}
        </div>
      </div>
    </div>
  );

  let push = null;

  if (stack.kind === 'search') {
    const searchQuery = searchDraft.trim();
    const searchNavTotal =
      searchStudios.length + searchPrefixes.length + searchHits.length;
    const searchStatusParts = [
      searchStudios.length ? `${searchStudios.length} 厂牌` : '',
      searchPrefixes.length ? `${searchPrefixes.length} 前缀` : '',
      searchHits.length ? `${searchHits.length} 影片` : '',
    ].filter(Boolean);
    const clearSearchResults = () => {
      setSearchHits([]);
      setSearchStudios([]);
      setSearchPrefixes([]);
      setSearchDone(false);
    };
    push = (
      <AppPush
        title="搜索"
        scrollKey={`makers-search-${hubTab}`}
        onBack={() => {
          clearSearchResults();
          setStack({ kind: 'hub' });
        }}
        skipEnterAnimation
      >
        <div className="makers-search-panel">
          <form
            className="makers-search"
            onSubmit={(e) => {
              e.preventDefault();
              void runSemanticSearch(searchDraft);
            }}
          >
            <label className="makers-search__field">
              <Search
                className="makers-search__icon"
                size={17}
                strokeWidth={2.25}
                aria-hidden
              />
              <input
                className="makers-search__input"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder={`${makerSourceLabel(hubTab)} · 番号 / 厂牌 / 前缀`}
                autoFocus
                enterKeyHint="search"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
              />
              {searchDraft ? (
                <button
                  type="button"
                  className="makers-search__clear"
                  aria-label="清除"
                  onClick={() => {
                    setSearchDraft('');
                    clearSearchResults();
                  }}
                >
                  <X size={15} strokeWidth={2.35} aria-hidden />
                </button>
              ) : null}
            </label>
            <button
              type="submit"
              className="makers-search__go"
              disabled={searchLoading || searchQuery.length < SEARCH_KEYWORD_LENGTH_MIN}
            >
              {searchLoading ? '…' : '搜索'}
            </button>
          </form>

          {searchLoading || (searchDone && searchNavTotal > 0) ? (
            <p className="makers-search__status allow-select" aria-live="polite">
              {searchLoading
                ? '搜索中…'
                : searchStatusParts.join(' · ')}
            </p>
          ) : null}

          {!searchLoading && !searchDone && searchNavTotal === 0 ? (
            <div className="makers-search-empty allow-select">
              <span className="makers-search-empty__icon" aria-hidden>
                <Search size={28} strokeWidth={1.75} />
              </span>
              <p className="makers-search-empty__title">搜番号、厂牌或前缀</p>
              <p className="makers-search-empty__hint">
                例如 SSIS-001、S1、SSIS
              </p>
            </div>
          ) : !searchLoading && searchDone && searchNavTotal === 0 ? (
            <div className="makers-search-empty allow-select">
              <span className="makers-search-empty__icon" aria-hidden>
                <Search size={28} strokeWidth={1.75} />
              </span>
              <p className="makers-search-empty__title">无匹配结果</p>
              <p className="makers-search-empty__hint">换个关键字再试试</p>
            </div>
          ) : (
            <div className="makers-search-results">
              {searchStudios.length > 0 ? (
                <section className="makers-search-nav">
                  <h3 className="makers-search-nav__title">厂牌</h3>
                  <ul className="makers-prefix-list">
                    {searchStudios.map((s) => (
                      <li key={`studio-${s.name}`}>
                        <button
                          type="button"
                          className="makers-prefix-list__row"
                          onClick={() =>
                            setStack({
                              kind: 'folderStudio',
                              studio: s.name,
                            })
                          }
                        >
                          <span className="makers-prefix-list__main">
                            <span className="makers-prefix-list__prefix">
                              {s.name}
                            </span>
                            {s.blurb ? (
                              <span className="makers-prefix-list__maker">
                                {s.blurb}
                              </span>
                            ) : null}
                          </span>
                          <span className="makers-search-nav__count allow-select">
                            {s.count}
                          </span>
                          <ChevronRight
                            size={16}
                            strokeWidth={2.2}
                            aria-hidden
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {searchPrefixes.length > 0 ? (
                <section className="makers-search-nav">
                  <h3 className="makers-search-nav__title">前缀</h3>
                  <ul className="makers-prefix-list">
                    {searchPrefixes.map((p) => {
                      const studio = String(p.studio || p.prefix || '').trim();
                      return (
                        <li key={`prefix-${p.prefix}`}>
                          <button
                            type="button"
                            className="makers-prefix-list__row"
                            onClick={() =>
                              setStack({
                                kind: 'folderPrefix',
                                studio: studio || p.prefix,
                                prefix: p.prefix,
                              })
                            }
                          >
                            <span className="makers-prefix-list__main">
                              <span className="makers-prefix-list__prefix">
                                {p.prefix}
                              </span>
                              {p.studio || p.blurb ? (
                                <span className="makers-prefix-list__maker">
                                  {p.studio || p.blurb}
                                </span>
                              ) : null}
                            </span>
                            <span className="makers-search-nav__count allow-select">
                              {p.count}
                            </span>
                            <ChevronRight
                              size={16}
                              strokeWidth={2.2}
                              aria-hidden
                            />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}
              {searchHits.length > 0 || searchLoading ? (
                <section className="makers-search-nav">
                  {searchStudios.length > 0 || searchPrefixes.length > 0 ? (
                    <h3 className="makers-search-nav__title">影片</h3>
                  ) : null}
                  {wall(searchHits, '无匹配结果', { loading: searchLoading })}
                </section>
              ) : null}
            </div>
          )}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'folderStudio') {
    push = (
      <AppPush
        title={stack.studio}
        scrollKey={`makers-folder-studio-${hubTab}-${stack.studio}`}
        onBack={() => setStack({ kind: 'hub' })}
        skipEnterAnimation
      >
        <div className="makers-library-panel">
          <div
            className="makers-drill-toolbar makers-sort-bar--push"
            ref={sortSlotRef}
          >
            <p className="makers-drill-toolbar__meta allow-select">
              {drillLoading && drillPrefixes.length === 0
                ? '加载中…'
                : `${drillTotal} 个前缀`}
            </p>
            {combinedSortBtn(true, 'makers-drill-sort')}
            {sortDropdown}
          </div>
          {drillLoading && drillPrefixes.length === 0 ? (
            <div className="makers-collage-grid makers-collage-grid--skel" aria-hidden>
              {Array.from({ length: 6 }).map((_, i) => (
                <span key={i} className="makers-collage-skel" />
              ))}
            </div>
          ) : drillPrefixes.length === 0 ? (
            <p className="media-empty makers-hub__empty allow-select">
              暂无前缀
            </p>
          ) : (
            <div className="makers-collage-grid">
              {drillPrefixes.map((p) => (
                <ScrapCollageCard
                  key={p.prefix}
                  title={p.prefix}
                  count={p.count}
                  blurb={p.blurb}
                  posterApi={p.posterApi}
                  coverUrl={p.coverUrl}
                  onClick={() =>
                    setStack({
                      kind: 'folderPrefix',
                      studio: stack.studio,
                      prefix: p.prefix,
                    })
                  }
                />
              ))}
            </div>
          )}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'folderPrefix') {
    push = (
      <AppPush
        title={stack.prefix}
        scrollKey={`makers-folder-prefix-${hubTab}-${stack.studio}-${stack.prefix}`}
        onBack={() =>
          setStack({ kind: 'folderStudio', studio: stack.studio })
        }
        skipEnterAnimation
      >
        <div className="makers-library-panel">
          <div
            className="makers-drill-toolbar makers-sort-bar--push"
            ref={sortSlotRef}
          >
            <p className="makers-drill-toolbar__meta allow-select">
              {loading && items.length === 0
                ? '加载中…'
                : `${stack.studio} · ${total} 项`}
            </p>
            {combinedSortBtn(true, 'makers-drill-sort')}
            {sortDropdown}
          </div>
          {wall(items, '暂无匹配条目', {
            loading: loading && items.length === 0,
          })}
          {drillPager}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'facet') {
    const onDrillBack = () => {
      if (stack.fromDetail) {
        setStack({
          kind: 'detail',
          item: stack.fromDetail,
          from: { kind: 'hub' },
        });
        return;
      }
      setStack({ kind: 'hub' });
    };
    const isActress = stack.facet === 'actress';
    const profileName = actressProfile?.name || stack.value;
    const profileCount =
      typeof actressProfile?.count === 'number'
        ? actressProfile.count
        : typeof stack.count === 'number'
          ? stack.count
          : total;
    push = (
      <AppPush
        title={isActress ? '女优' : stack.value}
        scrollKey={`makers-drill-${hubTab}-facet-${stack.value}`}
        onBack={onDrillBack}
        skipEnterAnimation
      >
        <div className="makers-library-panel">
          {isActress ? (
            <ScrapActressProfileHeader
              name={profileName}
              count={profileCount}
              posterApi={
                actressProfile?.posterApi ||
                (stack.posterApi &&
                (stack.posterApi.includes('/_actress/') ||
                  stack.posterApi.includes('%2F_actress%2F') ||
                  stack.posterApi.includes('%2f_actress%2f'))
                  ? stack.posterApi
                  : undefined)
              }
              loading={actressProfileLoading}
              profile={actressProfile}
            />
          ) : null}
          <div
            className="makers-drill-toolbar makers-sort-bar--push"
            ref={sortSlotRef}
          >
            <p className="makers-drill-toolbar__meta allow-select">
              {loading && items.length === 0
                ? '加载中…'
                : isActress
                  ? `番号 · ${total} 项`
                  : `共 ${total} 项`}
            </p>
            {combinedSortBtn(true, 'makers-drill-sort')}
            {sortDropdown}
          </div>
          {wall(items, '暂无匹配条目', {
            loading: loading && items.length === 0,
          })}
          {drillPager}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'detail') {
    const code = String(stack.item.code || '').trim() || '详情';
    push = (
      <AppPush
        title={code}
        scrollKey={`makers-detail-${stack.item.itemId || code}`}
        scrollMode="top"
        onBack={() => setStack(stack.from)}
        skipEnterAnimation
      >
        <ScrapDetailBody
          item={stack.item}
          region={hubTab}
          onFavoriteChange={() => setFavTick((n) => n + 1)}
          onOpenActress={(name, posterApi) =>
            openFacetFromDetail('actress', name, { posterApi })
          }
          onOpenGenre={(name) => openFacetFromDetail('genre', name)}
          onOpenStudio={(name) => openStudioFromDetail(name)}
          onItemPatch={(patch) => {
            const iid = String(stack.item.itemId || '');
            setStack((prev) =>
              prev.kind === 'detail'
                ? { ...prev, item: { ...prev.item, ...patch } }
                : prev,
            );
            // 列表缓存同步，返回后再进详情仍是中文剧情
            if (iid) {
              setItems((prev) =>
                prev.map((it) =>
                  String(it.itemId || '') === iid ? { ...it, ...patch } : it,
                ),
              );
            }
          }}
          onOpenRelated={(next) =>
            setStack({
              kind: 'detail',
              item: next,
              from: stack.from,
            })
          }
        />
      </AppPush>
    );
  }

  return (
    <div className="app-stack-root media-stack">
      {hub}
      {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}
      {push}
    </div>
  );
}
