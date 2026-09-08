'use client';

import { useState } from 'react';
import {
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
  SCRAP_LIST_THUMB_W,
} from '@/lib/api';

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
  const [gone, setGone] = useState(false);
  // poster 已是竖图；rp=0 避免列表默认右裁
  const poster = scrapLibraryCoverUrl(item, {
    w: SCRAP_LIST_THUMB_W,
    // 横图右裁竖幅；竖 poster 服务端 no-op
    rp: true,
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
        {poster && !gone ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={poster}
            alt=""
            loading={eager ? 'eager' : 'lazy'}
            decoding="async"
            fetchPriority={eager ? 'high' : 'auto'}
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
