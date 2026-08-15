'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  fetchMediaCharts,
  type MediaCategoryId,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { chartsForSource } from './mediaUi';
import { MediaPosterCard } from './MediaPosterCard';

export function MediaChartBody({
  source,
  category,
  initialChart,
  onOpen,
}: {
  source: MediaSourceId;
  category: MediaCategoryId;
  initialChart?: string;
  onOpen: (item: MediaItem) => void;
}) {
  const charts = chartsForSource(source, category);
  const [chart, setChart] = useState(() => {
    if (initialChart && charts.some((c) => c.id === initialChart)) {
      return initialChart;
    }
    return charts[0]?.id || 'popular';
  });
  const [items, setItems] = useState<MediaItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    const next =
      initialChart && charts.some((c) => c.id === initialChart)
        ? initialChart
        : charts[0]?.id || 'popular';
    setChart(next);
    setPage(1);
  }, [source, category, initialChart]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const data = await fetchMediaCharts({
        source,
        category,
        chart,
        page,
      });
      setItems(data.items || []);
      setTotalPages(Math.max(1, Number(data.totalPages || 1)));
    } catch (e) {
      setItems([]);
      setErr(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [source, category, chart, page]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="media-chart">
      <div className="media-chart__tabs" role="tablist" aria-label="榜单">
        {charts.map((c) => (
          <button
            key={c.id}
            type="button"
            role="tab"
            aria-selected={chart === c.id}
            className={
              chart === c.id ? 'media-chart__tab is-active' : 'media-chart__tab'
            }
            onClick={() => {
              setPage(1);
              setChart(c.id);
            }}
          >
            {c.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="media-wall media-wall--skel" aria-hidden>
          {Array.from({ length: 9 }).map((_, i) => (
            <span key={i} className="media-poster-skel media-poster-skel--wall" />
          ))}
        </div>
      ) : null}

      {!loading && err ? (
        <p className="media-empty allow-select">{err}</p>
      ) : null}
      {!loading && !err && items.length === 0 ? (
        <p className="media-empty">暂无条目</p>
      ) : null}

      {!loading && !err && items.length > 0 ? (
        <div className="media-wall">
          {items.map((it, i) => (
            <MediaPosterCard
              key={`${it.source}-${it.id}`}
              item={it}
              rank={(page - 1) * 20 + i + 1}
              size="md"
              onClick={() => onOpen(it)}
            />
          ))}
        </div>
      ) : null}

      {!loading && !err && totalPages > 1 ? (
        <div className="media-chart__pager">
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span className="media-chart__page-meta">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
