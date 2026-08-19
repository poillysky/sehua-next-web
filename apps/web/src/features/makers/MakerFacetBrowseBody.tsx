'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Search, Tags } from 'lucide-react';
import {
  fetchLibraryRegion,
  fetchLibraryRegionFacets,
  type MakerFsRegionCatalog,
} from '@/lib/api';
import {
  aggregateCatalogFacets,
  setLibraryCatalogCache,
  type CatalogFacetItem,
} from '@/lib/makerFsUi';

type FacetTab = 'tag' | 'series';

type FacetBuckets = {
  tags: CatalogFacetItem[];
  series: CatalogFacetItem[];
};

function toBuckets(
  tags: Array<{ name: string; count: number }>,
  series: Array<{ name: string; count: number }>,
): FacetBuckets {
  return {
    tags: tags.map((it) => ({ name: it.name, count: it.count })),
    series: series.map((it) => ({ name: it.name, count: it.count })),
  };
}

/**
 * 分区索引：标签 / 系列，来自片库 catalog；可手动刷新入库。
 */
export function MakerFacetBrowseBody({
  regionId,
  catalog,
  onOpenFacet,
  onCatalogRefresh,
}: {
  regionId: string;
  catalog: MakerFsRegionCatalog;
  onOpenFacet: (kind: FacetTab, value: string, count: number) => void;
  onCatalogRefresh?: (catalog: MakerFsRegionCatalog) => void;
}) {
  const [tab, setTab] = useState<FacetTab>('tag');
  const [q, setQ] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncHint, setSyncHint] = useState('');
  const [facets, setFacets] = useState<FacetBuckets>(() =>
    aggregateCatalogFacets(catalog.prefixes),
  );

  useEffect(() => {
    setFacets(aggregateCatalogFacets(catalog.prefixes));
  }, [catalog.prefixes]);

  const list = useMemo((): CatalogFacetItem[] => {
    const raw = tab === 'tag' ? facets.tags : facets.series;
    const key = q.trim().toLowerCase();
    if (!key) return raw;
    return raw.filter((it) => String(it.name || '').toLowerCase().includes(key));
  }, [facets, tab, q]);

  async function syncIndex() {
    if (syncing) return;
    setSyncing(true);
    setSyncHint('');
    try {
      const r = await fetchLibraryRegionFacets(regionId, { sync: true });
      setFacets(toBuckets(r.tags || [], r.series || []));
      const next = await fetchLibraryRegion(regionId);
      setLibraryCatalogCache(regionId, next);
      onCatalogRefresh?.(next);
      const updated = Number(r.updated || 0);
      const tagN = (r.tags || []).length;
      const seriesN = (r.series || []).length;
      if (tagN || seriesN) {
        setSyncHint(`标签 ${tagN} · 系列 ${seriesN}${updated ? ` · 变更 ${updated}` : ''}`);
      } else {
        setSyncHint('已刷新，本地暂无刮削标签');
      }
    } catch (e) {
      setSyncHint(e instanceof Error ? e.message : '更新失败');
    } finally {
      setSyncing(false);
    }
  }

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
            {facets.tags.length ? (
              <span className="mk-facet-tabs__count">{facets.tags.length}</span>
            ) : null}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'series'}
            className={`mk-facet-tabs__btn${tab === 'series' ? ' is-active' : ''}`}
            onClick={() => setTab('series')}
          >
            系列
            {facets.series.length ? (
              <span className="mk-facet-tabs__count">{facets.series.length}</span>
            ) : null}
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
          <button
            type="button"
            className="mk-facet-sync-btn"
            disabled={syncing}
            onClick={() => void syncIndex()}
          >
            {syncing ? (
              <Loader2 size={15} strokeWidth={2.25} className="mk-facet-sync-btn__spin" />
            ) : (
              <RefreshCw size={15} strokeWidth={2.25} aria-hidden />
            )}
            更新
          </button>
        </div>
        {syncHint ? <p className="mk-facet-sync-hint">{syncHint}</p> : null}
      </div>

      {list.length === 0 ? (
        <div className="app-empty" style={{ paddingTop: 24 }}>
          <Tags size={22} strokeWidth={2} aria-hidden />
          <p style={{ marginTop: 8 }}>
            {tab === 'tag' ? '片商目录暂无标签' : '片商目录暂无系列'}
          </p>
          <button
            type="button"
            className="mk-facet-sync-btn mk-facet-sync-btn--empty"
            disabled={syncing}
            onClick={() => void syncIndex()}
          >
            {syncing ? (
              <Loader2 size={15} strokeWidth={2.25} className="mk-facet-sync-btn__spin" />
            ) : (
              <RefreshCw size={15} strokeWidth={2.25} aria-hidden />
            )}
            从本地片库刷新
          </button>
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
