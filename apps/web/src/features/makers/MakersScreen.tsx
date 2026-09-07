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
import { ArrowDown, ArrowUp, Check, ChevronRight, Search } from 'lucide-react';
import {
  listScrapLibraryEmbedFacets,
  listScrapLibraryEmbedItems,
  listScrapLibraryEmbedPrefixes,
  listScrapLibraryEmbedRecommend,
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
  MAKER_SORT_OPTS,
  type MakerFacetSortId,
  type MakerLibraryView,
  type MakerSortId,
} from './makersUi';
import { ScrapPosterCard } from './ScrapPosterCard';
import { ScrapActressCard, ScrapCollageCard } from './ScrapCollageCard';
import { ScrapDetailBody } from './ScrapDetailBody';
import {
  listScrapFavorites,
} from './scrapFavorites';

type DrillStack =
  | { kind: 'hub' }
  | { kind: 'search' }
  | { kind: 'prefix'; prefix: string }
  | {
      kind: 'facet';
      facet: 'genre' | 'tag' | 'studio';
      value: string;
      /** 从详情芯片跳转时，返回可回到该条目 */
      fromDetail?: ScrapLibraryEmbedItem;
    };

type Stack =
  | DrillStack
  | { kind: 'detail'; item: ScrapLibraryEmbedItem; from: DrillStack };

const PAGE_SIZE = 36;

function sortFacets<T extends { name: string; count: number }>(
  rows: T[],
  sortId: MakerFacetSortId,
  order: 'asc' | 'desc',
): T[] {
  const mul = order === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sortId === 'count') {
      return (a.count - b.count) * mul || a.name.localeCompare(b.name, 'zh');
    }
    return a.name.localeCompare(b.name, 'zh') * mul;
  });
}

