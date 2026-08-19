import type {
  MakerFsPrefixCodeItem,
  MakerFsRegionCatalog,
  MakerFsRegionSummary,
  MakerFsRegionsOverview,
} from '@/lib/api';
import { makerCodeFormatMeta } from '@/lib/makerCode';
import { avMakersForFsRegion, prefixNote } from '@/config/av-makers';

export const MAKER_FS_FALLBACK_REGIONS: MakerFsRegionSummary[] = [
  { id: 'japan_censored', label: '日本有码', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'japan_gravure', label: '日本写真', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'japan_uncensored', label: '日本无码', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'japan_amateur', label: '日本素人', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'fc2', label: 'FC2', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'china', label: '国产无码', prefixCount: 0, makerCount: 0, codeCount: 0 },
  { id: 'western', label: '欧美无码', prefixCount: 0, makerCount: 0, codeCount: 0 },
];

/** 七区短标记（片商 / 本地索引共用） */
export const MAKER_FS_REGION_MARK: Record<string, string> = {
  japan_censored: '码',
  japan_gravure: '写',
  japan_uncensored: '无',
  japan_amateur: '素',
  fc2: 'F',
  china: '国',
  western: '欧',
};

export function makerFsRegionMark(regionId: string | undefined | null): string {
  return MAKER_FS_REGION_MARK[String(regionId || '').trim()] || '片';
}

/** 日本有码 / 日本写真：索引副文案含女优；其余区只用影片标题。全员另有 coverUrl。 */
export const MAKER_FS_ACTORS_TITLE_REGIONS = new Set([
  'japan_censored',
  'japan_gravure',
]);

export function indexesMakerFsActors(regionId: string | undefined | null): boolean {
  return MAKER_FS_ACTORS_TITLE_REGIONS.has(String(regionId || '').trim());
}

/** 规范展示：以后端 catalog 的 codeFormat/codeSample 为准，不用区名猜 */
export type MakerFsCodeFormatKind =
  | 'digit_pad'
  | 'western_date'
  | 'fc2'
  | 'fc2ppv'
  | 'date6'
  | 'alnum_id'
  | 'fixed_std';

export function makerFsPadEditable(p: {
  padEditable?: boolean;
  codeFormat?: string;
  prefix?: string;
}): boolean {
  if (typeof p.padEditable === 'boolean') return p.padEditable;
  if (p.codeFormat) return p.codeFormat === 'digit_pad';
  if (p.prefix) return makerCodeFormatMeta(p.prefix).padEditable;
  return true;
}

export function makerFsCodeSample(
  prefix: string,
  _regionId: string | undefined | null,
  opts?: {
    pad?: number;
    codeSample?: string;
    codeFormat?: string;
    padEditable?: boolean;
  },
): string {
  const cached = String(opts?.codeSample || '').trim();
  if (cached) return cached;
  const pref = String(prefix || '').trim();
  if (!pref) return '';
  const meta = makerCodeFormatMeta(pref);
  if (meta.codeFormat === 'digit_pad' && opts?.pad) {
    const pad = Math.max(1, Math.min(8, Number(opts.pad)));
    return `${pref.toUpperCase()}-${String(1).padStart(pad, '0')}`;
  }
  return meta.codeSample;
}

export function makerFsFormatKindLabel(codeFormat: string | undefined): string {
  switch (codeFormat) {
    case 'western_date':
      return '日期格式';
    case 'fc2':
    case 'fc2ppv':
      return 'FC2 编号';
    case 'date6':
      return '六位日期';
    case 'alnum_id':
      return '字母编号';
    case 'fixed_std':
      return '固定格式';
    default:
      return '数字位数';
  }
}

/**
 * 列表展示用规范番号（对齐后端 _index_code_key 流水规则）。
 * - 剥 -C/-CH 等字母尾缀
 * - 保留素人数字头前缀（200GANA）
 * - 短号按 pad 补零；已有前导零不压扁
 * - FC2 / date6 / western / alnum：不按流水号补零
 */
