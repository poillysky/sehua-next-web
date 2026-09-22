'use client';

import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import {
  listScrapLibraryEmbedFacets,
  listScrapLibraryEmbedItems,
  listScrapLibraryEmbedRecommend,
  refreshScrapLibraryEmbedFacetsSnapshot,
  type MakerCatalogSourceId,
  type ScrapLibraryEmbedFacet,
  type ScrapLibraryEmbedItem,
  type ScrapLibraryEmbedPrefix,
  type ScrapLibraryEmbedRecommend,
} from '@/lib/api';
import type { MakerFacetSortId, MakerLibraryView, MakerSortId } from './makersUi';
import { isFc2FoldersDirectItems } from './makersUi';
import {
  ensureScrapFavoritesLoaded,
  listScrapFavorites,
} from './scrapFavorites';
import { MAKERS_PAGE_SIZE } from './makersTypes';

export type HubCacheEntry = {
  items: ScrapLibraryEmbedItem[];
  facets: ScrapLibraryEmbedFacet[];
  total: number;
  recommend: ScrapLibraryEmbedRecommend | null;
};

export type DrillCacheEntry = {
  prefixes: ScrapLibraryEmbedPrefix[];
  facets: ScrapLibraryEmbedFacet[];
  total: number;
};

export function putLruCache<T>(
  m: Map<string, T>,
  key: string,
  payload: T,
  max: number,
) {
  if (m.has(key)) m.delete(key);
  m.set(key, payload);
  while (m.size > max) {
    const oldest = m.keys().next().value;
    if (oldest == null) break;
    m.delete(oldest);
  }
}

export function scrollMakersHubTop() {
  const el =
    (document.querySelector('.makers-hub__scroll') as HTMLElement | null) ||
    (document.querySelector('.app-hub__scroll') as HTMLElement | null);
  el?.scrollTo({ top: 0 });
}

export function scrollMakersDrillTop() {
  const el = document.querySelector('.app-push__body') as HTMLElement | null;
  el?.scrollTo({ top: 0 });
}

export type MakersLoadersDeps = {
  hubTab: MakerCatalogSourceId;
  libraryView: MakerLibraryView;
  itemSort: MakerSortId;
  activeFacetSort: MakerFacetSortId;
  sortOrder: 'asc' | 'desc';
  folderStudio: string | undefined;
  folderPrefix: string | undefined;
  facetKind: 'actress' | 'genre' | 'tag' | undefined;
  facetValue: string | undefined;
  hubPage: number;
  snapRefreshing: boolean;
  loadSeq: MutableRefObject<number>;
  hubCacheRef: MutableRefObject<Map<string, HubCacheEntry>>;
  drillCacheRef: MutableRefObject<Map<string, DrillCacheEntry>>;
  loadedDrillKeyRef: MutableRefObject<string>;
  putHubCache: (key: string, payload: HubCacheEntry) => void;
  setLoading: Dispatch<SetStateAction<boolean>>;
  setMsg: Dispatch<SetStateAction<string>>;
  setItems: Dispatch<SetStateAction<ScrapLibraryEmbedItem[]>>;
  setTotal: Dispatch<SetStateAction<number>>;
  setPrefixes: Dispatch<SetStateAction<ScrapLibraryEmbedPrefix[]>>;
  setFacets: Dispatch<SetStateAction<ScrapLibraryEmbedFacet[]>>;
  setRecommend: Dispatch<SetStateAction<ScrapLibraryEmbedRecommend | null>>;
  setFavTick: Dispatch<SetStateAction<number>>;
  setSnapRefreshing: Dispatch<SetStateAction<boolean>>;
};

export function useMakersLoaders(d: MakersLoadersDeps) {
  const {
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
  } = d;

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
          limit: MAKERS_PAGE_SIZE,
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
      loadSeq,
      setLoading,
      setMsg,
      setItems,
      setTotal,
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
  }, [
    hubCacheRef,
    loadSeq,
    putHubCache,
    setFacets,
    setItems,
    setLoading,
    setMsg,
    setPrefixes,
    setRecommend,
    setTotal,
  ]);

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
      const offset = (pageNum - 1) * MAKERS_PAGE_SIZE;
      try {
        if (
          libraryView === 'movies' ||
          (libraryView === 'folders' && isFc2FoldersDirectItems(hubTab))
        ) {
          const page = await listScrapLibraryEmbedItems({
            region: hubTab,
            sort: itemSort,
            order: sortOrder,
            offset,
            limit: MAKERS_PAGE_SIZE,
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
            limit: MAKERS_PAGE_SIZE,
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
    [
      hubTab,
      libraryView,
      itemSort,
      activeFacetSort,
      sortOrder,
      hubCacheRef,
      loadSeq,
      putHubCache,
      setFacets,
      setFavTick,
      setItems,
      setLoading,
      setMsg,
      setPrefixes,
      setRecommend,
      setTotal,
    ],
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
  }, [
    snapRefreshing,
    libraryView,
    hubPage,
    loadHubView,
    loadRecommend,
    drillCacheRef,
    hubCacheRef,
    loadedDrillKeyRef,
    setMsg,
    setSnapRefreshing,
  ]);

  return {
    loadItems,
    loadRecommend,
    loadHubView,
    refreshFacetsSnapshot,
  };
}
