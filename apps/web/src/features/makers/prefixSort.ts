import type { ScrapLibraryEmbedPrefix } from '@/lib/api';
import type { MakerPrefixSortId } from './makersUi';

export function prefixCodeRank(code: string): number {
  const m = String(code || '')
    .trim()
    .toUpperCase()
    .match(/(\d+)\s*$/);
  return m ? Number.parseInt(m[1], 10) : 0;
}

export function sortPrefixes(
  rows: ScrapLibraryEmbedPrefix[],
  sortId: MakerPrefixSortId,
  order: 'asc' | 'desc',
): ScrapLibraryEmbedPrefix[] {
  const mul = order === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sortId === 'count') {
      return (
        (a.count - b.count) * mul || a.prefix.localeCompare(b.prefix, 'zh')
      );
    }
    if (sortId === 'code') {
      const la = Number(a.lineRank ?? 99);
      const lb = Number(b.lineRank ?? 99);
      if (la !== lb) return la - lb;
      const ya = Number(a.latestYear || 0);
      const yb = Number(b.latestYear || 0);
      if (ya !== yb) return (ya - yb) * mul;
      const ta = Date.parse(String(a.latestAt || '')) || 0;
      const tb = Date.parse(String(b.latestAt || '')) || 0;
      if (ta !== tb) return (ta - tb) * mul;
      const ra = prefixCodeRank(a.latestCode || '');
      const rb = prefixCodeRank(b.latestCode || '');
      if (ra !== rb) return (ra - rb) * mul;
      return a.prefix.localeCompare(b.prefix, 'zh');
    }
    return a.prefix.localeCompare(b.prefix, 'zh') * mul;
  });
}
