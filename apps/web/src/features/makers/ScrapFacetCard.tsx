'use client';

import { SoftImg } from '@/components/SoftImg';
import { useScrapLocalCover, SCRAP_POSTER_COVER_OPTS } from './useScrapLocalCover';

export function ScrapFacetCard({
  title,
  count,
  posterApi,
  coverUrl,
  itemId,
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  coverUrl?: string;
  itemId?: string;
  onClick: () => void;
}) {
  const { src, onError } = useScrapLocalCover({
    posterApi,
    coverUrl,
    itemId,
    ...SCRAP_POSTER_COVER_OPTS,
  });

  return (
    <button
      type="button"
      className="media-poster makers-poster makers-facet media-poster--sm"
      onClick={onClick}
    >
      <span className="media-poster__frame makers-poster__frame makers-facet__frame">
        <span className="media-poster__ph" aria-hidden>
          {(title || '?').slice(0, 1)}
        </span>
        {src ? (
          <SoftImg
            src={src}
            loading="eager"
            fetchPriority="high"
            onError={onError}
          />
        ) : null}
      </span>
      <span className="media-poster__caption makers-poster__caption">
        <span className="makers-poster__code allow-select">{title}</span>
        <span className="makers-poster__title">{count} 项</span>
      </span>
    </button>
  );
}
