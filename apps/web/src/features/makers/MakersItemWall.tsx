'use client';

import type { ScrapLibraryEmbedItem } from '@/lib/api';
import { isCensoredRightCropRegion } from './makersUi';
import { ScrapPosterCard } from './ScrapPosterCard';

export function MakersItemWall({
  items,
  empty,
  loading,
  region,
  onOpenItem,
}: {
  items: ScrapLibraryEmbedItem[];
  empty: string;
  loading?: boolean;
  region: string;
  onOpenItem: (item: ScrapLibraryEmbedItem) => void;
}) {
  return (
    <>
      {loading ? (
        <div className="media-wall media-wall--skel makers-hub__wall" aria-hidden>
          {Array.from({ length: 9 }).map((_, i) => (
            <span key={i} className="makers-poster-skel" />
          ))}
        </div>
      ) : null}
      {!loading && items.length === 0 ? (
        <p className="media-empty makers-hub__empty allow-select">{empty}</p>
      ) : null}
      {!loading && items.length > 0 ? (
        <div className="media-wall makers-hub__wall">
          {items.map((item, i) => (
            <ScrapPosterCard
              key={String(item.itemId || item.code)}
              item={item}
              eager={i < 18}
              rightCrop={isCensoredRightCropRegion(region)}
              onClick={() => onOpenItem(item)}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}