function sortPrefixes(
  rows: ScrapLibraryEmbedPrefix[],
  sortId: MakerFacetSortId,
  order: 'asc' | 'desc',
): ScrapLibraryEmbedPrefix[] {
  const mul = order === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sortId === 'count') {
      return (
        (a.count - b.count) * mul || a.prefix.localeCompare(b.prefix, 'zh')
      );
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
  const [itemSort, setItemSort] = useState<MakerSortId>('name');
  const [facetSort, setFacetSort] = useState<MakerFacetSortId>('name');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [sortMenuOpen, setSortMenuOpen] = useState(false);
  const sortSlotRef = useRef<HTMLDivElement | null>(null);
  const [msg, setMsg] = useState('');
  const [items, setItems] = useState<ScrapLibraryEmbedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [prefixes, setPrefixes] = useState<ScrapLibraryEmbedPrefix[]>([]);
  const [facets, setFacets] = useState<ScrapLibraryEmbedFacet[]>([]);
  const [recommend, setRecommend] = useState<ScrapLibraryEmbedRecommend | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchDraft, setSearchDraft] = useState('');
  const [searchHits, setSearchHits] = useState<ScrapLibraryEmbedItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [favTick, setFavTick] = useState(0);
  const loadSeq = useRef(0);

  const hubCover = useStackCover(
    stack.kind !== 'hub',
    'makers-hub',
    'app-hub makers-hub media-hub-root',
  );

  const favoriteItems = useMemo(() => {
    return listScrapFavorites(hubTab);
  }, [hubTab, favTick]);

  const prefixFilter =
    stack.kind === 'prefix'
      ? stack.prefix
      : stack.kind === 'detail' && stack.from.kind === 'prefix'
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
  const isItemSortView =
    libraryView === 'movies' ||
    stack.kind === 'prefix' ||
    stack.kind === 'facet';

  const loadItems = useCallback(
    async (offset: number, append: boolean) => {
      const seq = ++loadSeq.current;
      if (append) setLoadingMore(true);
      else setLoading(true);
      setMsg('');
      try {
        const page = await listScrapLibraryEmbedItems({
          region: hubTab,
          prefix: prefixFilter,
          genre: facetKind === 'genre' ? facetValue : undefined,
          tag: facetKind === 'tag' ? facetValue : undefined,
          studio: facetKind === 'studio' ? facetValue : undefined,
          sort: itemSort,
          order: sortOrder,
          offset,
          limit: PAGE_SIZE,
        });
        if (seq !== loadSeq.current) return;
        setTotal(page.total);
        setItems((prev) =>
          append ? [...prev, ...(page.items || [])] : page.items || [],
        );
      } catch (e) {
        if (seq !== loadSeq.current) return;
        if (!append) {
          setItems([]);
          setTotal(0);
        }
        setMsg(e instanceof Error ? e.message : '刮削库加载失败');
      } finally {
        if (seq === loadSeq.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [
      hubTab,
      prefixFilter,
      facetKind,
      facetValue,
      itemSort,
      sortOrder,
    ],
  );

  const loadHubView = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setMsg('');
    setItems([]);
    setRecommend(null);
    setPrefixes([]);
    setFacets([]);
    setTotal(0);
    try {
      if (libraryView === 'movies') {
        const page = await listScrapLibraryEmbedItems({
          region: hubTab,
          sort: itemSort,
          order: sortOrder,
          offset: 0,
          limit: PAGE_SIZE,
        });
        if (seq !== loadSeq.current) return;
        setItems(page.items || []);
        setTotal(page.total);
      } else if (libraryView === 'recommended') {
        const data = await listScrapLibraryEmbedRecommend(hubTab);
        if (seq !== loadSeq.current) return;
        setRecommend(data);
        setTotal(data.total || 0);
      } else if (libraryView === 'folders') {
        const rows = await listScrapLibraryEmbedPrefixes(hubTab);
        if (seq !== loadSeq.current) return;
        setPrefixes(sortPrefixes(rows, facetSort, sortOrder));
        setTotal(rows.length);
      } else if (libraryView === 'collections') {
        const rows = await listScrapLibraryEmbedFacets({
          region: hubTab,
          kind: 'studio',
        });
        if (seq !== loadSeq.current) return;
        setFacets(sortFacets(rows, facetSort, sortOrder));
        setTotal(rows.length);
      } else if (libraryView === 'genres') {
        const rows = await listScrapLibraryEmbedFacets({
          region: hubTab,
          kind: 'genre',
        });
        if (seq !== loadSeq.current) return;
        setFacets(sortFacets(rows, facetSort, sortOrder));
        setTotal(rows.length);
      } else if (libraryView === 'tags') {
        const rows = await listScrapLibraryEmbedFacets({
          region: hubTab,
          kind: 'actress',
        });
        if (seq !== loadSeq.current) return;
        setFacets(sortFacets(rows, facetSort, sortOrder));
        setTotal(rows.length);
      } else if (libraryView === 'favorites') {
        setTotal(listScrapFavorites(hubTab).length);
      }
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setMsg(e instanceof Error ? e.message : '加载失败');
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [hubTab, libraryView, itemSort, facetSort, sortOrder]);

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/makers') return;
    if (tabCtx.tabReselect > 0) {
      setStack({ kind: 'hub' });
      setLibraryView('recommended');
    }
  }, [tabCtx?.tabReselect, tabCtx?.activeTab]);

  // Hub 数据：不要依赖 stack.kind，否则详情返回会整页重载（闪烁 + 丢滚动）
  // favTick 不进这里：收藏页走 favoriteItems，避免详情里点收藏清空下层 hub
  useEffect(() => {
    void loadHubView();
  }, [hubTab, libraryView, itemSort, facetSort, sortOrder, loadHubView]);

  // 钻取列表：详情盖住时保持同一 drillKey，避免返回时重新拉数
  const drillLoadKey = useMemo(() => {
    if (stack.kind === 'prefix') {
      return `${hubTab}|prefix|${stack.prefix}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'facet') {
      return `${hubTab}|facet|${stack.facet}|${stack.value}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'prefix') {
      return `${hubTab}|prefix|${stack.from.prefix}|${itemSort}|${sortOrder}`;
    }
    if (stack.kind === 'detail' && stack.from.kind === 'facet') {
      return `${hubTab}|facet|${stack.from.facet}|${stack.from.value}|${itemSort}|${sortOrder}`;
    }
    return '';
  }, [stack, hubTab, itemSort, sortOrder]);

  useEffect(() => {
    if (!drillLoadKey) return;
    void loadItems(0, false);
  }, [drillLoadKey, loadItems]);

  const sortLabel = isItemSortView
    ? MAKER_SORT_OPTS.find((o) => o.id === itemSort)?.label || '名称'
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

  const sortOpts = isItemSortView ? MAKER_SORT_OPTS : MAKER_FACET_SORT_OPTS;
  const activeSortId = isItemSortView ? itemSort : facetSort;

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
    if (stack.kind === 'prefix') return { kind: 'prefix', prefix: stack.prefix };
    return {
      kind: 'facet',
      facet: stack.facet,
      value: stack.value,
      fromDetail: stack.fromDetail,
    };
  }

  function openItem(item: ScrapLibraryEmbedItem) {
    startTransition(() =>
      setStack({ kind: 'detail', item, from: currentDrill() }),
    );
  }

  function openFacetFromDetail(
    facet: 'genre' | 'tag' | 'studio',
    value: string,
  ) {
    const name = String(value || '').trim();
    if (!name) return;
    const fromDetail =
      stack.kind === 'detail' ? stack.item : undefined;
    startTransition(() =>
      setStack({
        kind: 'facet',
        facet,
        value: name,
        fromDetail,
      }),
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
          {wallItems.map((item) => (
            <ScrapPosterCard
              key={String(item.itemId || item.code)}
              item={item}
              onClick={() => openItem(item)}
            />
          ))}
        </div>
      ) : null}
    </>
  );

  const loadMoreBtn =
    !loading && items.length > 0 && items.length < total ? (
      <div className="makers-library-more">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={loadingMore}
          onClick={() => void loadItems(items.length, true)}
        >
          {loadingMore ? '加载中…' : `加载更多 · ${items.length}/${total}`}
        </button>
      </div>
    ) : null;

  function shelfRail(
    title: string,
    children: ReactNode,
    onMore?: () => void,
  ) {
    return (
      <section className="media-shelf makers-shelf">
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
        return `${base} · 推荐`;
      case 'collections':
        return `${base} · ${total} 个厂牌`;
      case 'genres':
        return `${base} · ${total} 个标签`;
      case 'tags':
        return `${base} · ${total} 位女优`;
      case 'favorites':
        return `${base} · ${favoriteItems.length} 项收藏`;
      case 'folders':
        return `${base} · ${total} 个文件夹`;
      default:
        return `${base} · 共 ${total} 项`;
    }
  }

  const hubBody = () => {
    if (libraryView === 'favorites') {
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
      return wall(favoriteItems, '这里空空如也');
    }
    if (libraryView === 'recommended') {
      if (loading) {
        return (
          <div className="makers-hub__shelves" aria-hidden>
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="media-shelf__rail media-shelf__rail--skel">
                {Array.from({ length: 5 }).map((__, j) => (
                  <span key={j} className="makers-poster-skel" />
                ))}
              </div>
            ))}
          </div>
        );
      }
      if (!recommend) {
        return (
          <p className="media-empty makers-hub__empty allow-select">暂无推荐内容</p>
        );
      }
      return (
        <div className="makers-hub__shelves">
          {recommend.latest.length > 0
            ? shelfRail(
                '最新影片',
                recommend.latest.map((item) => (
                  <ScrapPosterCard
                    key={String(item.itemId || item.code)}
                    item={item}
                    onClick={() => openItem(item)}
                  />
                )),
                () => setLibraryView('movies'),
              )
            : null}
          {recommend.genres.length > 0
            ? shelfRail(
                '标签',
                recommend.genres.map((f) => (
                  <ScrapCollageCard
                    key={f.name}
                    title={f.name}
                    posterApi={f.posterApi}
                    posterApis={f.posterApis}
                    overlay
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
                )),
                () => setLibraryView('genres'),
              )
            : null}
          {recommend.collections.length > 0
            ? shelfRail(
                '厂牌',
                recommend.collections.map((f) => (
                  <ScrapCollageCard
                    key={f.name}
                    title={f.name}
                    count={f.count}
                    posterApi={f.posterApi}
                    posterApis={f.posterApis}
                    onClick={() =>
                      startTransition(() =>
                        setStack({
                          kind: 'facet',
                          facet: 'studio',
                          value: f.name,
                        }),
                      )
                    }
                  />
                )),
                () => setLibraryView('collections'),
              )
            : null}
          {recommend.folders.length > 0
            ? shelfRail(
                '文件夹',
                recommend.folders.map((p) => (
                  <ScrapCollageCard
                    key={p.prefix}
                    title={p.prefix}
                    count={p.count}
                    posterApi={p.posterApi}
                    posterApis={p.posterApis}
                    onClick={() =>
                      startTransition(() =>
                        setStack({ kind: 'prefix', prefix: p.prefix }),
                      )
                    }
                  />
                )),
                () => setLibraryView('folders'),
              )
            : null}
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
      if (prefixes.length === 0) {
        return (
          <p className="media-empty makers-hub__empty allow-select">
            暂无文件夹
          </p>
        );
      }
      return (
        <div className="makers-collage-grid">
          {prefixes.map((p) => (
            <ScrapCollageCard
              key={p.prefix}
              title={p.prefix}
              count={p.count}
              posterApi={p.posterApi}
              posterApis={p.posterApis}
              onClick={() =>
                startTransition(() =>
                  setStack({ kind: 'prefix', prefix: p.prefix }),
                )
              }
            />
          ))}
        </div>
      );
    }
    if (libraryView === 'collections' || libraryView === 'genres') {
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
            {libraryView === 'collections' ? '暂无厂牌' : '暂无标签'}
          </p>
        );
      }
      const overlay = libraryView === 'genres';
      return (
        <div className="makers-collage-grid">
          {facets.map((f) => (
            <ScrapCollageCard
              key={f.name}
              title={f.name}
              count={overlay ? undefined : f.count}
              posterApi={f.posterApi}
              posterApis={f.posterApis}
              overlay={overlay}
              onClick={() =>
                startTransition(() =>
                  setStack({
                    kind: 'facet',
                    facet: libraryView === 'collections' ? 'studio' : 'genre',
                    value: f.name,
                  }),
                )
              }
            />
          ))}
        </div>
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
        <div className="makers-actress-grid">
          {facets.map((f) => (
            <ScrapActressCard
              key={f.name}
              title={f.name}
              count={f.count}
              posterApi={f.posterApi}
              posterApis={f.posterApis}
              onClick={() =>
                startTransition(() =>
                  setStack({
                    kind: 'facet',
                    facet: 'tag',
                    value: f.name,
                  }),
                )
              }
            />
          ))}
        </div>
      );
    }
    return (
      <>
        {wall(
          items,
          `「${makerSourceLabel(hubTab)}」刮削库暂无条目，请先在设置同步向量`,
          { loading },
        )}
        {loadMoreBtn}
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
    push = (
      <AppPush
        title="搜索刮削库"
        scrollKey={`makers-search-${hubTab}`}
        onBack={() => {
          setSearchHits([]);
          setSearchDone(false);
          setStack({ kind: 'hub' });
        }}
        skipEnterAnimation
      >
        <div className="makers-library-panel">
          <form
            className="makers-prefix-search"
            onSubmit={(e) => {
              e.preventDefault();
              void runSemanticSearch(searchDraft);
            }}
          >
            <input
              className="makers-prefix-search__input"
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder={`在 ${makerSourceLabel(hubTab)} 搜番号 / 语义`}
              autoFocus
            />
            <button type="submit" className="makers-prefix-search__go">
              搜索
            </button>
          </form>
          <p className="makers-prefix-panel__meta allow-select">
            {searchLoading
              ? '搜索中…'
              : searchDone
                ? `「${searchDraft.trim()}」· ${searchHits.length} 条`
                : '支持番号关键字与中文语义'}
          </p>
          {wall(
            searchHits,
            searchDone ? '无匹配结果' : '输入后搜索',
            { loading: searchLoading },
          )}
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'prefix' || stack.kind === 'facet') {
    const title =
      stack.kind === 'prefix' ? stack.prefix : stack.value;
    const onDrillBack = () => {
      if (stack.kind === 'facet' && stack.fromDetail) {
        setStack({
          kind: 'detail',
          item: stack.fromDetail,
          from: { kind: 'hub' },
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
              {loading ? '加载中…' : `共 ${total} 项`}
            </p>
            {combinedSortBtn(true, 'makers-drill-sort')}
            {sortDropdown}
          </div>
          {wall(items, '暂无匹配条目', { loading })}
          {!loading && items.length > 0 && items.length < total ? (
            <div className="makers-library-more">
              <button
                type="button"
                className="app-btn-secondary"
                disabled={loadingMore}
                onClick={() => void loadItems(items.length, true)}
              >
                {loadingMore ? '加载中…' : `加载更多 · ${items.length}/${total}`}
              </button>
            </div>
          ) : null}
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
          onOpenActress={(name) => openFacetFromDetail('tag', name)}
          onOpenGenre={(name) => openFacetFromDetail('genre', name)}
          onOpenStudio={(name) => openFacetFromDetail('studio', name)}
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
