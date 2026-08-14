import type { MagnetHit } from '@/lib/api';
import type { ResourceItem } from '@/types/resource';

export type FeedSource = 'sehua' | 'bitmagnet';

export type FeedEntry =
  | { source: 'sehua'; id: string; sortAt: number; item: ResourceItem }
  | { source: 'bitmagnet'; id: string; sortAt: number; item: MagnetHit };

export function magnetHash(item: MagnetHit): string {
  return (item.hash || item.infoHash || item.path || '').toLowerCase();
}

function magnetCreated(item: MagnetHit): number {
  if (item.created_at) return item.created_at;
  if (item.createdAt) {
    const n = Date.parse(item.createdAt);
    return Number.isFinite(n) ? Math.floor(n / 1000) : 0;
  }
  return 0;
}

export function toSehualEntries(items: ResourceItem[]): FeedEntry[] {
  return items.map((item) => ({
    source: 'sehua' as const,
    id: `sh:${item.hash}`,
    sortAt: Number(item.created_at) || 0,
    item,
  }));
}

export function toMagnetEntries(items: MagnetHit[]): FeedEntry[] {
  return items.map((item) => {
    const hash = magnetHash(item);
    return {
      source: 'bitmagnet' as const,
      id: `bm:${hash}`,
      sortAt: magnetCreated(item),
      item,
    };
  });
}

/** 色花堂整段落在上方，组内按收录时间倒序；Bitmagnet 同理接在后面 */
export function mergeFeed(
  sehua: ResourceItem[],
  magnets: MagnetHit[],
): FeedEntry[] {
  const byTime = (a: FeedEntry, b: FeedEntry) => {
    if (b.sortAt !== a.sortAt) return b.sortAt - a.sortAt;
    return a.id.localeCompare(b.id);
  };
  return [
    ...toSehualEntries(sehua).sort(byTime),
    ...toMagnetEntries(magnets).sort(byTime),
  ];
}
