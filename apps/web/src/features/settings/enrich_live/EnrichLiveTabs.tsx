'use client';

import { cn } from '@/lib/utils';
import { TAB_META, type LiveTab } from './queueFormat';

export function EnrichLiveTabs({
  tab,
  tabCounts,
  searchActive,
  onSelectTab,
}: {
  tab: LiveTab;
  tabCounts: Record<LiveTab, number>;
  searchActive: boolean;
  onSelectTab: (id: LiveTab) => void;
}) {
  return (
    <div
      className="app-seg enrich-live__tabs enrich-live__tabs--status"
      role="tablist"
      aria-label="刮削队列"
    >
      {TAB_META.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={searchActive ? false : tab === t.id}
          className={cn(
            'app-seg__btn',
            !searchActive && tab === t.id && 'app-seg__btn--active',
            searchActive && 'enrich-live__tab--dim',
          )}
          onClick={() => onSelectTab(t.id)}
        >
          <span className="enrich-live__tab-label">{t.label}</span>
          <span className="enrich-live__tab-count">
            {Number(tabCounts[t.id] || 0).toLocaleString()}
          </span>
        </button>
      ))}
    </div>
  );
}
