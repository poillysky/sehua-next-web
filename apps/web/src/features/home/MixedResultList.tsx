'use client';

import type { FeedEntry } from '@/lib/mixedSearch';
import { ResourceCard } from '@/features/home/ResourceCard';
import { MagnetCard } from '@/features/magnet/BitmagnetResultList';

/** 双库混合结果列表 */
export function MixedResultList({
  entries,
  keywords = [],
  cropRegion,
  onOpenSehual,
  onOpenMagnet,
}: {
  entries: FeedEntry[];
  keywords?: string[];
  cropRegion?: string;
  onOpenSehual: (hash: string) => void;
  onOpenMagnet: (hash: string) => void;
}) {
  return (
    <div className="bm-result-list">
      {entries.map((entry) =>
        entry.source === 'sehua' ? (
          <ResourceCard
            key={entry.id}
            item={entry.item}
            keywords={keywords}
            cropRegion={cropRegion}
            badge="色花堂"
            onOpen={onOpenSehual}
          />
        ) : (
          <MagnetCard
            key={entry.id}
            item={entry.item}
            keywords={keywords}
            badge="Bitmagnet"
            onOpen={onOpenMagnet}
          />
        ),
      )}
    </div>
  );
}
