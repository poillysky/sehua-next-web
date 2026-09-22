'use client';

import type { Dispatch, SetStateAction } from 'react';
import {
  listScrapLibraryEmbedFacets,
  listScrapLibraryEmbedItems,
  listScrapLibraryEmbedPrefixes,
  searchScrapLibraryEmbed,
  type MakerCatalogSourceId,
  type ScrapLibraryEmbedFacet,
  type ScrapLibraryEmbedItem,
  type ScrapLibraryEmbedPrefix,
} from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import { MAKER_KIND_TABS } from './makersUi';
import type { DrillStack, Stack } from './makersTypes';
import { MAKERS_PAGE_SIZE } from './makersTypes';

export function currentDrill(stack: Stack): DrillStack {
  if (stack.kind === 'detail') return stack.from;
  if (stack.kind === 'hub') return { kind: 'hub' };
  if (stack.kind === 'search') return { kind: 'search' };
  if (stack.kind === 'folderStudio') {
    return { kind: 'folderStudio', studio: stack.studio };
  }
  if (stack.kind === 'folderPrefix') {
    return {
      kind: 'folderPrefix',
      studio: stack.studio,
      prefix: stack.prefix,
    };
  }
  return {
    kind: 'facet',
    facet: stack.facet,
    value: stack.value,
    fromDetail: stack.fromDetail,
  };
}

export function openMakerItem(
  item: ScrapLibraryEmbedItem,
  opts: {
    hubTab: MakerCatalogSourceId;
    stack: Stack;
    setHubTab: Dispatch<SetStateAction<MakerCatalogSourceId>>;
    setStack: Dispatch<SetStateAction<Stack>>;
  },
) {
  const rid = String(item.region || '').trim();
  if (
    rid &&
    MAKER_KIND_TABS.some((t) => t.id === rid) &&
    rid !== opts.hubTab
  ) {
    opts.setHubTab(rid as MakerCatalogSourceId);
  }
  opts.setStack({ kind: 'detail', item, from: currentDrill(opts.stack) });
}

export function openMakerFacetFromDetail(
  facet: 'genre' | 'tag' | 'actress',
  value: string,
  opts: {
    stack: Stack;
    setStack: Dispatch<SetStateAction<Stack>>;
    posterApi?: string;
    count?: number;
  },
) {
  const name = String(value || '').trim();
  if (!name) return;
  const fromDetail = opts.stack.kind === 'detail' ? opts.stack.item : undefined;
  opts.setStack({
    kind: 'facet',
    facet,
    value: name,
    fromDetail,
    posterApi: opts.posterApi,
    count: opts.count,
  });
}

export function openMakerStudioFromDetail(
  value: string,
  setStack: Dispatch<SetStateAction<Stack>>,
) {
  const name = String(value || '').trim();
  if (!name) return;
  setStack({ kind: 'folderStudio', studio: name });
}

export function clearMakerSearchResults(opts: {
  setSearchHits: Dispatch<SetStateAction<ScrapLibraryEmbedItem[]>>;
  setSearchStudios: Dispatch<SetStateAction<ScrapLibraryEmbedFacet[]>>;
  setSearchPrefixes: Dispatch<SetStateAction<ScrapLibraryEmbedPrefix[]>>;
  setSearchDone: Dispatch<SetStateAction<boolean>>;
}) {
  opts.setSearchHits([]);
  opts.setSearchStudios([]);
  opts.setSearchPrefixes([]);
  opts.setSearchDone(false);
}

export function openMakerSearch(opts: {
  setSearchDraft: Dispatch<SetStateAction<string>>;
  setSearchHits: Dispatch<SetStateAction<ScrapLibraryEmbedItem[]>>;
  setSearchStudios: Dispatch<SetStateAction<ScrapLibraryEmbedFacet[]>>;
  setSearchPrefixes: Dispatch<SetStateAction<ScrapLibraryEmbedPrefix[]>>;
  setSearchDone: Dispatch<SetStateAction<boolean>>;
  setStack: Dispatch<SetStateAction<Stack>>;
}) {
  opts.setSearchDraft('');
  clearMakerSearchResults(opts);
  opts.setStack({ kind: 'search' });
}

export async function runMakerSemanticSearch(
  raw: string,
  opts: {
    hubTab: MakerCatalogSourceId;
    setSearchLoading: Dispatch<SetStateAction<boolean>>;
    setSearchDone: Dispatch<SetStateAction<boolean>>;
    setMsg: Dispatch<SetStateAction<string>>;
    setSearchHits: Dispatch<SetStateAction<ScrapLibraryEmbedItem[]>>;
    setSearchPrefixes: Dispatch<SetStateAction<ScrapLibraryEmbedPrefix[]>>;
    setSearchStudios: Dispatch<SetStateAction<ScrapLibraryEmbedFacet[]>>;
  },
) {
  const q = raw.trim();
  if (q.length < SEARCH_KEYWORD_LENGTH_MIN) {
    opts.setMsg(`请输入至少 ${SEARCH_KEYWORD_LENGTH_MIN} 个字`);
    return;
  }
  opts.setSearchLoading(true);
  opts.setSearchDone(false);
  opts.setMsg('');
  try {
    const [page, prefixes, studioPage] = await Promise.all([
      listScrapLibraryEmbedItems({
        region: opts.hubTab,
        q,
        offset: 0,
        limit: MAKERS_PAGE_SIZE,
      }),
      listScrapLibraryEmbedPrefixes(opts.hubTab, { q, limit: 24 }).catch(
        () => [] as ScrapLibraryEmbedPrefix[],
      ),
      listScrapLibraryEmbedFacets({
        region: opts.hubTab,
        kind: 'studio',
        q,
        sort: 'count',
        order: 'desc',
        limit: 24,
      }).catch(() => ({ facets: [] as ScrapLibraryEmbedFacet[], total: 0 })),
    ]);
    let hits = page.items || [];
    if (hits.length < 8) {
      try {
        const semantic = await searchScrapLibraryEmbed({
          query: q,
          limit: 24,
          region: opts.hubTab,
        });
        const seen = new Set(
          hits.map((h) => String(h.itemId || h.code || '')),
        );
        for (const h of semantic) {
          const key = String(h.itemId || h.code || '');
          if (!key || seen.has(key)) continue;
          seen.add(key);
          hits.push(h);
        }
      } catch {
        /* 语义失败仍展示关键字结果 */
      }
    }
    opts.setSearchHits(hits);
    opts.setSearchPrefixes(prefixes || []);
    opts.setSearchStudios(studioPage.facets || []);
    opts.setSearchDone(true);
  } catch (e) {
    opts.setSearchHits([]);
    opts.setSearchPrefixes([]);
    opts.setSearchStudios([]);
    opts.setSearchDone(true);
    opts.setMsg(e instanceof Error ? e.message : '搜索失败');
  } finally {
    opts.setSearchLoading(false);
  }
}
