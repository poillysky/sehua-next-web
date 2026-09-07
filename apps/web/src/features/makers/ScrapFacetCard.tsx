'use client';

import { useState } from 'react';
import { scrapLibraryCoverUrl } from '@/lib/api';

export function ScrapFacetCard({
  title,
  count,
  posterApi,
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  onClick: () => void;
}) {
  const [gone, setGone] = useState(false);
  const poster = scrapLibraryCoverUrl({ posterApi });

  return (
    <button
      type="button"
      className="media-poster makers-poster makers-facet media-poster--sm"
      onClick={onClick}
    >
      <span className="media-poster__frame makers-poster__frame makers-facet__frame">
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
            {(title || '?').slice(0, 1)}
          </span>
        )}
      </span>
      <span className="media-poster__caption makers-poster__caption">
        <span className="makers-poster__code allow-select">{title}</span>
        <span className="makers-poster__title">{count} 项</span>
      </span>
    </button>
  );
}
