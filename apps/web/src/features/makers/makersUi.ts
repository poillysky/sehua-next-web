import type { MakerCatalogSourceId } from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import type { TabRoute } from '@/shell';
import { openHomeSearch } from '@/features/media/mediaUi';
import { writeP115AttachSubs } from '@/lib/p115AttachSubs';

/** 六区顶栏（库 / 分区；原写真并入有码） */
export const MAKER_KIND_TABS: Array<{
  id: MakerCatalogSourceId;
  label: string;
}> = [
  { id: 'japan_censored', label: '有码' },
  { id: 'japan_uncensored', label: '无码' },
  { id: 'japan_amateur', label: '素人' },
  { id: 'fc2', label: 'FC2' },
  { id: 'china', label: '国产' },
  { id: 'western', label: '欧美' },
];

/** 横图封面区：无码 / 国产 / 欧美（推荐货架与分区页共用） */
export const MAKER_LANDSCAPE_REGIONS = new Set<MakerCatalogSourceId>([
  'japan_uncensored',
  'china',
  'western',
]);

export function isMakerLandscapeRegion(
  region: string | null | undefined,
): boolean {
  return MAKER_LANDSCAPE_REGIONS.has(String(region || '') as MakerCatalogSourceId);
}

/** 有码列表：横图右裁竖幅，竖图原样（服务端 rp 只在宽>高时裁） */
export function isCensoredRightCropRegion(
  region: string | null | undefined,
): boolean {
  const raw = String(region || '').trim();
  if (!raw) return false;
  if (raw === 'japan_censored' || raw === '有码' || raw === '日本有码') return true;
  try {
    const dec = decodeURIComponent(raw);
    return dec.includes('日本有码') || dec.includes('/有码/');
  } catch {
    return false;
  }
}

/** FC2 / FC2-PPV：厂牌墙点进后跳过前缀层，直接番号列表 */
export function isFc2DirectStudio(studio: string): boolean {
  const n = String(studio || '')
    .trim()
    .toUpperCase()
    .replace(/[\s_-]/g, '');
  return n === 'FC2' || n === 'FC2PPV';
}

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
  { id: 'folders', label: '文件夹' },
  { id: 'movies', label: '影片' },
  { id: 'genres', label: '标签' },
  { id: 'tags', label: '女优' },
  { id: 'favorites', label: '收藏' },
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
export type MakerFacetSortId = 'name' | 'count' | 'age';

export const MAKER_FACET_SORT_OPTS: Array<{
  id: MakerFacetSortId;
  label: string;
}> = [
  { id: 'name', label: '名称' },
  { id: 'count', label: '数量' },
];

/** 女优墙：默认按年龄（小→大） */
export const MAKER_ACTRESS_SORT_OPTS: Array<{
  id: MakerFacetSortId;
  label: string;
}> = [
  { id: 'age', label: '年龄' },
  { id: 'count', label: '数量' },
  { id: 'name', label: '名称' },
];

/** 厂牌下前缀列表排序（文件夹下钻） */
export type MakerPrefixSortId = 'code' | 'name' | 'count';

export const MAKER_PREFIX_SORT_OPTS: Array<{
  id: MakerPrefixSortId;
  label: string;
}> = [
  { id: 'code', label: '先后' },
  { id: 'count', label: '数量' },
  { id: 'name', label: '名称' },
];

export function makerSourceLabel(id: MakerCatalogSourceId): string {
  return MAKER_KIND_TABS.find((t) => t.id === id)?.label || id;
}

/**
 * FC2 资源库搜索词：按文件夹定主关键词，并附带另一写法。
 * - FC2 夹 → 主 `FC2-{n}`，兼试 `FC2-PPV-{n}`
 * - PPV 夹 → 主 `FC2-PPV-{n}`，兼试 `FC2-{n}`
 * 色花堂帖题常混写两种，只搜一种会漏。
 */
export function fc2HomeSearchTerms(
  code: string,
  opts?: { prefix?: string | null; itemId?: string | null },
): string[] | null {
  const raw = String(code || '').trim();
  const m = raw.match(/^FC2(?:[-_\s.]?PPV)?[-_\s.]?(\d{5,10})$/i);
  if (!m) return null;
  const n = m[1];
  const fc2 = `FC2-${n}`;
  const ppv = `FC2-PPV-${n}`;
  const hint = [
    String(opts?.prefix || ''),
    String(opts?.itemId || ''),
    raw,
  ]
    .join('/')
    .toUpperCase()
    .replace(/[\s_]/g, '-');
  const preferPpv =
    /FC2-?PPV/.test(hint) || /\/FC2PPV\b/.test(hint.replace(/-/g, ''));
  return preferPpv ? [ppv, fc2] : [fc2, ppv];
}

/** 片商详情跳仓库：双库同搜，优先展示色花堂；115 落到「片商」区分子目录 */
export function openMakerHomeSearch(
  item: {
    code?: string | null;
    title?: string | null;
    id?: string;
    region?: string | null;
    prefix?: string | null;
  },
  scrollToTab?: (tab: TabRoute) => void,
): boolean {
  const code = String(item.code || '').trim();
  const title = String(item.title || '').trim();
  const id = String(item.id || '').trim();
  const region = String(item.region || '').trim();
  const prefix = String(item.prefix || '').trim();
  const fc2Terms = fc2HomeSearchTerms(code, { prefix, itemId: id });
  const names = fc2Terms || [code || title || id];
  const q = names[0] || '';
  if (q.trim().length < SEARCH_KEYWORD_LENGTH_MIN) return false;
  // 转存 115：按分区进子目录，字幕进「字幕」
  writeP115AttachSubs({
    code: fc2Terms?.[0] || code,
    itemId: id,
    region,
  });
  return openHomeSearch(names, scrollToTab, {
    source: 'sehua',
    p115Source: 'makers',
  });
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * 海报/详情标题：剥掉开头番号（卡片上方已单独显示 code）。
 * 兼容 FC2 ↔ FC2-PPV、去横杠、可选分隔符。
 */
export function stripTitleCodePrefix(title: string, code: string): string {
  const raw = String(title || '').trim();
  const c = String(code || '').trim();
  if (!raw) return '';
  if (!c) return raw;

  let out = raw;
  const tryStrip = (pattern: string) => {
    const next = out
      .replace(new RegExp(`^${pattern}\\s*[-:：]?\\s*`, 'i'), '')
      .trim();
    if (next) out = next;
  };

  tryStrip(escapeRegExp(c));
  const compact = c.replace(/[-_\s]/g, '');
  if (compact && compact.toLowerCase() !== c.toLowerCase()) {
    tryStrip(escapeRegExp(compact));
  }

  const fc2 = c.match(/^FC2(?:[-_]?PPV)?[-_]?(\d+)$/i);
  if (fc2) {
    const n = fc2[1];
    tryStrip(`FC2[-_]?PPV[-_]?${n}`);
    tryStrip(`FC2[-_]?${n}`);
    tryStrip(n);
  }

  // 标题以「任意厂牌形番号 + 本条数字」开头时一并去掉（如 SSIS-001 vs 库内 SSIS001）
  const digits = c.replace(/\D/g, '');
  if (digits && digits.length >= 3) {
    tryStrip(`[A-Z]{1,12}[-_]?${digits}`);
  }

  return out || raw;
}
