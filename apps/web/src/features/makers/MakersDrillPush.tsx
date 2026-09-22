'use client';

import type { Dispatch, RefObject, SetStateAction } from 'react';
import type {
  MakerCatalogSourceId,
  ScrapActressProfile,
  ScrapLibraryEmbedItem,
  ScrapLibraryEmbedPrefix,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { isFc2DirectStudio } from './makersUi';
import type { Stack } from './makersTypes';
import { ScrapCollageCard } from './ScrapCollageCard';
import { ScrapActressProfileHeader } from './ScrapActressProfileHeader';
import { MakersItemWall } from './MakersItemWall';
import { MakersPager } from './MakersPager';
import { MakersSortBar } from './MakersSortBar';

type SortOpt = { id: string; label: string };

type DrillCommon = {
  hubTab: MakerCatalogSourceId;
  items: ScrapLibraryEmbedItem[];
  total: number;
  loading: boolean;
  pageSize: number;
  drillPage: number;
  drillTotalPages: number;
  goDrillPage: (n: number) => void;
  sortSlotRef: RefObject<HTMLDivElement | null>;
  sortLabel: string;
  sortOrder: 'asc' | 'desc';
  sortMenuOpen: boolean;
  setSortMenuOpen: Dispatch<SetStateAction<boolean>>;
  sortOpts: readonly SortOpt[];
  activeSortId: string;
  pickSort: (id: string) => void;
  setStack: Dispatch<SetStateAction<Stack>>;
  openItem: (item: ScrapLibraryEmbedItem) => void;
};

function DrillSortToolbar({
  meta,
  sortSlotRef,
  sortLabel,
  sortOrder,
  sortMenuOpen,
  setSortMenuOpen,
  sortOpts,
  activeSortId,
  pickSort,
}: {
  meta: string;
} & Pick<
  DrillCommon,
  | 'sortSlotRef'
  | 'sortLabel'
  | 'sortOrder'
  | 'sortMenuOpen'
  | 'setSortMenuOpen'
  | 'sortOpts'
  | 'activeSortId'
  | 'pickSort'
>) {
  return (
    <div
      className="makers-drill-toolbar makers-sort-bar--push"
      ref={sortSlotRef}
    >
      <p className="makers-drill-toolbar__meta allow-select">{meta}</p>
      <MakersSortBar
        showButton
        buttonClassName="makers-drill-sort"
        sortLabel={sortLabel}
        sortOrder={sortOrder}
        menuOpen={sortMenuOpen}
        onToggleMenu={() => setSortMenuOpen((o) => !o)}
        sortOpts={sortOpts}
        activeSortId={activeSortId}
        onPickSort={pickSort}
      />
    </div>
  );
}

function drillPagerBlock(c: DrillCommon) {
  if (c.loading || c.total <= c.pageSize) return null;
  return (
    <MakersPager
      page={c.drillPage}
      totalPages={c.drillTotalPages}
      onPrev={() => c.goDrillPage(Math.max(1, c.drillPage - 1))}
      onNext={() =>
        c.goDrillPage(Math.min(c.drillTotalPages, c.drillPage + 1))
      }
    />
  );
}

export function MakersFolderStudioPush({
  studio,
  drillPrefixes,
  drillTotal,
  drillLoading,
  ...c
}: DrillCommon & {
  studio: string;
  drillPrefixes: ScrapLibraryEmbedPrefix[];
  drillTotal: number;
  drillLoading: boolean;
}) {
  const directItems = isFc2DirectStudio(studio);
  return (
    <AppPush
      title={studio}
      scrollKey={`makers-folder-studio-${c.hubTab}-${studio}`}
      onBack={() => c.setStack({ kind: 'hub' })}
      skipEnterAnimation
    >
      <div className="makers-library-panel">
        <DrillSortToolbar
          meta={
            directItems
              ? c.loading && c.items.length === 0
                ? '加载中…'
                : `${c.total} 项`
              : drillLoading && drillPrefixes.length === 0
                ? '加载中…'
                : `${drillTotal} 个前缀`
          }
          sortSlotRef={c.sortSlotRef}
          sortLabel={c.sortLabel}
          sortOrder={c.sortOrder}
          sortMenuOpen={c.sortMenuOpen}
          setSortMenuOpen={c.setSortMenuOpen}
          sortOpts={c.sortOpts}
          activeSortId={c.activeSortId}
          pickSort={c.pickSort}
        />
        {directItems ? (
          <>
            <MakersItemWall
              items={c.items}
              empty="暂无匹配条目"
              loading={c.loading && c.items.length === 0}
              region={c.hubTab}
              onOpenItem={c.openItem}
            />
            {drillPagerBlock(c)}
          </>
        ) : drillLoading && drillPrefixes.length === 0 ? (
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
                posterApis={p.posterApis}
                coverUrl={p.coverUrl}
                onClick={() =>
                  c.setStack({
                    kind: 'folderPrefix',
                    studio,
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
}

export function MakersFolderPrefixPush({
  studio,
  prefix,
  ...c
}: DrillCommon & { studio: string; prefix: string }) {
  return (
    <AppPush
      title={prefix}
      scrollKey={`makers-folder-prefix-${c.hubTab}-${studio}-${prefix}`}
      onBack={() => c.setStack({ kind: 'folderStudio', studio })}
      skipEnterAnimation
    >
      <div className="makers-library-panel">
        <DrillSortToolbar
          meta={
            c.loading && c.items.length === 0
              ? '加载中…'
              : `${studio} · ${c.total} 项`
          }
          sortSlotRef={c.sortSlotRef}
          sortLabel={c.sortLabel}
          sortOrder={c.sortOrder}
          sortMenuOpen={c.sortMenuOpen}
          setSortMenuOpen={c.setSortMenuOpen}
          sortOpts={c.sortOpts}
          activeSortId={c.activeSortId}
          pickSort={c.pickSort}
        />
        <MakersItemWall
          items={c.items}
          empty="暂无匹配条目"
          loading={c.loading && c.items.length === 0}
          region={c.hubTab}
          onOpenItem={c.openItem}
        />
        {drillPagerBlock(c)}
      </div>
    </AppPush>
  );
}

export function MakersFacetPush({
  facet,
  value,
  fromDetail,
  posterApi,
  count,
  actressProfile,
  actressProfileLoading,
  ...c
}: DrillCommon & {
  facet: 'genre' | 'tag' | 'actress';
  value: string;
  fromDetail?: ScrapLibraryEmbedItem;
  posterApi?: string;
  count?: number;
  actressProfile: ScrapActressProfile | null;
  actressProfileLoading: boolean;
}) {
  const onDrillBack = () => {
    if (fromDetail) {
      c.setStack({
        kind: 'detail',
        item: fromDetail,
        from: { kind: 'hub' },
      });
      return;
    }
    c.setStack({ kind: 'hub' });
  };
  const isActress = facet === 'actress';
  const profileName = actressProfile?.name || value;
  const profileCount =
    typeof actressProfile?.count === 'number'
      ? actressProfile.count
      : typeof count === 'number'
        ? count
        : c.total;

  return (
    <AppPush
      title={isActress ? '女优' : value}
      scrollKey={`makers-drill-${c.hubTab}-facet-${value}`}
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
              (posterApi &&
              (posterApi.includes('/_actress/') ||
                posterApi.includes('%2F_actress%2F') ||
                posterApi.includes('%2f_actress%2f'))
                ? posterApi
                : undefined)
            }
            loading={actressProfileLoading}
            profile={actressProfile}
          />
        ) : null}
        <DrillSortToolbar
          meta={
            c.loading && c.items.length === 0
              ? '加载中…'
              : isActress
                ? `番号 · ${c.total} 项`
                : `共 ${c.total} 项`
          }
          sortSlotRef={c.sortSlotRef}
          sortLabel={c.sortLabel}
          sortOrder={c.sortOrder}
          sortMenuOpen={c.sortMenuOpen}
          setSortMenuOpen={c.setSortMenuOpen}
          sortOpts={c.sortOpts}
          activeSortId={c.activeSortId}
          pickSort={c.pickSort}
        />
        <MakersItemWall
          items={c.items}
          empty="暂无匹配条目"
          loading={c.loading && c.items.length === 0}
          region={c.hubTab}
          onOpenItem={c.openItem}
        />
        {drillPagerBlock(c)}
      </div>
    </AppPush>
  );
}
