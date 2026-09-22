import type {
  MediaCategoryId,
  MediaItem,
  MediaSourceId,
  P115MakerRegionSource,
} from '@/lib/api';
import { P115_MAKER_REGION_SOURCES } from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import type { TabRoute } from '@/shell';
import { clearSaveSource, writeSaveSource } from '@/lib/p115Source';

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
      { category: 'movie', chart: 'new', title: '新片' },
      { category: 'movie', chart: 'hot', title: '热门电影' },
      { category: 'tv', chart: 'hot', title: '热门剧集' },
      { category: 'movie', chart: 'cn', title: '华语电影' },
      { category: 'movie', chart: 'western', title: '欧美电影' },
      { category: 'tv', chart: 'jp', title: '日剧' },
      { category: 'tv', chart: 'kr', title: '韩剧' },
      { category: 'anime', chart: 'hot', title: '日本动画' },
      { category: 'variety', chart: 'hot', title: '综艺' },
      { category: 'movie', chart: 'top250', title: '豆瓣 Top250' },
    ];
  }
  if (source === 'bangumi') {
    return [
      { category: 'anime', chart: 'rank', title: '动画排名' },
      { category: 'anime', chart: 'heat', title: '热门动画' },
      { category: 'anime', chart: 'score', title: '高分动画' },
      { category: 'anime', chart: 'calendar', title: '本季放送' },
      { category: 'tv', chart: 'real', title: '三次元' },
    ];
  }
  if (source === 'anilist') {
    return [
      { category: 'anime', chart: 'trending', title: '趋势动画' },
      { category: 'anime', chart: 'popular', title: '热门动画' },
      { category: 'anime', chart: 'top_rated', title: '高分动画' },
      { category: 'anime', chart: 'airing', title: '放送中' },
      { category: 'anime', chart: 'upcoming', title: '即将上映' },
      { category: 'movie', chart: 'movies', title: '剧场版' },
    ];
  }
  return [
    { category: 'movie', chart: 'upcoming', title: '即将上映' },
    { category: 'movie', chart: 'now_playing', title: '正在热映' },
    { category: 'movie', chart: 'popular', title: '热门电影' },
    { category: 'tv', chart: 'popular', title: '热门剧集' },
    { category: 'movie', chart: 'trending', title: '本周趋势·电影' },
    { category: 'tv', chart: 'trending', title: '本周趋势·剧集' },
    { category: 'tv', chart: 'on_the_air', title: '正在播出' },
    { category: 'anime', chart: 'popular', title: '热门动漫' },
    { category: 'variety', chart: 'popular', title: '热门综艺' },
    { category: 'movie', chart: 'top_rated', title: '高分电影' },
    { category: 'tv', chart: 'top_rated', title: '高分剧集' },
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

/** 是否适合进 BT 搜索：中文（汉字）或英文（拉丁），剔除日文假名 / 韩文等。 */
function isZhEnSearchable(s: string): boolean {
  if (/[\u3040-\u30ff\uac00-\ud7af]/.test(s)) return false;
  if (/[\u4e00-\u9fff]/.test(s)) return true;
  if (/[\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u1780-\u17FF\u0400-\u04FF]/.test(s)) {
    return false;
  }
  return /[A-Za-z]/.test(s);
}

/** 影视跳 BT：主名保留；原名/别名仅中英，用顿号拼接；后端按词分别搜再 OR 合并。 */
export function buildMediaSearchTerms(
  item: Pick<MediaItem, 'title' | 'originalTitle' | 'aka'>,
  opts?: { maxTerms?: number; maxLen?: number },
): string[] {
  const maxTerms = opts?.maxTerms ?? 2;
  const maxLen = opts?.maxLen ?? 100;
  const seen = new Set<string>();
  const parts: string[] = [];
  const candidates = [item.title, item.originalTitle, ...(item.aka || [])];
  for (let i = 0; i < candidates.length; i++) {
    let s = String(candidates[i] || '').trim();
    if (!s) continue;
    // 过长别名截断，避免整串超限
    if (s.length > 60) s = s.slice(0, 60).trim();
    if (s.length < SEARCH_KEYWORD_LENGTH_MIN) continue;
    // 主名恒保留；originalTitle / aka 仅中英
    if (i > 0 && !isZhEnSearchable(s)) continue;
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

/** 盘搜 / CloudSaver：优先中文词，其次主名。 */
export function pickCloudSearchKeyword(
  item: Pick<MediaItem, 'title' | 'originalTitle' | 'aka'>,
): string {
  const terms = buildMediaSearchTerms(item, { maxTerms: 4, maxLen: 80 });
  const zh = terms.find((t) => /[\u4e00-\u9fff]/.test(t));
  return (zh || terms[0] || String(item.title || '').trim()).trim();
}

/** 影视 / 片商跳转仓库：双库同搜 */
export function openHomeSearch(
  names: string[] | string,
  scrollToTab?: (tab: TabRoute) => void,
  opts?: {
    source?: 'sehua' | 'bitmagnet';
    /** 115 转存目录：电影 / 电视剧 / 片商六区 */
    p115Source?: 'movie' | 'tv' | P115MakerRegionSource;
  },
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
    if (
      opts?.p115Source === 'movie' ||
      opts?.p115Source === 'tv' ||
      (opts?.p115Source &&
        (P115_MAKER_REGION_SOURCES as string[]).includes(opts.p115Source))
    ) {
      writeSaveSource(opts.p115Source);
    } else {
      // 非片商/影视入口：清掉上次片商分区，避免误入六区
      clearSaveSource();
    }
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
  const p115Source = item.mediaType === 'tv' ? 'tv' : 'movie';
  return openHomeSearch(
    [item.title, item.originalTitle || '', ...(item.aka || [])],
    scrollToTab,
    { p115Source, source: 'bitmagnet' },
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
  if (source === 'bangumi') {
    if (category === 'tv') {
      return [{ id: 'real', label: '三次元' }];
    }
    return [
      { id: 'rank', label: '排名' },
      { id: 'heat', label: '热门' },
      { id: 'score', label: '高分' },
      { id: 'calendar', label: '放送表' },
    ];
  }
  if (source === 'anilist') {
    if (category === 'movie') {
      return [{ id: 'movies', label: '剧场版' }];
    }
    return [
      { id: 'trending', label: '趋势' },
      { id: 'popular', label: '热门' },
      { id: 'top_rated', label: '高分' },
      { id: 'airing', label: '放送中' },
      { id: 'upcoming', label: '即将上映' },
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
