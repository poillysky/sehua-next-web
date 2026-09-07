'use client';

import { useState } from 'react';
import {
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
} from '@/lib/api';

export function ScrapPosterCard({
  item,
  onClick,
}: {
  item: ScrapLibraryEmbedItem;
  onClick: () => void;
}) {
  const [gone, setGone] = useState(false);
  const poster = scrapLibraryCoverUrl(item);
  const code = String(item.code || '').trim();
  const title = String(item.title || '').trim();
  const displayTitle = title
    .replace(new RegExp(`^${code}\\s*`, 'i'), '')
    .trim();

  return (
    <button
      type="button"
      className="media-poster makers-poster media-poster--sm"
      onClick={onClick}
    >
      <span className="media-poster__frame makers-poster__frame">
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
          <span className="media-poster__ph">
            {(code || title || '?').slice(0, 1)}
          </span>
        )}
      </span>
      <span className="media-poster__caption makers-poster__caption">
        <span className="makers-poster__code allow-select">
          {code || '—'}
        </span>
        {displayTitle ? (
          <span className="makers-poster__title">{displayTitle}</span>
        ) : null}
      </span>
    </button>
  );
}
