import type { ScrapEnrichStrategy } from '@/lib/api';

export function cloneStrategy(s: ScrapEnrichStrategy): ScrapEnrichStrategy {
  const fill =
    s.fillMode === 'overwrite'
      ? 'overwrite'
      : s.fillMode === 'refresh_weak'
        ? 'refresh_weak'
        : 'incremental';
  const q = 'compact';
  const regionSources: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(s.regionSources || {})) {
    regionSources[k] = [...(Array.isArray(v) ? v : [])];
  }
  for (const r of s.regions || []) {
    if (!regionSources[r.id]?.length && Array.isArray(r.sources) && r.sources.length) {
      regionSources[r.id] = [...r.sources];
    }
  }
  return {
    ...s,
    regionGroups: Object.fromEntries(
      Object.entries(s.regionGroups || {}).map(([k, v]) => [k, [...(v || [])]]),
    ),
    regionSources,
    regionsEnabled: { ...(s.regionsEnabled || {}) },
    fillMode: fill,
    actressAvatarMode:
      s.actressAvatarMode === 'overwrite' ? 'overwrite' : 'incremental',
    llmTranslateOnJunk: s.llmTranslateOnJunk !== false,
    fieldLanguage: {
      title:
        s.fieldLanguage?.title === 'prefer_ja'
          ? 'prefer_ja'
          : s.fieldLanguage?.title === 'zh_or_translate'
            ? 'zh_or_translate'
            : 'prefer_zh',
      overview:
        s.fieldLanguage?.overview === 'prefer_ja'
          ? 'prefer_ja'
          : s.fieldLanguage?.overview === 'zh_or_translate'
            ? 'zh_or_translate'
            : 'prefer_zh',
    },
    stripTitleActorSuffix: Boolean(s.stripTitleActorSuffix),
    stripTitleCodePrefix: Boolean(s.stripTitleCodePrefix),
    fc2SellerAsActor: s.fc2SellerAsActor !== false,
    coverEnhance: s.coverEnhance === 'official' ? 'official' : 'off',
    outlineShow:
      s.outlineShow === 'zh_jp' || s.outlineShow === 'jp_zh'
        ? s.outlineShow
        : 'zh',
    forceFields: [...(s.forceFields || [])],
    fieldPriority: Object.fromEntries(
      Object.entries(s.fieldPriority || {}).map(([k, v]) => [
        k,
        [...(Array.isArray(v) ? v : [])],
      ]),
    ),
    fieldPriorityHideEmpty: Boolean(s.fieldPriorityHideEmpty),
    localMaps: {
      title:
        s.localMaps?.title === 'off'
          ? 'off'
          : s.localMaps?.title === 'force'
            ? 'force'
            : 'prefer',
      actors: s.localMaps?.actors === 'off' ? 'off' : 'fallback',
      tags: s.localMaps?.tags === 'off' ? 'off' : 'fallback',
      compactOutlineNewlines: s.localMaps?.compactOutlineNewlines !== false,
    },
    cover: {
      quality: q,
      cropRatio: s.cover?.cropRatio === 'emby' ? 'emby' : 'full',
      regionCrop: { ...(s.cover?.regionCrop || {}) },
      minShortEdge: s.cover?.minShortEdge,
      coverLogicVersion: s.cover?.coverLogicVersion,
    },
    coverCropOptions: [...(s.coverCropOptions || [])],
    coverQualityOptions: [...(s.coverQualityOptions || [])],
    coverRatioOptions: [...(s.coverRatioOptions || [])],
    fieldLanguageOptions: [...(s.fieldLanguageOptions || [])],
    coverEnhanceOptions: [...(s.coverEnhanceOptions || [])],
    outlineShowOptions: [...(s.outlineShowOptions || [])],
    forceFieldOptions: [...(s.forceFieldOptions || [])],
    fillModes: [...(s.fillModes || [])],
    localMapModeOptions: [...(s.localMapModeOptions || [])],
    regionSourceDefaults: {
      ...(s.regionSourceDefaults || {}),
    },
    fieldPriorityDefaults: Object.fromEntries(
      Object.entries(s.fieldPriorityDefaults || {}).map(([k, v]) => [
        k,
        [...(Array.isArray(v) ? v : [])],
      ]),
    ),
    regions: (s.regions || []).map((r) => ({
      ...r,
      groups: [...(r.groups || [])],
      sources: [...(regionSources[r.id] || r.sources || [])],
    })),
  };
}

/** 「恢复默认」以本表为准（对齐 COVER_LOGIC），不依赖可能过期的 API 缓存 */
export const REGION_SOURCE_RESTORE: Record<string, string[]> = {
  japan_censored: [
    'dmm',
    'libredmm',
    'r18dev',
    'javbus',
    'jav321',
    'avbase',
    'mgstage',
  ],
  // 无码：仅通用兜底；专用站按前缀内置
  japan_uncensored: ['avsox', 'javbus', 'airav_io', 'miss_av'],
  japan_amateur: ['mgstage', 'javbus', 'carib', 'airav_io'],
  fc2: ['fc2', 'fd2ppv', 'airav_io'],
  china: ['madouqu', 'madou', 'xiao_huang_shu'],
  western: ['theporndb'],
};

export const UNCENSORED_OFFICIAL_FALLBACK = [
  'heyzo',
  '1pondo',
  'pacopacomama',
  'carib',
  '10musume',
  'kin8',
  'h0930',
  'h4610',
  'c0930',
  'tokyohot',
  'nyoshin',
  'heydouga',
] as const;

export const FIELD_PRIORITY_RESTORE: Record<string, string[]> = {
  title: ['airav_io', 'iqqtv', 'javbus'],
  overview: ['airav_io', 'iqqtv'],
  actors: ['javbus', 'airav_io', 'iqqtv'],
  poster: ['dmm', 'libredmm', 'r18dev', 'javbus', 'mgstage'],
  tags: ['javbus', 'avbase', 'freejavbt'],
};

export const MODE_OPTIONS = [
  {
    value: 'parallel_all',
    label: '全部并发',
    desc: '对该番号命中的数据源同时发起请求，按下方并发上限调度。',
  },
  {
    value: 'adaptive_first',
    label: '自适应优先',
    desc: '先请求自适应源；关键字段或封面仍缺时，再补跑过盾源。',
  },
  {
    value: 'adaptive_only',
    label: '仅自适应',
    desc: '只请求自适应源，不调度 Flare / 过盾源。',
  },
] as const;

export function digitsOnly(raw: string) {
  return String(raw || '').replace(/[^\d]/g, '');
}

export function clampInt(raw: string, fallback: number, min: number, max: number) {
  const n = Number(digitsOnly(raw));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}
