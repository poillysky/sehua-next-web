'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Search, Tags } from 'lucide-react';
import {
  fetchLibraryRegionFacets,
  type LibraryFacetItem,
  type LibraryRegionFacets,
} from '@/lib/api';

type FacetTab = 'tag' | 'series';

/**
 * 分区标签 / 系列分类浏览。
 * 默认只读落库；点「更新」才扫盘同步。
 */
export function MakerFacetBrowseBody({
  regionId,
  onOpenFacet,
}: {
  regionId: string;
  onOpenFacet: (kind: FacetTab, value: string, count: number) => void;
}) {
  const [tab, setTab] = useState<FacetTab>('tag');
  const [data, setData] = useState<LibraryRegionFacets | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');

  const load = useCallback(
    async (opts?: { sync?: boolean; signal?: AbortSignal }) => {
      const sync = Boolean(opts?.sync);
      if (sync) setSyncing(true);
      else setLoading(true);
      setError('');
      try {
        const d = await fetchLibraryRegionFacets(regionId, {
          sync,
          signal: opts?.signal,
        });
        if (opts?.signal?.aborted) return;
        setData(d);
      } catch (e) {
        if (opts?.signal?.aborted) return;
        setError(e instanceof Error ? e.message : '加载分类失败');
      } finally {
        if (!opts?.signal?.aborted) {
          setLoading(false);
          setSyncing(false);
        }
      }
    },
    [regionId],
  );

  useEffect(() => {
    const ac = new AbortController();
    setData(null);
    void load({ signal: ac.signal });
    return () => ac.abort();
  }, [load]);

  const list = useMemo(() => {
    const raw: LibraryFacetItem[] =
      tab === 'tag' ? data?.tags || [] : data?.series || [];
    const key = q.trim().toLowerCase();
    if (!key) return raw;
    return raw.filter((it) => String(it.name || '').toLowerCase().includes(key));
  }, [data, tab, q]);

  const updatedLabel = data?.updatedAt
    ? String(data.updatedAt).replace('T', ' ').replace('Z', '')
    : '';

  return (
    <div className="mk-facet-page">
      <div className="mk-facet-page__top">
        <div className="mk-facet-tabs" role="tablist" aria-label="分类">
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
          <button
            type="button"
            className="mk-facet-sync-btn"
            disabled={loading || syncing}
            title="从刮削落盘增量更新分类"
            onClick={() => void load({ sync: true })}
          >
            <RefreshCw
              size={15}
              strokeWidth={2.25}
              aria-hidden
              className={syncing ? 'mk-facet-sync-btn__spin' : undefined}
            />
            <span>{syncing ? '更新中' : '更新'}</span>
          </button>
        </div>

        {loading || syncing || error || list.length === 0 || updatedLabel ? (
          <p className="app-hint" style={{ marginTop: 0, marginBottom: 8 }}>
            {loading
              ? '读取落库分类…'
              : syncing
                ? '正在同步刮削分类…'
                : error
                  ? error
                  : list.length === 0
                    ? '暂无分类，可先刮削后点「更新」'
                    : updatedLabel
                      ? `落库 ${updatedLabel}`
                      : null}
          </p>
        ) : null}
      </div>

      {loading ? (
        <div
          className={`mk-facet-grid mk-facet-grid--skel${tab === 'series' ? ' mk-facet-grid--rows' : ''}`}
          aria-busy="true"
        >
          {Array.from({ length: tab === 'series' ? 8 : 12 }).map((_, i) => (
            <div key={i} className="mk-facet-card mk-facet-card--skel" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="app-empty" style={{ paddingTop: 24 }}>
          <Tags size={22} strokeWidth={2} aria-hidden />
          <p style={{ marginTop: 8 }}>没有可展示的分类</p>
          <button
            type="button"
            className="mk-facet-sync-btn mk-facet-sync-btn--empty"
            disabled={syncing}
            onClick={() => void load({ sync: true })}
          >
            <RefreshCw size={15} strokeWidth={2.25} aria-hidden />
            <span>{syncing ? '更新中…' : '更新分类'}</span>
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
