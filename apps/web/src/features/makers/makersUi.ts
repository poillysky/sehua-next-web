import type { MakerCatalogSourceId } from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import type { TabRoute } from '@/shell';
import { openHomeSearch } from '@/features/media/mediaUi';
import { writeP115AttachSubs } from '@/lib/p115AttachSubs';

/** 七区顶栏（库 / 分区） */
export const MAKER_KIND_TABS: Array<{
  id: MakerCatalogSourceId;
  label: string;
}> = [
  { id: 'japan_censored', label: '有码' },
  { id: 'japan_uncensored', label: '无码' },
  { id: 'japan_amateur', label: '素人' },
  { id: 'japan_gravure', label: '写真' },
  { id: 'fc2', label: 'FC2' },
  { id: 'china', label: '国产' },
  { id: 'western', label: '欧美' },
];

/** Emby 库内二级菜单 */
export type MakerLibraryView =
  | 'movies'
  | 'recommended'
  | 'genres'
  | 'tags'
  | 'favorites'
  | 'folders';

export const MAKER_LIBRARY_VIEWS: Array<{
  id: MakerLibraryView;
  label: string;
}> = [
  { id: 'recommended', label: '推荐' },
  { id: 'movies', label: '影片' },
  { id: 'genres', label: '标签' },
  { id: 'tags', label: '女优' },
  { id: 'favorites', label: '收藏' },
  { id: 'folders', label: '文件夹' },
];

/** Emby 式排序（影片墙） */
export type MakerSortId =
  | 'name'
  | 'code'
  | 'recent'
  | 'year'
  | 'studio'
  | 'prefix'
  | 'actress'
  | 'random';

export const MAKER_SORT_OPTS: Array<{ id: MakerSortId; label: string }> = [
  { id: 'year', label: '发行日期' },
  { id: 'code', label: '番号' },
  { id: 'name', label: '名称' },
  { id: 'prefix', label: '前缀' },
  { id: 'studio', label: '片商' },
  { id: 'actress', label: '女优' },
  { id: 'recent', label: '最近添加' },
  { id: 'random', label: '随机' },
];

/** 合集 / 流派 / 标签 / 文件夹列表排序 */
export type MakerFacetSortId = 'name' | 'count';

export const MAKER_FACET_SORT_OPTS: Array<{
  id: MakerFacetSortId;
  label: string;
}> = [
  { id: 'name', label: '名称' },
  { id: 'count', label: '数量' },
];

export function makerSourceLabel(id: MakerCatalogSourceId): string {
  return MAKER_KIND_TABS.find((t) => t.id === id)?.label || id;
}

/** 片商详情跳仓库：双库同搜，优先展示色花堂；115 落到「片商」区分子目录 */
export function openMakerHomeSearch(
  item: {
    code?: string | null;
    title?: string | null;
    id?: string;
    region?: string | null;
  },
  scrollToTab?: (tab: TabRoute) => void,
): boolean {
  const code = String(item.code || '').trim();
  const title = String(item.title || '').trim();
  const id = String(item.id || '').trim();
  const region = String(item.region || '').trim();
  const q = code || title || id;
  if (q.trim().length < SEARCH_KEYWORD_LENGTH_MIN) return false;
  // 转存 115：按分区进子目录，字幕进「字幕」
  writeP115AttachSubs({ code, itemId: id, region });
  return openHomeSearch(q, scrollToTab, {
    source: 'sehua',
    p115Source: 'makers',
  });
}
