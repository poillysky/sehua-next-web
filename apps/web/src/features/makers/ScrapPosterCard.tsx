'use client';

import {
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import {
  SCRAP_POSTER_COVER_OPTS,
  useScrapLocalCover,
} from './useScrapLocalCover';

export function ScrapPosterCard({
  item,
  onClick,
  eager = false,
}: {
  item: ScrapLibraryEmbedItem;
  onClick: () => void;
  /** iOS：Tab transform 容器内 lazy 常不触发加载，首屏建议 eager */
  eager?: boolean;
}) {
  const { src, onError } = useScrapLocalCover({
    posterApi: item.posterApi,
    thumbApi: item.thumbApi,
    coverUrl: item.coverUrl,
    itemId: item.itemId,
    ...SCRAP_POSTER_COVER_OPTS,
  });

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
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt=""
            loading={eager ? 'eager' : 'lazy'}
            decoding="async"
            fetchPriority={eager ? 'high' : 'auto'}
            referrerPolicy="no-referrer"
            onError={onError}
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
