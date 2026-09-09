'use client';

import {
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ArrowDown, ArrowUp, Check, ChevronRight, RefreshCw, Search, X } from 'lucide-react';
import {
  listScrapLibraryEmbedFacets,
  listScrapLibraryEmbedItems,
  listScrapLibraryEmbedPrefixes,
  listScrapLibraryEmbedRecommend,
  refreshScrapLibraryEmbedFacetsSnapshot,
  searchScrapLibraryEmbed,
  type MakerCatalogSourceId,
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
import { ScrapActressCard, ScrapCollageCard } from './ScrapCollageCard';
import { ScrapDetailBody } from './ScrapDetailBody';
import {
  listScrapFavorites,
  ensureScrapFavoritesLoaded,
} from './scrapFavorites';

type DrillStack =
  | { kind: 'hub' }
  | { kind: 'search' }
  /** 文件夹：厂牌 → 前缀 → 女优 → 番号 */
  | { kind: 'folderStudio'; studio: string }
  | { kind: 'folderPrefix'; studio: string; prefix: string }
  | {
      kind: 'folderActress';
      studio: string;
      prefix: string;
      actress: string;
    }
  | {
      kind: 'facet';
      facet: 'genre' | 'tag' | 'actress';
      value: string;
      /** 从详情芯片跳转时，返回可回到该条目 */
      fromDetail?: ScrapLibraryEmbedItem;
    };

type Stack =
  | DrillStack
  | { kind: 'detail'; item: ScrapLibraryEmbedItem; from: DrillStack };

const PAGE_SIZE = 45;

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
  const [searchDraft, setSearchDraft] = useState('');
  const [searchHits, setSearchHits] = useState<ScrapLibraryEmbedItem[]>([]);
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
    stack.kind === 'folderStudio' ||
    stack.kind === 'folderPrefix' ||
    stack.kind === 'folderActress'
      ? stack.studio
      : stack.kind === 'detail' &&
          (stack.from.kind === 'folderStudio' ||
            stack.from.kind === 'folderPrefix' ||
            stack.from.kind === 'folderActress')
        ? stack.from.studio
        : undefined;
  const folderPrefix =
    stack.kind === 'folderPrefix' || stack.kind === 'folderActress'
      ? stack.prefix
      : stack.kind === 'detail' &&
          (stack.from.kind === 'folderPrefix' ||
            stack.from.kind === 'folderActress')
        ? stack.from.prefix
        : undefined;
  const folderActress =
    stack.kind === 'folderActress'
      ? stack.actress
      : stack.kind === 'detail' && stack.from.kind === 'folderActress'
        ? stack.from.actress
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
  const isItemSortView =
    libraryView === 'movies' ||
    stack.kind === 'folderActress' ||
    stack.kind === 'facet' ||
    (stack.kind === 'detail' &&
      (stack.from.kind === 'folderActress' || stack.from.kind === 'facet'));
  const isPrefixSortView =
    stack.kind === 'folderStudio' ||
    (stack.kind === 'detail' && stack.from.kind === 'folderStudio');

  const loadItems = useCallback(
    async (offset: number) => {
      const seq = ++loadSeq.current;
      setLoading(true);
      setMsg('');
      try {
        const page = await listScrapLibraryEmbedItems({
          region: hubTab,
          prefix: folderPrefix,
          studio: folderStudio,
          actress:
            folderActress ||
            (facetKind === 'actress' ? facetValue : undefined),
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
      folderActress,
      facetKind,
      facetValue,
      itemSort,
      sortOrder,
    ],
  );

  const loadRecommend = useCallback(async () => {
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
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setRecommend(null);
      setMsg(e instanceof Error ? e.message : '加载失败');
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

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
          setItems(page.items || []);
          setTotal(page.total);
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
            sort: facetSort,
            order: sortOrder,
            offset,
            limit: PAGE_SIZE,
          });
          if (seq !== loadSeq.current) return;
          setFacets(page.facets || []);
          setTotal(page.total);
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
    [hubTab, libraryView, itemSort, facetSort, sortOrder],
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
  }, [hubTab, libraryView, itemSort, facetSort, sortOrder]);

  // Hub 数据：不要依赖 stack.kind，否则详情返回会整页重载（闪烁 + 丢滚动）
  // 推荐页与七区无关，切换区时不要重拉
  const hubQueryKey = `${hubTab}|${libraryView}|${itemSort}|${facetSort}|${sortOrder}`;
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
        region: hubTab,
      });
      drillCacheRef.current.clear();
      loadedDrillKeyRef.current = '';
      const counts = data.kinds || {};
      const parts = [
        counts.studio != null ? `厂牌 ${counts.studio}` : '',
        counts.genre != null ? `标签 ${counts.genre}` : '',
        counts.actress != null ? `女优 ${counts.actress}` : '',
      ].filter(Boolean);
      setMsg(
        parts.length
          ? `分面快照已更新（${parts.join(' · ')}）`
          : '分面快照已更新',
      );
      if (
        libraryView === 'folders' ||
        libraryView === 'genres' ||
        libraryView === 'tags'
      ) {
        await loadHubView(hubPage);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '刷新快照失败');
    } finally {
      setSnapRefreshing(false);
    }
  }, [snapRefreshing, hubTab, libraryView, hubPage, loadHubView]);

  const goDrillPage = useCallback(
    (next: number) => {
      setDrillPage(next);
      scrollDrillTop();
    },
    [scrollDrillTop],
  );
  // 文件夹中间层：厂牌下前缀 / 前缀下女优
  const folderMidKey = useMemo(() => {
    if (stack.kind === 'folderStudio') {
      return `fs|${hubTab}|${stack.studio}|${prefixSort}|${sortOrder}`;
    }
    if (stack.kind === 'folderPrefix') {
      return `fp|${hubTab}|${stack.studio}|${stack.prefix}|${facetSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderStudio') {
      return `fs|${hubTab}|${stack.from.studio}|${prefixSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderPrefix') {
      return `fp|${hubTab}|${stack.from.studio}|${stack.from.prefix}|${facetSort}|${sortOrder}`;
    }
    return '';
  }, [stack, hubTab, facetSort, prefixSort, sortOrder]);

  useEffect(() => {
    drillCacheRef.current.clear();
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
    const level = folderMidKey.startsWith('fs|') ? 'studio' : 'prefix';
    // 已有同层内容时不先清空，避免后退闪白
    setDrillLoading(true);
    setMsg('');
    void (async () => {
      try {
        if (level === 'studio') {
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
        } else {
          const page = await listScrapLibraryEmbedFacets({
            region: hubTab,
            kind: 'actress',
            studio: folderStudio,
            prefix: folderPrefix,
            sort: facetSort,
            order: sortOrder,
          });
          if (cancelled) return;
          const facets = page.facets || [];
          const payload = {
            prefixes: [] as ScrapLibraryEmbedPrefix[],
            facets,
            total: page.total,
          };
          putDrillCache(folderMidKey, payload);
          setDrillPrefixes(payload.prefixes);
          setDrillFacets(payload.facets);
          setDrillTotal(payload.total);
        }
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
    folderPrefix,
    facetSort,
    prefixSort,
    sortOrder,
    putDrillCache,
  ]);

  // 钻取列表：详情盖住时保持同一 drillKey，避免返回时重新拉数
  const drillLoadKey = useMemo(() => {
    if (stack.kind === 'folderActress') {
      return `${hubTab}|fa|${stack.studio}|${stack.prefix}|${stack.actress}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'facet') {
      return `${hubTab}|facet|${stack.facet}|${stack.value}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'folderActress') {
      return `${hubTab}|fa|${stack.from.studio}|${stack.from.prefix}|${stack.from.actress}|${itemSort}|${sortOrder}`;
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
      : MAKER_FACET_SORT_OPTS.find((o) => o.id === facetSort)?.label || '名称';

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
    } else {
      const next = id as MakerFacetSortId;
      if (facetSort === next) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setFacetSort(next);
      setSortOrder(next === 'count' ? 'desc' : 'asc');
    }
    setSortMenuOpen(false);
  }

  const sortOpts = isItemSortView
    ? MAKER_SORT_OPTS
    : isPrefixSortView
      ? MAKER_PREFIX_SORT_OPTS
      : MAKER_FACET_SORT_OPTS;
  const activeSortId = isItemSortView
    ? itemSort
    : isPrefixSortView
      ? prefixSort
      : facetSort;

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
      const page = await listScrapLibraryEmbedItems({
        region: hubTab,
        q,
        offset: 0,
        limit: PAGE_SIZE,
      });
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
      setSearchDone(true);
    } catch (e) {
      setSearchHits([]);
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
    if (stack.kind === 'folderActress') {
      return {
        kind: 'folderActress',
        studio: stack.studio,
        prefix: stack.prefix,
        actress: stack.actress,
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
    startTransition(() =>
      setStack({ kind: 'detail', item, from: currentDrill() }),
    );
  }

  function openFacetFromDetail(
    facet: 'genre' | 'tag' | 'actress',
    value: string,
  ) {
    const name = String(value || '').trim();
    if (!name) return;
    const fromDetail = stack.kind === 'detail' ? stack.item : undefined;
    startTransition(() =>
      setStack({
        kind: 'facet',
        facet,
        value: name,
        fromDetail,
      }),
    );
  }

  function openStudioFromDetail(value: string) {
    const name = String(value || '').trim();
    if (!name) return;
    startTransition(() =>
      setStack({ kind: 'folderStudio', studio: name }),
    );
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
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="media-shelf__rail media-shelf__rail--skel">
                {Array.from({ length: 5 }).map((__, j) => (
                  <span key={j} className="makers-poster-skel" />
                ))}
              </div>
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
              `${title} · 最新`,
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
                  startTransition(() =>
                    setStack({ kind: 'folderStudio', studio: f.name }),
                  )
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
          <div className="makers-collage-grid makers-collage-grid--skel" aria-hidden>
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className="makers-collage-skel" />
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
          <div className="makers-collage-grid">
            {facets.map((f) => (
              <ScrapCollageCard
                key={f.name}
                title={f.name}
                count={f.count}
                posterApi={f.posterApi}
                coverUrl={f.coverUrl}
                onClick={() =>
                  startTransition(() =>
                    setStack({
                      kind: 'facet',
                      facet: 'genre',
                      value: f.name,
                    }),
                  )
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
            {Array.from({ length: 9 }).map((_, i) => (
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
                  startTransition(() =>
                    setStack({
                      kind: 'facet',
                      facet: 'actress',
                      value: f.name,
                    }),
                  )
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
      <div className="makers-hub__top media-hub__top">
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
              aria-label="刷新分面快照"
              title="刷新厂牌 / 标签 / 女优快照"
              disabled={snapRefreshing}
              onClick={() => {
                void refreshFacetsSnapshot();
              }}
            >
              <RefreshCw
                size={17}
                strokeWidth={2.4}
                aria-hidden
                className={
                  snapRefreshing ? 'makers-hub__refresh-spin' : undefined
                }
              />
            </button>
            <button
              type="button"
              className="media-hub__search-btn"
              aria-label="搜索刮削库"
              onClick={() => {
                setSearchDraft('');
                setSearchHits([]);
                setSearchDone(false);
                startTransition(() => setStack({ kind: 'search' }));
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
    push = (
      <AppPush
        title="搜索"
        scrollKey={`makers-search-${hubTab}`}
        onBack={() => {
          setSearchHits([]);
          setSearchDone(false);
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
                placeholder={`${makerSourceLabel(hubTab)} · 番号或语义`}
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
                    setSearchHits([]);
                    setSearchDone(false);
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

          {searchLoading || (searchDone && searchHits.length > 0) ? (
            <p className="makers-search__status allow-select" aria-live="polite">
              {searchLoading ? '搜索中…' : `${searchHits.length} 条结果`}
            </p>
          ) : null}

          {!searchLoading && !searchDone && searchHits.length === 0 ? (
            <div className="makers-search-empty allow-select">
              <span className="makers-search-empty__icon" aria-hidden>
                <Search size={28} strokeWidth={1.75} />
              </span>
              <p className="makers-search-empty__title">搜番号或语义</p>
              <p className="makers-search-empty__hint">
                例如 SSIS-001、女优名
              </p>
            </div>
          ) : !searchLoading && searchDone && searchHits.length === 0 ? (
            <div className="makers-search-empty allow-select">
              <span className="makers-search-empty__icon" aria-hidden>
                <Search size={28} strokeWidth={1.75} />
              </span>
              <p className="makers-search-empty__title">无匹配结果</p>
              <p className="makers-search-empty__hint">换个关键字再试试</p>
            </div>
          ) : (
            wall(searchHits, '无匹配结果', { loading: searchLoading })
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
                    startTransition(() =>
                      setStack({
                        kind: 'folderPrefix',
                        studio: stack.studio,
                        prefix: p.prefix,
                      }),
                    )
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
              {drillLoading && drillFacets.length === 0
                ? '加载中…'
                : `${stack.studio} · ${drillTotal} 位女优`}
            </p>
            {combinedSortBtn(true, 'makers-drill-sort')}
            {sortDropdown}
          </div>
          {drillLoading && drillFacets.length === 0 ? (
            <div
              className="makers-actress-grid makers-actress-grid--skel"
              aria-hidden
            >
              {Array.from({ length: 9 }).map((_, i) => (
                <span key={i} className="makers-actress-skel" />
              ))}
            </div>
          ) : drillFacets.length === 0 ? (
            <p className="media-empty makers-hub__empty allow-select">
              暂无女优
            </p>
          ) : (
            <div className="makers-actress-grid">
              {drillFacets.map((f) => (
                <ScrapActressCard
                  key={f.name}
                  title={f.name}
                  count={f.count}
                  posterApi={f.posterApi}
                  posterApis={f.posterApis}
                  coverUrl={f.coverUrl}
                  onClick={() =>
                    startTransition(() =>
                      setStack({
                        kind: 'folderActress',
                        studio: stack.studio,
                        prefix: stack.prefix,
                        actress: f.name,
                      }),
                    )
                  }
                />
              ))}
            </div>
          )}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'folderActress' || stack.kind === 'facet') {
    const title =
      stack.kind === 'folderActress' ? stack.actress : stack.value;
    const onDrillBack = () => {
      if (stack.kind === 'facet' && stack.fromDetail) {
        setStack({
          kind: 'detail',
          item: stack.fromDetail,
          from: { kind: 'hub' },
        });
        return;
      }
      if (stack.kind === 'folderActress') {
        setStack({
          kind: 'folderPrefix',
          studio: stack.studio,
          prefix: stack.prefix,
        });
        return;
      }
      setStack({ kind: 'hub' });
    };
    push = (
      <AppPush
        title={title}
        scrollKey={`makers-drill-${hubTab}-${stack.kind}-${title}`}
        onBack={onDrillBack}
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
                : stack.kind === 'folderActress'
                  ? `${stack.studio} · ${stack.prefix} · ${total} 项`
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
          onOpenActress={(name) => openFacetFromDetail('actress', name)}
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
            startTransition(() =>
              setStack({
                kind: 'detail',
                item: next,
                from: stack.from,
              }),
            )
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
