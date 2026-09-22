'use client';

import type { Dispatch, ReactNode, RefObject, SetStateAction } from 'react';
import { ChevronRight, RefreshCw, Search } from 'lucide-react';
import type {
  MakerCatalogSourceId,
  ScrapLibraryEmbedFacet,
  ScrapLibraryEmbedItem,
  ScrapLibraryEmbedRecommend,
} from '@/lib/api';
import {
  isCensoredRightCropRegion,
  isMakerLandscapeRegion,
  makerSourceLabel,
  MAKER_KIND_TABS,
  MAKER_LIBRARY_VIEWS,
  type MakerFacetSortId,
  type MakerLibraryView,
} from './makersUi';
import type { Stack } from './makersTypes';
import { ScrapPosterCard } from './ScrapPosterCard';
import { ScrapActressCard, ScrapCollageCard, ScrapTagCard } from './ScrapCollageCard';
import { MakersItemWall } from './MakersItemWall';
import { MakersPager } from './MakersPager';
import { MakersSortBar } from './MakersSortBar';
import type { useStackCover } from '@/hooks/useStackCover';

function shelfRail(
  railKey: string,
  title: string,
  children: ReactNode,
  onMore?: () => void,
  opts?: { landscape?: boolean },
) {
  return (
    <section
      key={railKey}
      className={
        opts?.landscape
          ? 'media-shelf makers-shelf makers-shelf--landscape'
          : 'media-shelf makers-shelf'
      }
    >
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

function viewMetaLabel(
  hubTab: MakerCatalogSourceId,
  libraryView: MakerLibraryView,
  loading: boolean,
  total: number,
  favoriteCount: number,
): string {
  const base = makerSourceLabel(hubTab);
  if (loading) return `${base} · 加载中…`;
  switch (libraryView) {
    case 'recommended':
      return loading ? '推荐 · 加载中…' : '推荐 · 各区最新';
    case 'folders':
      return `${base} · ${total} 个厂牌`;
    case 'genres':
      return `${base} · ${total} 个标签`;
    case 'tags':
      return `${base} · ${total} 位女优`;
    case 'favorites':
      return `${base} · ${favoriteCount} 项收藏`;
    default:
      return `${base} · 共 ${total} 项`;
  }
}

export function MakersHub({
  hubCover,
  hubTab,
  setHubTab,
  libraryView,
  setLibraryView,
  stack,
  setStack,
  sortMenuOpen,
  setSortMenuOpen,
  sortSlotRef,
  showSortBar,
  sortLabel,
  sortOrder,
  setSortOrder,
  actressSort,
  sortOpts,
  activeSortId,
  pickSort,
  loading,
  total,
  items,
  facets,
  recommend,
  favoriteItems,
  favoritePageItems,
  hubPage,
  hubTotalPages,
  favTotalPages,
  pageSize,
  goHubPage,
  snapRefreshing,
  refreshFacetsSnapshot,
  openSearch,
  openItem,
}: {
  hubCover: ReturnType<typeof useStackCover>;
  hubTab: MakerCatalogSourceId;
  setHubTab: (id: MakerCatalogSourceId) => void;
  libraryView: MakerLibraryView;
  setLibraryView: (id: MakerLibraryView) => void;
  stack: Stack;
  setStack: Dispatch<SetStateAction<Stack>>;
  sortMenuOpen: boolean;
  setSortMenuOpen: Dispatch<SetStateAction<boolean>>;
  sortSlotRef: RefObject<HTMLDivElement | null>;
  showSortBar: boolean;
  sortLabel: string;
  sortOrder: 'asc' | 'desc';
  setSortOrder: Dispatch<SetStateAction<'asc' | 'desc'>>;
  actressSort: MakerFacetSortId;
  sortOpts: readonly { id: string; label: string }[];
  activeSortId: string;
  pickSort: (id: string) => void;
  loading: boolean;
  total: number;
  items: ScrapLibraryEmbedItem[];
  facets: ScrapLibraryEmbedFacet[];
  recommend: ScrapLibraryEmbedRecommend | null;
  favoriteItems: ScrapLibraryEmbedItem[];
  favoritePageItems: ScrapLibraryEmbedItem[];
  hubPage: number;
  hubTotalPages: number;
  favTotalPages: number;
  pageSize: number;
  goHubPage: (n: number) => void;
  snapRefreshing: boolean;
  refreshFacetsSnapshot: () => void | Promise<void>;
  openSearch: () => void;
  openItem: (item: ScrapLibraryEmbedItem) => void;
}) {
  const hubPager =
    !loading &&
    (libraryView === 'movies' ||
      libraryView === 'folders' ||
      libraryView === 'genres' ||
      libraryView === 'tags') &&
    total > pageSize ? (
      <MakersPager
        page={hubPage}
        totalPages={hubTotalPages}
        onPrev={() => goHubPage(Math.max(1, hubPage - 1))}
        onNext={() => goHubPage(Math.min(hubTotalPages, hubPage + 1))}
      />
    ) : null;

  const favPager =
    !loading &&
    libraryView === 'favorites' &&
    favoriteItems.length > pageSize ? (
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

  function hubBody() {
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
          <MakersItemWall
            items={favoritePageItems}
            empty="这里空空如也"
            region={hubTab}
            onOpenItem={openItem}
          />
          {favPager}
        </>
      );
    }
    if (libraryView === 'recommended') {
      if (loading) {
        return (
          <div className="makers-hub__shelves" aria-hidden>
            {MAKER_KIND_TABS.map((tab) => (
              <section
                key={tab.id}
                className={
                  isMakerLandscapeRegion(tab.id)
                    ? 'media-shelf makers-shelf makers-shelf--landscape'
                    : 'media-shelf makers-shelf'
                }
              >
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
            const shelfItems = shelf.latest || [];
            if (shelfItems.length === 0) return null;
            return shelfRail(
              shelf.region || title,
              `${title} · 最近刮削`,
              shelfItems.map((item, i) => (
                <ScrapPosterCard
                  key={`${shelf.region}-${String(item.itemId || item.code)}`}
                  item={item}
                  eager={i < 6}
                  rightCrop={isCensoredRightCropRegion(shelf.region)}
                  onClick={() => openItem(item)}
                />
              )),
              () => {
                if (MAKER_KIND_TABS.some((t) => t.id === shelf.region)) {
                  setHubTab(shelf.region as MakerCatalogSourceId);
                }
                setLibraryView('movies');
              },
              { landscape: isMakerLandscapeRegion(shelf.region) },
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
                posterApis={f.posterApis}
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
        <MakersItemWall
          items={items}
          empty={`「${makerSourceLabel(hubTab)}」刮削库暂无条目，请先在设置同步向量`}
          loading={loading}
          region={hubTab}
          onOpenItem={openItem}
        />
        {hubPager}
      </>
    );
  }

  return (
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
          <p className="makers-hub__meta allow-select">
            {viewMetaLabel(
              hubTab,
              libraryView,
              loading,
              total,
              favoriteItems.length,
            )}
          </p>
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
              title="刷新各区厂牌/标签/女优 + 推荐 + 影片首页快照"
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
              onClick={openSearch}
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
                    setSortOrder(actressSort === 'count' ? 'desc' : 'asc');
                  }
                  if (stack.kind !== 'hub') setStack({ kind: 'hub' });
                }}
              >
                {v.label}
              </button>
            ))}
          </div>
          <div className="makers-view-row__sort-slot" ref={sortSlotRef}>
            <MakersSortBar
              showButton={showSortBar}
              buttonClassName="makers-view-row__sort"
              ghostWhenHidden
              sortLabel={sortLabel}
              sortOrder={sortOrder}
              menuOpen={sortMenuOpen}
              onToggleMenu={() => setSortMenuOpen((o) => !o)}
              sortOpts={sortOpts}
              activeSortId={activeSortId}
              onPickSort={pickSort}
            />
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
}
