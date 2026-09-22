'use client';

import { AppMsg } from '@/components/ui/AppMsg';
import { AppPush } from '@/components/ui/AppPush';
import { isMakerLandscapeRegion } from './makersUi';
import { ScrapDetailBody } from './ScrapDetailBody';
import { useMakersScreen } from './useMakersScreen';
import { MakersHub } from './MakersHub';
import { MakersSearchPush } from './MakersSearchPush';
import {
  MakersFacetPush,
  MakersFolderPrefixPush,
  MakersFolderStudioPush,
} from './MakersDrillPush';

export function MakersScreen() {
  const m = useMakersScreen();

  const drillCommon = {
    hubTab: m.hubTab,
    items: m.items,
    total: m.total,
    loading: m.loading,
    pageSize: m.pageSize,
    drillPage: m.drillPage,
    drillTotalPages: m.drillTotalPages,
    goDrillPage: m.goDrillPage,
    sortSlotRef: m.sortSlotRef,
    sortLabel: m.sortLabel,
    sortOrder: m.sortOrder,
    sortMenuOpen: m.sortMenuOpen,
    setSortMenuOpen: m.setSortMenuOpen,
    sortOpts: m.sortOpts,
    activeSortId: m.activeSortId,
    pickSort: m.pickSort,
    setStack: m.setStack,
    openItem: m.openItem,
  };

  let push = null;

  if (m.stack.kind === 'search') {
    push = (
      <MakersSearchPush
        hubTab={m.hubTab}
        searchDraft={m.searchDraft}
        setSearchDraft={m.setSearchDraft}
        searchHits={m.searchHits}
        searchStudios={m.searchStudios}
        searchPrefixes={m.searchPrefixes}
        searchLoading={m.searchLoading}
        searchDone={m.searchDone}
        runSemanticSearch={m.runSemanticSearch}
        clearSearchResults={m.clearSearchResults}
        setStack={m.setStack}
        openItem={m.openItem}
      />
    );
  } else if (m.stack.kind === 'folderStudio') {
    push = (
      <MakersFolderStudioPush
        {...drillCommon}
        studio={m.stack.studio}
        drillPrefixes={m.drillPrefixes}
        drillTotal={m.drillTotal}
        drillLoading={m.drillLoading}
      />
    );
  } else if (m.stack.kind === 'folderPrefix') {
    push = (
      <MakersFolderPrefixPush
        {...drillCommon}
        studio={m.stack.studio}
        prefix={m.stack.prefix}
      />
    );
  } else if (m.stack.kind === 'facet') {
    push = (
      <MakersFacetPush
        {...drillCommon}
        facet={m.stack.facet}
        value={m.stack.value}
        fromDetail={m.stack.fromDetail}
        posterApi={m.stack.posterApi}
        count={m.stack.count}
        actressProfile={m.actressProfile}
        actressProfileLoading={m.actressProfileLoading}
      />
    );
  } else if (m.stack.kind === 'detail') {
    const code = String(m.stack.item.code || '').trim() || '详情';
    const detailItem = m.stack.item;
    const detailFrom = m.stack.from;
    push = (
      <AppPush
        title={code}
        scrollKey={`makers-detail-${detailItem.itemId || code}`}
        scrollMode="top"
        onBack={() => m.setStack(detailFrom)}
        skipEnterAnimation
      >
        <ScrapDetailBody
          item={detailItem}
          region={m.hubTab}
          onFavoriteChange={() => m.setFavTick((n) => n + 1)}
          onOpenActress={(name, posterApi) =>
            m.openFacetFromDetail('actress', name, { posterApi })
          }
          onOpenGenre={(name) => m.openFacetFromDetail('genre', name)}
          onOpenStudio={(name) => m.openStudioFromDetail(name)}
          onItemPatch={(patch) => {
            const iid = String(detailItem.itemId || '');
            m.setStack((prev) =>
              prev.kind === 'detail'
                ? { ...prev, item: { ...prev.item, ...patch } }
                : prev,
            );
            // 列表缓存同步，返回后再进详情仍是中文剧情
            if (iid) {
              m.setItems((prev) =>
                prev.map((it) =>
                  String(it.itemId || '') === iid ? { ...it, ...patch } : it,
                ),
              );
            }
          }}
          onOpenRelated={(next) =>
            m.setStack({
              kind: 'detail',
              item: next,
              from: detailFrom,
            })
          }
        />
      </AppPush>
    );
  }

  return (
    <div
      className={
        // 推荐页按货架自定横竖；其它库页才跟当前分区
        m.libraryView !== 'recommended' && isMakerLandscapeRegion(m.hubTab)
          ? 'app-stack-root media-stack makers-landscape'
          : 'app-stack-root media-stack'
      }
    >
      <MakersHub
        hubCover={m.hubCover}
        hubTab={m.hubTab}
        setHubTab={m.setHubTab}
        libraryView={m.libraryView}
        setLibraryView={m.setLibraryView}
        stack={m.stack}
        setStack={m.setStack}
        sortMenuOpen={m.sortMenuOpen}
        setSortMenuOpen={m.setSortMenuOpen}
        sortSlotRef={m.sortSlotRef}
        showSortBar={m.showSortBar}
        sortLabel={m.sortLabel}
        sortOrder={m.sortOrder}
        setSortOrder={m.setSortOrder}
        actressSort={m.actressSort}
        sortOpts={m.sortOpts}
        activeSortId={m.activeSortId}
        pickSort={m.pickSort}
        loading={m.loading}
        total={m.total}
        items={m.items}
        facets={m.facets}
        recommend={m.recommend}
        favoriteItems={m.favoriteItems}
        favoritePageItems={m.favoritePageItems}
        hubPage={m.hubPage}
        hubTotalPages={m.hubTotalPages}
        favTotalPages={m.favTotalPages}
        pageSize={m.pageSize}
        goHubPage={m.goHubPage}
        snapRefreshing={m.snapRefreshing}
        refreshFacetsSnapshot={m.refreshFacetsSnapshot}
        openSearch={m.openSearch}
        openItem={m.openItem}
      />
      {m.msg ? <AppMsg onDismiss={() => m.setMsg('')}>{m.msg}</AppMsg> : null}
      {push}
    </div>
  );
}
