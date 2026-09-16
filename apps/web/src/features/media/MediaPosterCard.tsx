'use client';

import { useState } from 'react';
import type { MediaCategoryId, MediaItem } from '@/lib/api';
import { proxiedCoverUrl } from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import { MEDIA_CATEGORY_MARK } from './mediaUi';

function typeMark(
  item: MediaItem,
  category?: MediaCategoryId,
): string {
  if (category && MEDIA_CATEGORY_MARK[category]) {
    return MEDIA_CATEGORY_MARK[category];
  }
  return item.mediaType === 'tv' ? '剧' : '影';
}

export function MediaPosterCard({
  item,
  category,
  onClick,
  size = 'md',
}: {
  item: MediaItem;
  category?: MediaCategoryId;
  onClick: () => void;
  size?: 'sm' | 'md' | 'lg';
}) {
  const [gone, setGone] = useState(false);
  const poster = proxiedCoverUrl(item.posterUrl);
  const rating =
    item.rating != null && Number(item.rating) > 0
      ? Number(item.rating).toFixed(1)
      : null;
  const mark = typeMark(item, category);

  return (
    <button
      type="button"
      className={`media-poster media-poster--${size}`}
      onClick={onClick}
    >
      <span className="media-poster__frame">
        <span className="media-poster__ph" aria-hidden>
          {item.title.slice(0, 1)}
        </span>
        {poster && !gone ? (
          <SoftImg
            src={poster}
            loading="lazy"
            onError={() => setGone(true)}
          />
        ) : null}
        <span className="media-poster__type" aria-hidden>
          {mark}
        </span>
        {rating ? (
          <span className="media-poster__score" aria-hidden>
            {rating}
          </span>
        ) : null}
      </span>
      <span className="media-poster__caption">
        <span className="media-poster__title">{item.title}</span>
      </span>
    </button>
  );
}
