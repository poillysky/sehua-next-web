'use client';

import { useEffect, useState } from 'react';
import { Search, Star } from 'lucide-react';
import {
  fetchMediaRelated,
  type MediaItem,
  proxiedCoverUrl,
} from '@/lib/api';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { openHomeSearchFromItem } from './mediaUi';
import { MediaPosterCard } from './MediaPosterCard';

function pickAka(item: MediaItem): string[] {
  return [item.originalTitle, ...(item.aka || [])]
    .map((s) => String(s || '').trim())
    .filter(Boolean)
    .filter((s, i, arr) => arr.indexOf(s) === i && s !== item.title)
    .filter((s) => /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z0-9]/.test(s))
    .filter(
      (s) => !/^[\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u1780-\u17FF]+/.test(s),
    )
    .slice(0, 2);
}

export function MediaDetailBody({
  item,
  onOpenRelated,
}: {
  item: MediaItem;
  onOpenRelated?: (next: MediaItem) => void;
}) {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const [imgGone, setImgGone] = useState(false);
  const [related, setRelated] = useState<MediaItem[]>([]);
  const poster = proxiedCoverUrl(item.posterUrl);

  useEffect(() => {
    setImgGone(false);
  }, [item.id, item.posterUrl]);

  useEffect(() => {
    if (item.source !== 'tmdb' || !onOpenRelated) {
      setRelated([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchMediaRelated({
          mediaType: item.mediaType,
          id: item.id,
        });
        if (cancelled) return;
        const merged = [
          ...(data.recommendations || []),
          ...(data.similar || []),
        ];
        const seen = new Set<string>();
        const uniq: MediaItem[] = [];
        for (const row of merged) {
          const k = `${row.source}-${row.id}`;
          if (seen.has(k) || row.id === item.id) continue;
          seen.add(k);
          uniq.push(row);
          if (uniq.length >= 12) break;
        }
        setRelated(uniq);
      } catch {
        if (!cancelled) setRelated([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.id, item.mediaType, item.source, onOpenRelated]);

  const akaLine = pickAka(item);
  const rating =
    item.rating != null && Number(item.rating) > 0
      ? Number(item.rating).toFixed(1)
      : null;

  function onSearch() {
    const ok = openHomeSearchFromItem(item, (t) => tabCtx?.scrollToTab(t));
    if (!ok) toast('没有可用的片名用于搜索', 'error');
    else toast('已跳转 BT 库搜索', 'success');
  }

  const facts: Array<{ label: string; value: string }> = [];
  if (item.genres && item.genres.length > 0) {
    facts.push({ label: '类型', value: item.genres.slice(0, 6).join(' · ') });
  }
  if (item.cast && item.cast.length > 0) {
    facts.push({ label: '主演', value: item.cast.slice(0, 6).join(' · ') });
  }
  if (item.countries && item.countries.length > 0) {
    facts.push({ label: '地区', value: item.countries.slice(0, 4).join(' · ') });
  }

  return (
    <div className="media-detail">
      <div className="media-detail__hero">
        <div className="media-detail__poster" aria-hidden>
          {poster && !imgGone ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={poster}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={() => setImgGone(true)}
            />
          ) : (
            <span className="media-detail__poster-ph">
              {item.title.slice(0, 1)}
            </span>
          )}
        </div>
        <div className="media-detail__meta">
          <h2 className="media-detail__title allow-select">{item.title}</h2>
          {akaLine.length > 0 ? (
            <p className="media-detail__aka allow-select">
              {akaLine.join(' · ')}
            </p>
          ) : null}
          <div className="media-detail__chips">
            {rating ? (
              <span className="media-detail__chip media-detail__chip--score">
                <Star size={12} strokeWidth={2.5} aria-hidden />
                {rating}
              </span>
            ) : null}
            {item.year ? (
              <span className="media-detail__chip">{item.year}</span>
            ) : null}
            {item.runtime ? (
              <span className="media-detail__chip">{item.runtime} 分钟</span>
            ) : null}
            <span className="media-detail__chip">
              {item.mediaType === 'tv' ? '剧集' : '电影'}
            </span>
          </div>
        </div>
      </div>

      {facts.length > 0 ? (
        <div className="media-detail__facts">
          {facts.map((f) => (
            <div key={f.label} className="media-detail__fact">
              <span className="media-detail__fact-k">{f.label}</span>
              <span className="media-detail__fact-v allow-select">{f.value}</span>
            </div>
          ))}
        </div>
      ) : null}

      {item.overview ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">简介</h3>
          <p className="media-detail__overview allow-select">{item.overview}</p>
        </section>
      ) : null}

      <button type="button" className="media-detail__cta" onClick={onSearch}>
        <Search size={16} strokeWidth={2.25} aria-hidden />
        在 BT 库搜索
      </button>
      <p className="media-detail__hint">中文名 · 英文原名 · 别名 → Bitmagnet</p>

      {related.length > 0 && onOpenRelated ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">相关推荐</h3>
          <div className="media-shelf__rail">
            {related.map((it) => (
              <MediaPosterCard
                key={`${it.source}-${it.id}`}
                item={it}
                size="sm"
                onClick={() => onOpenRelated(it)}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
