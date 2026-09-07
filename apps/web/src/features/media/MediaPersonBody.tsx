'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  fetchMediaPersonWorks,
  proxiedCoverUrl,
  type MediaCastPerson,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { MediaPosterCard } from './MediaPosterCard';

function yearOf(item: MediaItem): string {
  const y = String(item.year || '').trim();
  return /^\d{4}$/.test(y) ? y : '';
}

function sortByYearDesc(items: MediaItem[]): MediaItem[] {
  return [...items].sort((a, b) => {
    const ya = yearOf(a) ? Number(yearOf(a)) : -1;
    const yb = yearOf(b) ? Number(yearOf(b)) : -1;
    if (yb !== ya) return yb - ya;
    const ra = Number(a.rating || 0);
    const rb = Number(b.rating || 0);
    return rb - ra;
  });
}

function groupByYear(items: MediaItem[]): Array<{ year: string; items: MediaItem[] }> {
  const sorted = sortByYearDesc(items);
  const map = new Map<string, MediaItem[]>();
  for (const it of sorted) {
    const y = yearOf(it) || '未知年份';
    const bucket = map.get(y);
    if (bucket) bucket.push(it);
    else map.set(y, [it]);
  }
  return Array.from(map.entries()).map(([year, rows]) => ({ year, items: rows }));
}

export function MediaPersonBody({
  source,
  person,
  onOpen,
}: {
  source: MediaSourceId;
  person: MediaCastPerson;
  onOpen: (item: MediaItem) => void;
}) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [displayName, setDisplayName] = useState(person.name);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [avatarGone, setAvatarGone] = useState(false);
  const avatar = proxiedCoverUrl(person.avatarUrl);

  useEffect(() => {
    setAvatarGone(false);
  }, [person.avatarUrl, person.id, person.name]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr('');
    void (async () => {
      try {
        const data = await fetchMediaPersonWorks({
          source,
          q: person.name,
          personId: person.id || undefined,
        });
        if (cancelled) return;
        setItems(sortByYearDesc(data.items || []));
        if (data.name) setDisplayName(data.name);
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
  }, [source, person.id, person.name]);

  const groups = useMemo(() => groupByYear(items), [items]);
  const yearSpan = useMemo(() => {
    const years = items.map(yearOf).filter(Boolean).map(Number);
    if (years.length === 0) return '';
    const max = Math.max(...years);
    const min = Math.min(...years);
    return max === min ? `${max}` : `${min}–${max}`;
  }, [items]);

  return (
    <div className="media-person">
      <header className="media-person__hero">
        <span className="media-person__avatar" aria-hidden>
          {avatar && !avatarGone ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatar}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              onError={() => setAvatarGone(true)}
            />
          ) : (
            <span className="media-person__avatar-ph">
              {displayName.slice(0, 1)}
            </span>
          )}
        </span>
        <div className="media-person__meta">
          <h2 className="media-person__name allow-select">{displayName}</h2>
          <div className="media-person__chips">
            {loading ? (
              <span className="media-person__chip media-person__chip--mute">加载中</span>
            ) : err ? (
              <span className="media-person__chip media-person__chip--warn">加载失败</span>
            ) : items.length > 0 ? (
              <>
                <span className="media-person__chip">{items.length} 部</span>
                {yearSpan ? (
                  <span className="media-person__chip">{yearSpan}</span>
                ) : null}
                <span className="media-person__chip media-person__chip--mute">按年份</span>
              </>
            ) : (
              <span className="media-person__chip media-person__chip--mute">暂无作品</span>
            )}
          </div>
        </div>
      </header>

      {loading ? (
        <div className="media-person__skel" aria-hidden>
          <div className="media-person__year-head media-person__year-head--skel">
            <span className="media-person__skel-bar" />
          </div>
          <div className="media-wall media-wall--skel">
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className="media-poster-skel media-poster-skel--wall" />
            ))}
          </div>
        </div>
      ) : null}

      {!loading && err ? (
        <p className="media-empty allow-select">{err}</p>
      ) : null}

      {!loading && !err && items.length === 0 ? (
        <p className="media-empty">暂无作品</p>
      ) : null}

      {!loading && !err
        ? groups.map((g) => (
            <section key={g.year} className="media-person__year">
              <div className="media-person__year-head">
                <h3 className="media-person__year-title">{g.year}</h3>
                <span className="media-person__year-count">{g.items.length} 部</span>
              </div>
              <div className="media-wall media-person__wall">
                {g.items.map((it) => (
                  <MediaPosterCard
                    key={`${it.source}-${it.id}`}
                    item={it}
                    category={it.mediaType === 'tv' ? 'tv' : 'movie'}
                    size="md"
                    onClick={() => onOpen(it)}
                  />
                ))}
              </div>
            </section>
          ))
        : null}
    </div>
  );
}