export function formatMakerFsIndexCode(
  code: string,
  opts?: { prefix?: string; pad?: number },
): string {
  const raw0 = String(code || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');
  if (!raw0) return '';
  // 分集尾巴
  const raw = raw0.replace(/(?<=\d)-(?:EP|E)?\d{1,2}$/i, '');
  const pad = Math.max(1, Math.min(8, Number(opts?.pad || 3)));
  const pref = String(opts?.prefix || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');

  // 异格式：原样（不对 6 位日期段做 digit_pad）
  if (
    /^FC2([-.]?PPV)?[-.]?\d/i.test(raw) ||
    /\.\d{4}\.\d{2}\.\d{2}/.test(raw) ||
    /^[A-Z0-9]{2,20}-\d{6}-\d{2,3}$/i.test(raw) ||
    /^(?:C0930|H0930|H4610)-/i.test(raw) ||
    /^TOKYO[-]?HOT[-.]?N?\d{3,5}$/i.test(raw) ||
    /^MESUBUTA-\d{6}-\d{2,3}$/i.test(raw)
  ) {
    // TOKYOHOT 规范成 TOKYOHOT-N####
    const th = raw.match(/^TOKYO[-]?HOT[-.]?N?(\d{3,5})$/i);
    if (th) return `TOKYOHOT-N${th[1]}`;
    return raw;
  }

  // GACHINCO ↔ GACHI
  if (pref === 'GACHINCO' || pref === 'GACHI') {
    const gm = raw.match(/^GACHI(?:NCO)?-(\d{3,5})([A-Z]{1,6})?$/i);
    if (gm) return `GACHI-${gm[1]}`;
  }

  const padNum = (numS: string): string => {
    const n = Number(numS);
    if (!Number.isFinite(n)) return numS;
    const w =
      numS.length > String(n).length
        ? Math.max(numS.length, String(n).length, pad)
        : Math.max(pad, String(n).length);
    return String(n).padStart(w, '0');
  };

  // 完整前缀匹配（含 200GANA-409C）
  if (pref) {
    const esc = pref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const m = raw.match(new RegExp(`^${esc}-(\\d+)([A-Z]{1,6})?$`, 'i'));
    if (m) return `${pref}-${padNum(m[1])}`;

    // pref=200GANA, raw=GANA-409
    const hub = pref.match(/^(\d{2,3})([A-Z]{2,20})$/);
    if (hub) {
      const letter = hub[2];
      const m2 = raw.match(new RegExp(`^${letter}-(\\d+)([A-Z]{1,6})?$`, 'i'));
      if (m2) return `${pref}-${padNum(m2[1])}`;
    }

    // pref=GANA, raw=200GANA-409
    if (!/^\d/.test(pref)) {
      const m3 = raw.match(
        new RegExp(`^(\\d{2,3})${esc}-(\\d+)([A-Z]{1,6})?$`, 'i'),
      );
      if (m3) return `${pref}-${padNum(m3[2])}`;
    }
    // 对不上前缀：异格式原样
    return raw;
  }

  // 无前缀约束：剥尾缀字母
  const m = raw.match(/^([A-Z0-9]+)-(\d+)([A-Z]{1,6})?$/i);
  if (!m) return raw;
  return `${m[1].toUpperCase()}-${padNum(m[2])}`;
}

function normalizeCaptionToken(s: string): string {
  return s.replace(/[\s\u3000·・、,，/|]+/g, '').toLowerCase();
}

/** 短串且像单一人名（无剧情词）——不当影片标题 */
function looksLikeBareActorTitle(title: string): boolean {
  const t = String(title || '').trim();
  if (t.length < 2 || t.length > 8) return false;
  if (/[\s\u3000]/.test(t)) return false;
  if (/[的了是与和在被把给跟！!？?…—《》「」]/.test(t)) return false;
  if (/流出|盗撮|中出|解禁|专属|性交|诱惑/.test(t)) return false;
  return /^[\u4e00-\u9fffぁ-んァ-ンー·・]{2,8}$/.test(t);
}

/** 标题是否其实只是女优名（避免封面下重复显示女优） */
function titleIsActorOnly(title: string, actorList: string[]): boolean {
  const nt = normalizeCaptionToken(title);
  if (!nt) return false;
  if (actorList.some((a) => nt === normalizeCaptionToken(a))) return true;
  if (actorList.length) {
    const joined = normalizeCaptionToken(actorList.join('、'));
    if (nt === joined) return true;
  }
  return looksLikeBareActorTitle(title);
}

/** 列表副文案：有码/写真同时显示女优+标题；其他区只显示标题 */
export function makerFsIndexCaption(
  item: Pick<MakerFsPrefixCodeItem, 'forumTitle' | 'forumActors'>,
  regionId: string | undefined | null,
): string {
  const { actors, title } = makerFsIndexLines(item, regionId);
  if (actors && title) return `${title} · ${actors}`;
  return title || actors;
}

/**
 * 拆开女优 / 标题：
 * - 有码/写真：女优上封面；下方只留真正标题（人名形短串不算标题）
 * - 其余区：只有标题
 */
export function makerFsIndexLines(
  item: Pick<MakerFsPrefixCodeItem, 'forumTitle' | 'forumActors'>,
  regionId: string | undefined | null,
): { actors: string; title: string } {
  let title = String(item.forumTitle || '').trim();
  if (!indexesMakerFsActors(regionId)) {
    return { actors: '', title };
  }
  const actorList = (item.forumActors || [])
    .map((a) => String(a || '').trim())
    .filter(Boolean)
    .slice(0, 4);
  let actors = actorList.join('、');

  if (title && titleIsActorOnly(title, actorList)) {
    // 与女优字段一致：可叠到封面；其它人名形短串（串号污染）直接丢弃
    if (!actors && looksLikeBareActorTitle(title)) {
      actors = title;
    }
    title = '';
  }
  return { actors, title };
}

export type MakerFsMakerGroup = {
  maker: string;
  prefixes: MakerFsRegionCatalog['prefixes'];
  prefixCount: number;
  codeCount: number;
};

export type MakerFsPrefixCover = Pick<
  MakerFsRegionCatalog['prefixes'][number],
  'posterLocal' | 'posterRev' | 'coverUrl' | 'coverUrls' | 'coverCode'
>;

export function prefixHasCover(p: MakerFsPrefixCover | undefined | null): boolean {
  if (!p) return false;
  if (String(p.posterLocal || '').trim()) return true;
  if (String(p.coverUrl || '').trim()) return true;
  return (p.coverUrls || []).some((u) => Boolean(String(u || '').trim()));
}

/** 厂牌卡片封面：优先番号最多且有海报的前缀 */
export function pickMakerGroupCover(g: MakerFsMakerGroup): MakerFsPrefixCover {
  const ranked = [...g.prefixes].sort(
    (a, b) => (b.codeCount || 0) - (a.codeCount || 0),
  );
  return ranked.find((p) => prefixHasCover(p)) || ranked[0] || {};
}

/** FC2 是个人作者产出，不是片商厂牌；索引阶段无作者名时归「未分类」。 */
export const MAKER_FS_FC2_UNCATEGORIZED = '未分类';

export function isMakerFsFc2Region(regionId: string | undefined | null): boolean {
  return String(regionId || '').trim() === 'fc2';
}

/** 论坛板名 / 前缀名是否只是 FC2 板块壳，而非真实作者名 */
export function isFc2PlateMakerName(name: string | undefined | null): boolean {
  const s = String(name || '')
    .trim()
    .toLowerCase()
    .replace(/[\s·\-_/]+/g, '');
  if (!s || s === '自定义' || s === '未分组' || s === '未知') return true;
  return (
    s === 'fc2' ||
    s === 'fc2ppv' ||
    s === 'fc2ppvfc2' ||
    s.startsWith('fc2fc2') ||
    /^fc2(ppv)?$/.test(s)
  );
}

/**
 * 片商分组标题：
 * - 普通区：board_name / name / prefix
 * - FC2：真实作者名；尚无作者（仅 FC2 板名）→「未分类」（刮削后可再改 board_name）
 */
export function makerFsGroupLabel(
  regionId: string | undefined | null,
  p: Pick<MakerFsRegionCatalog['prefixes'][number], 'board_name' | 'name' | 'prefix'>,
): string {
  if (isMakerFsFc2Region(regionId)) {
    const bn = String(p.board_name || '').trim();
    if (bn && !isFc2PlateMakerName(bn)) return bn;
    return MAKER_FS_FC2_UNCATEGORIZED;
  }
  return (p.board_name || p.name || p.prefix || '未分组').trim() || '未分组';
}

/** FC2 区用「作者」，其余用「厂牌」 */
export function makerFsGroupNoun(regionId: string | undefined | null): string {
  return isMakerFsFc2Region(regionId) ? '作者' : '厂牌';
}

export function formatMakerFsCount(n: number | undefined): string {
  const v = n ?? 0;
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return String(v);
}

/** 厂牌/前缀本页筛选：厂牌名、前缀、备注、女优、刮削标签 */
export function makerFsPrefixMatchesQuery(
  prefix: MakerFsRegionCatalog['prefixes'][number],
  query: string,
  maker?: string,
): boolean {
  const key = query.trim().toLowerCase();
  if (!key) return true;
  if (maker?.toLowerCase().includes(key)) return true;
  if (prefix.prefix.toLowerCase().includes(key)) return true;
  const board = String(prefix.board_name || '').toLowerCase();
  if (board.includes(key)) return true;
  const name = String(prefix.name || '').toLowerCase();
  if (name.includes(key)) return true;
  const note = prefixNote(maker || prefix.board_name || '', prefix.prefix).toLowerCase();
  if (note.includes(key)) return true;
  for (const a of prefix.actors || []) {
    if (String(a).toLowerCase().includes(key)) return true;
  }
  for (const t of prefix.tags || []) {
    if (String(t).toLowerCase().includes(key)) return true;
  }
  return false;
}

export function groupMakerFsByMaker(
  prefixes: MakerFsRegionCatalog['prefixes'] | undefined,
  regionId?: string | null,
): MakerFsMakerGroup[] {
  const map = new Map<string, MakerFsMakerGroup & { order: number }>();
  let order = 0;
  for (const p of prefixes || []) {
    const maker = makerFsGroupLabel(regionId, p);
    let g = map.get(maker);
    if (!g) {
      g = { maker, prefixes: [], prefixCount: 0, codeCount: 0, order };
      map.set(maker, g);
      order += 1;
    }
    g.prefixes.push(p);
    g.prefixCount += 1;
    g.codeCount += p.codeCount ?? 0;
  }
    return [...map.values()].sort((a, b) => a.order - b.order);
}

type CatalogPrefix = MakerFsRegionCatalog['prefixes'][number];

function catalogPrefixKey(prefix: string): string {
  return String(prefix || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');
}

/**
 * 片商页：厂牌名单来自 av-makers（写死）；前缀只跟 maker-fs 索引走，不造本地空目录。
 * 索引里没有的 JSON 前缀不展示。素人 / FC2 仍按索引 catalog 分组。
 */
export function groupMakersForBrowse(
  prefixes: MakerFsRegionCatalog['prefixes'] | undefined,
  regionId?: string | null,
): MakerFsMakerGroup[] {
  const fixed = avMakersForFsRegion(regionId);
  if (!fixed || fixed.length === 0) {
    return groupMakerFsByMaker(prefixes, regionId);
  }

  const byMakerPrefix = new Map<string, CatalogPrefix>();
  const byPrefix = new Map<string, CatalogPrefix>();
  const indexList = prefixes || [];
  for (const p of indexList) {
    const pref = catalogPrefixKey(p.prefix);
    if (!pref) continue;
    const maker = makerFsGroupLabel(regionId, p).toLowerCase();
    byMakerPrefix.set(`${maker}|${pref}`, p);
    if (!byPrefix.has(pref)) byPrefix.set(pref, p);
  }

  return fixed.map((entry) => {
    const maker = String(entry.maker || '').trim();
    const makerKey = maker.toLowerCase();
    const jsonKeys = new Set(
      (entry.prefixes || []).map((raw) => catalogPrefixKey(String(raw || ''))).filter(Boolean),
    );
    const used = new Set<string>();
    const list: CatalogPrefix[] = [];

    for (const raw of entry.prefixes || []) {
      const pref = String(raw || '').trim();
      const key = catalogPrefixKey(pref);
      if (!key) continue;
      const hit =
        byMakerPrefix.get(`${makerKey}|${key}`) ||
        (jsonKeys.has(key) ? byPrefix.get(key) : undefined);
      if (!hit || used.has(key)) continue;
      used.add(key);
      list.push({ ...hit, board_name: maker, prefix: hit.prefix || pref });
    }

    for (const p of indexList) {
      const key = catalogPrefixKey(p.prefix);
      if (!key || used.has(key)) continue;
      if (makerFsGroupLabel(regionId, p).toLowerCase() !== makerKey) continue;
      used.add(key);
      list.push({ ...p, board_name: maker });
    }

    return {
      maker,
      prefixes: list,
      prefixCount: list.length,
      codeCount: list.reduce((n, p) => n + (p.codeCount || 0), 0),
    };
  });
}

export type CatalogFacetItem = {
  name: string;
  count: number;
};

const TAG_META_KEYS = new Set(
  [
    '系列',
    '片商',
    '发行',
    '發行',
    '发行商',
    '發行商',
    '发行日期',
    '發行日期',
    '女优',
    '女優',
    '女优名',
    '女優名',
    '演员',
    '演員',
    '制作',
    '製作',
    '导演',
    '導演',
    '出品',
    '工作室',
    '厂商',
    '廠商',
    'studio',
    'maker',
    'publisher',
    'label',
    'series',
    'set',
    'actress',
    'actor',
    'director',
    '番号',
    'id',
    'num',
  ].map((x) => x.toLowerCase()),
);

const SERIES_META_KEYS = new Set(['系列', 'series', 'set']);

function splitTagMetaField(raw: string): { key: string; value: string } | null {
  const s = String(raw || '').trim();
  const m = s.match(/^(.{1,16}?)[:：]\s*(.+)$/);
  if (!m) return null;
  const key = m[1].trim().toLowerCase();
  const value = m[2].trim();
  if (!value || !TAG_META_KEYS.has(key)) return null;
  return { key, value };
}

function foldFacetName(s: string): string {
  return String(s || '')
    .trim()
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[・·‧･•∙⋅\s　…]+/g, '');
}

function looksLikeSeriesTitle(name: string): boolean {
  const folded = foldFacetName(name);
  return folded.length >= 10 && /[\u3040-\u309f]/.test(name);
}

/** 从片商目录 catalog 聚合标签 / 系列；过滤 nfo 混入的女优、系列、片商 */
export function aggregateCatalogFacets(
  prefixes: MakerFsRegionCatalog['prefixes'] | undefined,
): { tags: CatalogFacetItem[]; series: CatalogFacetItem[] } {
  const tagBag = new Map<string, number>();
  const seriesBag = new Map<string, number>();
  const seriesFold = new Map<string, string>();
  for (const p of prefixes || []) {
    const n = Math.max(1, p.codeCount ?? 0);
    const actorCf = new Set(
      (p.actors || []).map((a) => foldFacetName(String(a))).filter(Boolean),
    );
    const seriesNames = (p.series || [])
      .map((s) => String(s || '').trim())
      .filter(Boolean);
    const seriesCf = new Set(seriesNames.map((s) => foldFacetName(s)));
    const prefixCf = foldFacetName(String(p.prefix || ''));
    const studioCf = foldFacetName(String(p.board_name || ''));

    const addSeries = (name: string) => {
      const s = String(name || '').trim();
      if (!s) return;
      const cf = foldFacetName(s);
      if (!cf) return;
      const display = seriesFold.get(cf) || s;
      seriesFold.set(cf, display);
      seriesBag.set(display, (seriesBag.get(display) || 0) + n);
    };
    for (const s of seriesNames) addSeries(s);

    for (const raw of p.tags || []) {
      const name = String(raw || '').trim();
      if (!name) continue;
      const split = splitTagMetaField(name);
      if (split) {
        if (SERIES_META_KEYS.has(split.key)) addSeries(split.value);
        continue;
      }
      const cf = foldFacetName(name);
      if (actorCf.has(cf) || seriesCf.has(cf)) continue;
      if (prefixCf && cf === prefixCf) continue;
      if (studioCf && cf === studioCf) continue;
      if (looksLikeSeriesTitle(name)) {
        addSeries(name);
        continue;
      }
      tagBag.set(name, (tagBag.get(name) || 0) + n);
    }
  }
  const sort = (bag: Map<string, number>) =>
    [...bag.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
      .slice(0, 800);
  return { tags: sort(tagBag), series: sort(seriesBag) };
}

/** 本地索引目录同步完成后通知片商等界面刷新 */
export const MAKER_FS_CATALOGS_SYNCED = 'nextweb:maker-fs-catalogs-synced';

/** 本地片库（library）物化完成后通知片商刷新 */
export const LIBRARY_SYNCED = 'nextweb:library-synced';

const libraryCatalogCache = new Map<string, MakerFsRegionCatalog>();
let libraryRegionsCache: MakerFsRegionsOverview | null = null;
const REGIONS_LS_KEY = 'mk-regions-overview';

function readRegionsFromStorage(): MakerFsRegionsOverview | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(REGIONS_LS_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as MakerFsRegionsOverview;
    if (!data || !Array.isArray(data.regions) || data.regions.length === 0) {
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

export function getLibraryCatalogCache(
  regionId: string,
): MakerFsRegionCatalog | null {
  const id = String(regionId || '').trim();
  return id ? libraryCatalogCache.get(id) || null : null;
}

export function setLibraryCatalogCache(
  regionId: string,
  catalog: MakerFsRegionCatalog,
) {
  const id = String(regionId || '').trim();
  if (id) libraryCatalogCache.set(id, catalog);
}

export function getLibraryRegionsCache(): MakerFsRegionsOverview | null {
  if (libraryRegionsCache) return libraryRegionsCache;
  libraryRegionsCache = readRegionsFromStorage();
  return libraryRegionsCache;
}

export function setLibraryRegionsCache(data: MakerFsRegionsOverview) {
  libraryRegionsCache = data;
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(REGIONS_LS_KEY, JSON.stringify(data));
  } catch {
    /* ignore */
  }
}

export function clearLibraryBrowseCaches() {
  libraryCatalogCache.clear();
  libraryRegionsCache = null;
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(REGIONS_LS_KEY);
  } catch {
    /* ignore */
  }
}

export function prefetchLibraryRegion(regionId: string) {
  const id = String(regionId || '').trim();
  if (!id || libraryCatalogCache.has(id)) return;
  void import('@/lib/api').then(({ fetchMakerFsRegion }) =>
    fetchMakerFsRegion(id)
      .then((catalog) => setLibraryCatalogCache(id, catalog))
      .catch(() => undefined),
  );
}

export function notifyMakerFsCatalogsSynced() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(MAKER_FS_CATALOGS_SYNCED));
}

export function notifyLibrarySynced() {
  if (typeof window === 'undefined') return;
  clearLibraryBrowseCaches();
  window.dispatchEvent(new Event(LIBRARY_SYNCED));
  window.dispatchEvent(new Event(MAKER_FS_CATALOGS_SYNCED));
}
