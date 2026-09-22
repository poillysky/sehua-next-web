'use client';

import { AppMsg } from '@/components/ui/AppMsg';
import { ResourceCard } from './ResourceCard';
import { SearchFilters } from './SearchFilters';
import { SearchResultsLoading } from './SearchResultsLoading';
import { MagnetCard } from '@/features/magnet/BitmagnetResultList';
import type { HomeScreenState } from './useHomeScreen';

type Props = {
  h: HomeScreenState;
};

/** 结果列表区：筛选、提示、错误/空态、卡片列表、无限滚动 */
export function HomeResultsBody({ h }: Props) {
  return (
    <div className="app-body home-search-body" ref={h.scrollBodyRef}>
      {h.msg ? <AppMsg onDismiss={() => h.setMsg('')}>{h.msg}</AppMsg> : null}

      {h.isKeywordSearch ? (
        <SearchFilters
          sortType={h.sortType}
          matchMode={h.matchMode}
          filterTime={h.filterTime}
          filterSize={h.filterSize}
          showMatch
          showSource
          searchSource={h.searchSource}
          onSearchSourceChange={h.onSearchSourceChange}
          onSortType={h.onFilterChange(h.setSortType)}
          onMatchMode={h.onFilterChange(h.setMatchMode)}
          onFilterTime={h.onFilterChange(h.setFilterTime)}
          onFilterSize={h.onFilterChange(h.setFilterSize)}
        />
      ) : null}

      <p className="app-hint">{h.hint}</p>
      {h.isKeywordSearch && h.magnetError && h.magnetTotal === 0 ? (
        <p className="app-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
          Bitmagnet：{h.magnetError}
        </p>
      ) : null}

      {h.activeLoading ? (
        <SearchResultsLoading keyword={h.isKeywordSearch ? h.keyword : undefined} />
      ) : h.activeSource === 'sehua' && h.error && h.items.length === 0 ? (
        <div className="app-error">
          <p>{h.error}</p>
          <p className="app-error-hint">请到「更多」检查资源库配置</p>
          <div className="app-actions" style={{ justifyContent: 'center' }}>
            <button
              type="button"
              className="app-btn-secondary"
              onClick={() => {
                h.setSehualPage(1);
                h.setReloadToken((n) => n + 1);
              }}
            >
              重试
            </button>
          </div>
        </div>
      ) : h.activeEmpty ? (
        <div className="app-empty">
          <p>{h.isKeywordSearch ? '没有匹配结果' : '暂无资源'}</p>
          {h.isKeywordSearch ? (
            <p className="app-footnote" style={{ marginTop: 8 }}>
              试试更短的关键词，或放宽筛选
            </p>
          ) : null}
        </div>
      ) : (
        <>
          <div className="bm-result-list">
            {h.activeSource === 'sehua'
              ? h.items.map((item) => (
                  <ResourceCard
                    key={item.hash}
                    item={item}
                    keywords={h.resultKeywords}
                    cropRegion={h.searchRegion || undefined}
                    onOpen={h.openSehualDetail}
                  />
                ))
              : h.magnetItems.map((item) => (
                  <MagnetCard
                    key={item.hash || item.infoHash || item.path}
                    item={item}
                    keywords={h.resultKeywords}
                    onOpen={h.openMagnetDetail}
                  />
                ))}
          </div>
          <div className="home-infinite">
            <div
              ref={h.sentinelRef}
              className="home-infinite__sentinel"
              aria-hidden
            />
            {h.activeLoadingMore ? (
              <p className="app-loading">加载更多…</p>
            ) : null}
            {!h.activeHasMore && h.activeItems.length > 0 ? (
              <p className="home-infinite__end">已全部加载</p>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
