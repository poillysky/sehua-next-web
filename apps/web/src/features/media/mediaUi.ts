import type { MediaCategoryId, MediaItem, MediaSourceId } from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import type { TabRoute } from '@/shell';

export const MEDIA_CATEGORY_MARK: Record<MediaCategoryId, string> = {
  movie: '影',
  tv: '剧',
  anime: '漫',
  variety: '综',
};

export type MediaHubShelf = {
  category: MediaCategoryId;
  chart: string;
  title: string;
};

/** MoviePilot 式发现页货架（按数据源） */
export function hubShelvesFor(source: MediaSourceId): MediaHubShelf[] {
  if (source === 'douban') {
    return [
      { category: 'movie', chart: 'hot', title: '热门电影' },
      { category: 'movie', chart: 'top250', title: '豆瓣 Top250' },
      { category: 'movie', chart: 'new', title: '新片' },
      { category: 'movie', chart: 'cn', title: '华语电影' },
      { category: 'movie', chart: 'western', title: '欧美电影' },
      { category: 'tv', chart: 'hot', title: '热门剧集' },
      { category: 'tv', chart: 'jp', title: '日剧' },
      { category: 'tv', chart: 'kr', title: '韩剧' },
      { category: 'anime', chart: 'hot', title: '日本动画' },
      { category: 'variety', chart: 'hot', title: '综艺' },
    ];
  }
  return [
    { category: 'movie', chart: 'trending', title: '本周趋势·电影' },
    { category: 'movie', chart: 'now_playing', title: '正在热映' },
    { category: 'movie', chart: 'upcoming', title: '即将上映' },
    { category: 'movie', chart: 'popular', title: '热门电影' },
    { category: 'movie', chart: 'top_rated', title: '高分电影' },
    { category: 'tv', chart: 'trending', title: '本周趋势·剧集' },
    { category: 'tv', chart: 'on_the_air', title: '正在播出' },
    { category: 'tv', chart: 'popular', title: '热门剧集' },
    { category: 'tv', chart: 'top_rated', title: '高分剧集' },
    { category: 'anime', chart: 'popular', title: '热门动漫' },
    { category: 'variety', chart: 'popular', title: '热门综艺' },
  ];
}

export function mediaCategoryLabel(id: MediaCategoryId): string {
  const map: Record<MediaCategoryId, string> = {
    movie: '电影',
    tv: '电视剧',
    anime: '动漫',
    variety: '综艺',
  };
  return map[id] || id;
}

/** 影视跳 BT：中文 / 英文原名 / 别名全部保留，用顿号拼接；后端按词分别搜再 OR 合并。 */
export function buildMediaSearchTerms(
  item: Pick<MediaItem, 'title' | 'originalTitle' | 'aka'>,
  opts?: { maxTerms?: number; maxLen?: number },
): string[] {
  const maxTerms = opts?.maxTerms ?? 6;
  const maxLen = opts?.maxLen ?? 100;
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const raw of [item.title, item.originalTitle, ...(item.aka || [])]) {
    let s = String(raw || '').trim();
    if (!s) continue;
    // 过长别名截断，避免整串超限
    if (s.length > 60) s = s.slice(0, 60).trim();
    if (s.length < SEARCH_KEYWORD_LENGTH_MIN) continue;
    const key = s.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(s);
    if (parts.length >= maxTerms) break;
  }
  while (parts.length > 1 && parts.join('，').length > maxLen) {
    parts.pop();
  }
  return parts;
}

export function buildMediaSearchQuery(
  item: Pick<MediaItem, 'title' | 'originalTitle' | 'aka'>,
): string {
  return buildMediaSearchTerms(item).join('，');
}

/** 影视跳转仓库：默认进 Bitmagnet（BT 库） */
export function openHomeSearch(
  names: string[] | string,
  scrollToTab?: (tab: TabRoute) => void,
  opts?: { source?: 'sehua' | 'bitmagnet' },
): boolean {
  const list = Array.isArray(names) ? names : [names];
  const q = buildMediaSearchQuery({
    title: list[0] || '',
    originalTitle: list[1] || '',
    aka: list.slice(2),
  });
  if (q.trim().length < SEARCH_KEYWORD_LENGTH_MIN) return false;
  const source = opts?.source ?? 'bitmagnet';
  try {
    sessionStorage.setItem('nextweb:home-search', q.trim());
    sessionStorage.setItem('nextweb:home-search-source', source);
    sessionStorage.removeItem('nextweb:home-prefix-region');
    window.dispatchEvent(new Event('nextweb:home-search'));
  } catch {
    return false;
  }
  scrollToTab?.('/');
  return true;
}

export function openHomeSearchFromItem(
  item: MediaItem,
  scrollToTab?: (tab: TabRoute) => void,
): boolean {
  return openHomeSearch(
    [item.title, item.originalTitle || '', ...(item.aka || [])],
    scrollToTab,
  );
}

export function chartsForSource(
  source: MediaSourceId,
  category: MediaCategoryId,
): Array<{ id: string; label: string }> {
  if (source === 'douban') {
    if (category === 'movie') {
      return [
        { id: 'hot', label: '热门' },
        { id: 'top250', label: 'Top250' },
        { id: 'new', label: '新片' },
        { id: 'cn', label: '华语' },
        { id: 'western', label: '欧美' },
      ];
    }
    if (category === 'tv') {
      return [
        { id: 'hot', label: '热门' },
        { id: 'new', label: '国产剧' },
        { id: 'jp', label: '日剧' },
        { id: 'kr', label: '韩剧' },
      ];
    }
    return [
      { id: 'hot', label: '热门' },
      { id: 'new', label: '新剧/新片' },
    ];
  }
  // TMDB
  if (category === 'movie') {
    return [
      { id: 'trending', label: '本周趋势' },
      { id: 'now_playing', label: '正在热映' },
      { id: 'upcoming', label: '即将上映' },
      { id: 'popular', label: '热门' },
      { id: 'top_rated', label: '高分' },
    ];
  }
  if (category === 'tv') {
    return [
      { id: 'trending', label: '本周趋势' },
      { id: 'on_the_air', label: '播出中' },
      { id: 'popular', label: '热门' },
      { id: 'top_rated', label: '高分' },
    ];
  }
  return [
    { id: 'popular', label: '热门' },
    { id: 'top_rated', label: '高分' },
  ];
}
