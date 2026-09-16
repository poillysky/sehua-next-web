'use client';

import {
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import {
  SCRAP_POSTER_COVER_OPTS,
  useScrapLocalCover,
} from './useScrapLocalCover';

export function ScrapPosterCard({
  item,
  onClick,
  eager = true,
}: {
  item: ScrapLibraryEmbedItem;
  onClick: () => void;
  /** iOS：Tab/Push transform 容器内 lazy 常不触发；默认 eager */
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
  const badges = (() => {
    const out: string[] = [];
    if (item.cnsub) out.push('中字');
    for (const b of item.badges || []) {
      const t = String(b || '').trim();
      if (!t) continue;
      if (t === '中字' || t === '字幕' || /^cnsub$/i.test(t)) continue;
      if (!out.includes(t)) out.push(t);
    }
    if (item.definition && !out.includes(item.definition)) {
      out.unshift(item.definition);
    }
    return out.slice(0, 2);
  })();

  return (
    <button
      type="button"
      className="media-poster makers-poster media-poster--sm"
      onClick={onClick}
    >
      <span className="media-poster__frame makers-poster__frame">
        <span className="media-poster__ph" aria-hidden>
          {(code || title || '?').slice(0, 1)}
        </span>
        {src ? (
          <SoftImg
            src={src}
            loading={eager ? 'eager' : 'lazy'}
            fetchPriority={eager ? 'high' : 'auto'}
            onError={onError}
          />
        ) : null}
        {badges.length > 0 ? (
          <span className="makers-poster__badges" aria-hidden>
            {badges.map((b) => (
              <span key={b} className="makers-poster__badge">
                {b}
              </span>
            ))}
          </span>
        ) : null}
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
