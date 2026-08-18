'use client';

import { useMemo, useState } from 'react';
import { Search, Tags } from 'lucide-react';
import type { MakerFsRegionCatalog } from '@/lib/api';
import { aggregateCatalogFacets, type CatalogFacetItem } from '@/lib/makerFsUi';

type FacetTab = 'tag' | 'series';

/**
 * 分区索引：标签 / 系列，来自片商目录 catalog。
 */
export function MakerFacetBrowseBody({
  regionId,
  catalog,
  onOpenFacet,
}: {
  regionId: string;
  catalog: MakerFsRegionCatalog;
  onOpenFacet: (kind: FacetTab, value: string, count: number) => void;
}) {
  void regionId;
  const [tab, setTab] = useState<FacetTab>('tag');
  const [q, setQ] = useState('');

  const facets = useMemo(
    () => aggregateCatalogFacets(catalog.prefixes),
    [catalog.prefixes],
  );

  const list = useMemo((): CatalogFacetItem[] => {
    const raw = tab === 'tag' ? facets.tags : facets.series;
    const key = q.trim().toLowerCase();
    if (!key) return raw;
    return raw.filter((it) => String(it.name || '').toLowerCase().includes(key));
  }, [facets, tab, q]);

  return (
    <div className="mk-facet-page">
      <div className="mk-facet-page__top">
        <div className="mk-facet-tabs" role="tablist" aria-label="索引">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'tag'}
            className={`mk-facet-tabs__btn${tab === 'tag' ? ' is-active' : ''}`}
            onClick={() => setTab('tag')}
          >
            标签
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'series'}
            className={`mk-facet-tabs__btn${tab === 'series' ? ' is-active' : ''}`}
            onClick={() => setTab('series')}
          >
            系列
          </button>
        </div>

        <div className="app-search-row mk-facet-search" style={{ marginTop: 0, marginBottom: 8 }}>
          <div className="app-search">
            <Search className="app-search-icon" aria-hidden />
            <input
              placeholder={tab === 'tag' ? '筛选标签' : '筛选系列'}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
          </div>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="app-empty" style={{ paddingTop: 24 }}>
          <Tags size={22} strokeWidth={2} aria-hidden />
          <p style={{ marginTop: 8 }}>
            {tab === 'tag' ? '片商目录暂无标签' : '片商目录暂无系列'}
          </p>
        </div>
      ) : (
        <div
          className={`mk-facet-grid${tab === 'series' ? ' mk-facet-grid--rows' : ''}`}
          role="list"
        >
          {list.map((it) => (
            <button
              key={`${tab}:${it.name}`}
              type="button"
              role="listitem"
              className="mk-facet-card"
              title={it.name}
              onClick={() => onOpenFacet(tab, it.name, it.count)}
            >
              <span className="mk-facet-card__name allow-select">{it.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
