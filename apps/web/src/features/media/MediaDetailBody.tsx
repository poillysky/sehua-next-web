'use client';

import { useEffect, useRef, useState } from 'react';
import { Search, Star } from 'lucide-react';
import {
  fetchMediaRelated,
  type MediaCastPerson,
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

function normalizeCast(raw: MediaItem['cast']): MediaCastPerson[] {
  if (!Array.isArray(raw)) return [];
  const out: MediaCastPerson[] = [];
  for (const row of raw) {
    if (typeof row === 'string') {
      const name = row.trim();
      if (name) out.push({ name });
      continue;
    }
    if (row && typeof row === 'object' && 'name' in row) {
      const name = String(row.name || '').trim();
      if (!name) continue;
      const id =
        row.id != null && String(row.id).trim() ? String(row.id) : undefined;
      const avatarUrl =
        row.avatarUrl != null && String(row.avatarUrl).trim()
          ? String(row.avatarUrl)
          : undefined;
      out.push({ name, id, avatarUrl });
    }
  }
  return out.slice(0, 12);
}

export function MediaDetailBody({
  item,
  enriching = false,
  onOpenRelated,
  onOpenPerson,
}: {
  item: MediaItem;
  /** 列表项已展示、详情接口仍在拉取时 */
  enriching?: boolean;
  onOpenRelated?: (next: MediaItem) => void;
  onOpenPerson?: (person: MediaCastPerson) => void;
}) {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const [imgGone, setImgGone] = useState(false);
  const [related, setRelated] = useState<MediaItem[]>([]);
  /** 同一条目内锁定首张已展示海报，避免详情回填换 URL 导致闪没再载 */
  const stickyPosterRef = useRef<{ id: string; url: string }>({
    id: item.id,
    url: proxiedCoverUrl(item.posterUrl),
  });
  const nextPoster = proxiedCoverUrl(item.posterUrl);
  if (stickyPosterRef.current.id !== item.id) {
    stickyPosterRef.current = { id: item.id, url: nextPoster };
  } else if (nextPoster && !stickyPosterRef.current.url) {
    stickyPosterRef.current.url = nextPoster;
  }
  const poster = stickyPosterRef.current.url;
  const cast = normalizeCast(item.cast);

  useEffect(() => {
    setImgGone(false);
  }, [item.id]);

  useEffect(() => {
    if (!onOpenRelated || enriching) {
      if (enriching) setRelated([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchMediaRelated({
          source: item.source,
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
  }, [item.id, item.mediaType, item.source, onOpenRelated, enriching]);

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

  return (
    <div className="media-detail">
      {poster && !imgGone ? (
        <div className="media-detail__wash" aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={poster}
            alt=""
            loading="eager"
            decoding="async"
            fetchPriority="high"
            referrerPolicy="no-referrer"
          />
        </div>
      ) : null}

      <div className="media-detail__hero">
        <div className="media-detail__poster" aria-hidden>
          {poster && !imgGone ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={poster}
              alt=""
              loading="eager"
              decoding="async"
              fetchPriority="high"
              referrerPolicy="no-referrer"
              onError={() => setImgGone(true)}
            />
          ) : (
            <span className="media-detail__poster-ph">
              {item.title.slice(0, 1)}
            </span>
          )}
          {rating ? (
            <span className="media-detail__score">
              <Star size={11} strokeWidth={2.6} aria-hidden />
              <span className="media-detail__score-n">{rating}</span>
            </span>
          ) : null}
        </div>
        <div className="media-detail__meta">
          <h2 className="media-detail__title allow-select">{item.title}</h2>
          {akaLine.length > 0 ? (
            <p className="media-detail__aka allow-select">
              {akaLine.join(' · ')}
            </p>
          ) : null}

          <div className="media-detail__stats">
            <div className="media-detail__stats-main">
              <p className="media-detail__meta-line allow-select">
                {[
                  item.year || '',
                  item.mediaType === 'tv' ? '剧集' : '电影',
                  item.runtime ? `${item.runtime} 分钟` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              {(item.genres?.length || item.countries?.length) ? (
                <p className="media-detail__meta-sub allow-select">
                  {[
                    ...(item.genres || []).slice(0, 4),
                    ...(item.countries || []).slice(0, 2),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              ) : null}
            </div>
          </div>

          {cast.length > 0 ? (
            <p className="media-detail__leads allow-select">
              <span className="media-detail__leads-k">主演</span>
              <span className="media-detail__leads-v">
                {cast
                  .slice(0, 4)
                  .map((p) => p.name)
                  .join(' · ')}
              </span>
            </p>
          ) : null}
        </div>
      </div>

      {cast.length > 0 ? (
        <section className="media-detail__section media-detail__cast-sec">
          <h3 className="media-detail__h">主演</h3>
          <div className="media-detail__cast-rail">
            {cast.map((p, i) => {
              const avatar = proxiedCoverUrl(p.avatarUrl);
              const body = (
                <>
                  <span className="media-detail__cast-avatar" aria-hidden>
                    {avatar ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={avatar}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <span className="media-detail__cast-ph">
                        {p.name.slice(0, 1)}
                      </span>
                    )}
                  </span>
                  <span className="media-detail__cast-name">{p.name}</span>
                </>
              );
              return onOpenPerson ? (
                <button
                  key={`${p.id || p.name}-${i}`}
                  type="button"
                  className="media-detail__cast-card"
                  onClick={() => onOpenPerson(p)}
                >
                  {body}
                </button>
              ) : (
                <div
                  key={`${p.id || p.name}-${i}`}
                  className="media-detail__cast-card media-detail__cast-card--static"
                >
                  {body}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {item.overview ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">简介</h3>
          <p className="media-detail__overview allow-select">{item.overview}</p>
        </section>
      ) : enriching ? (
        <p className="media-empty" style={{ marginTop: 8 }}>
          加载详情…
        </p>
      ) : null}

      <button type="button" className="media-detail__cta" onClick={onSearch}>
        <Search size={17} strokeWidth={2.25} aria-hidden />
        在 BT 库搜索
      </button>

      {related.length > 0 && onOpenRelated ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">相似推荐</h3>
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
