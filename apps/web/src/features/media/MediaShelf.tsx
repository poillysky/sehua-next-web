'use client';

import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  fetchMediaCharts,
  type MediaCategoryId,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { MediaPosterCard } from './MediaPosterCard';

/** MoviePilot 式横滑海报架 */
export function MediaShelf({
  source,
  category,
  chart,
  title,
  onOpenAll,
  onOpenItem,
}: {
  source: MediaSourceId;
  category: MediaCategoryId;
  chart: string;
  title: string;
  onOpenAll: () => void;
  onOpenItem: (item: MediaItem) => void;
}) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr('');
    void (async () => {
      try {
        const data = await fetchMediaCharts({
          source,
          category,
          chart,
          page: 1,
        });
        if (cancelled) return;
        setItems((data.items || []).slice(0, 12));
      } catch (e) {
        if (cancelled) return;
        setItems([]);
        setErr(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, category, chart]);

  return (
    <section className="media-shelf">
      <button type="button" className="media-shelf__head" onClick={onOpenAll}>
        <span className="media-shelf__title">{title}</span>
        <span className="media-shelf__more">
          全部
          <ChevronRight size={15} strokeWidth={2.25} aria-hidden />
        </span>
      </button>

      {loading ? (
        <div className="media-shelf__rail media-shelf__rail--skel" aria-hidden>
          {Array.from({ length: 5 }).map((_, i) => (
            <span key={i} className="media-poster-skel" />
          ))}
        </div>
      ) : null}

      {!loading && err ? (
        <p className="media-shelf__err allow-select">{err}</p>
      ) : null}

      {!loading && !err && items.length === 0 ? (
        <p className="media-shelf__err">暂无内容</p>
      ) : null}

      {!loading && !err && items.length > 0 ? (
        <div className="media-shelf__rail">
          {items.map((it, i) => (
            <MediaPosterCard
              key={`${it.source}-${it.id}`}
              item={it}
              rank={i + 1}
              size="sm"
              onClick={() => onOpenItem(it)}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
