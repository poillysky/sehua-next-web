'use client';

import { useState } from 'react';
import type { MediaItem } from '@/lib/api';
import { proxiedCoverUrl } from '@/lib/api';

export function MediaPosterCard({
  item,
  rank,
  onClick,
  size = 'md',
}: {
  item: MediaItem;
  rank?: number;
  onClick: () => void;
  size?: 'sm' | 'md' | 'lg';
}) {
  const [gone, setGone] = useState(false);
  const poster = proxiedCoverUrl(item.posterUrl);
  const rating =
    item.rating != null && Number(item.rating) > 0
      ? Number(item.rating).toFixed(1)
      : null;

  return (
    <button
      type="button"
      className={`media-poster media-poster--${size}`}
      onClick={onClick}
    >
      <span className="media-poster__frame">
        {poster && !gone ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={poster}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setGone(true)}
          />
        ) : (
          <span className="media-poster__ph">{item.title.slice(0, 1)}</span>
        )}
        {rank != null && rank > 0 ? (
          <span
            className={
              rank <= 3
                ? `media-poster__rank media-poster__rank--${rank}`
                : 'media-poster__rank'
            }
            aria-hidden
          >
            {rank}
          </span>
        ) : null}
        {rating ? (
          <span className="media-poster__score" aria-hidden>
            {rating}
          </span>
        ) : null}
      </span>
      <span className="media-poster__caption">
        <span className="media-poster__title">{item.title}</span>
        {item.year ? (
          <span className="media-poster__year">{item.year}</span>
        ) : null}
      </span>
    </button>
  );
}
