import {
  SEARCH_KEYWORD_LENGTH_MIN,
} from '@/config/search';
import type {
  FilterSize,
  FilterTime,
  MatchMode,
  SortType,
} from '@/types/resource';
import type { FeedSource } from '@/lib/mixedSearch';
import type { SearchSource } from './SourceSwitch';

export type HomeMode = 'landing' | 'results';

export function syncDetailUrl(hash: string | null, source?: FeedSource) {
  try {
    const url = new URL(window.location.href);
    if (hash) {
      url.searchParams.set('detail', hash);
      if (source === 'bitmagnet') url.searchParams.set('ds', 'bitmagnet');
      else url.searchParams.delete('ds');
    } else {
      url.searchParams.delete('detail');
      url.searchParams.delete('ds');
    }
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (
      `${window.location.pathname}${window.location.search}${window.location.hash}` !==
      next
    ) {
      window.history.replaceState(null, '', next);
    }
  } catch {
    /* ignore */
  }
}

export function syncSearchUrl(opts: {
  mode: HomeMode;
  keyword: string;
  browsing: boolean;
  sortType: SortType;
  matchMode: MatchMode;
  filterTime: FilterTime;
  filterSize: FilterSize;
  region?: string | null;
  searchSource?: SearchSource;
}) {
  try {
    const url = new URL(window.location.href);
    const detail = url.searchParams.get('detail');
    const ds = url.searchParams.get('ds');
    url.search = '';
    if (opts.mode === 'landing') {
      // keep empty
    } else if (opts.keyword.length >= SEARCH_KEYWORD_LENGTH_MIN) {
      url.searchParams.set('keyword', opts.keyword);
      url.searchParams.set('sortType', opts.sortType);
      url.searchParams.set('filterTime', opts.filterTime);
      url.searchParams.set('filterSize', opts.filterSize);
      url.searchParams.set('matchMode', opts.matchMode);
      if (opts.region) url.searchParams.set('region', opts.region);
      if (opts.searchSource === 'bitmagnet') {
        url.searchParams.set('src', 'bitmagnet');
      } else {
        url.searchParams.delete('src');
      }
    } else if (opts.browsing) {
      url.searchParams.set('browse', '1');
    }
    if (detail) url.searchParams.set('detail', detail);
    if (ds === 'bitmagnet') url.searchParams.set('ds', 'bitmagnet');
    const next = `${url.pathname}${url.search}${url.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (cur !== next) window.history.replaceState(null, '', next);
  } catch {
    /* ignore */
  }
}
