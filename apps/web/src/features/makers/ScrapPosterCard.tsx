'use client';

import { useEffect, useState } from 'react';
import {
  ensureScrapLibraryPoster,
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
  SCRAP_LIST_THUMB_W,
} from '@/lib/api';

const COVER_OPTS = { w: SCRAP_LIST_THUMB_W, rp: true as const };

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
  // 本地 poster/thumb 优先；失败再回退 NFO 外链 coverUrl
  const local = scrapLibraryCoverUrl(
    {
      posterApi: item.posterApi,
      thumbApi: item.thumbApi,
      coverUrl: '',
    },
    COVER_OPTS,
  );
  const remote = scrapLibraryCoverUrl(
    { coverUrl: item.coverUrl },
    COVER_OPTS,
  );
  const primary = local || remote;
  const [src, setSrc] = useState(primary);

  useEffect(() => {
    setSrc(primary);
  }, [primary]);

  // 仅有远程时：触发服务端把图落到番号目录（下次即可走本地）
  useEffect(() => {
    const id = String(item.itemId || '').trim();
    if (!id || local || !item.coverUrl) return;
    void ensureScrapLibraryPoster(id);
  }, [item.itemId, item.coverUrl, local]);

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
            onError={() => {
              if (remote && src !== remote) {
                const id = String(item.itemId || '').trim();
                if (id) void ensureScrapLibraryPoster(id);
                setSrc(remote);
                return;
              }
              setSrc('');
            }}
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
