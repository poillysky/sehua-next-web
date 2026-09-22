/**
 * 刮削补全：启停 / 重试 / 策略 / 海报重压
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import type {
  AuthUser,
  BrowseResult,
  FilterSize,
  FilterTime,
  MatchMode,
  ResourceDbConfig,
  ResourceItem,
  SearchResult,
  SortType,
} from '@/types/resource';

export async function cancelScrapLibraryEnrich(): Promise<{
  ok?: boolean;
  paused?: boolean;
  cancelled?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/pause', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      paused?: boolean;
      cancelled?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function pauseScrapLibraryEnrich(): Promise<{
  ok?: boolean;
  paused?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/pause', {
    method: 'POST',
    body: '{}',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      paused?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function stopScrapLibraryEnrich(opts?: {
  region?: string;
}): Promise<{
  ok?: boolean;
  stopped?: boolean;
  cleared?: boolean;
  running?: boolean;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/stop', {
    method: 'POST',
    body: JSON.stringify({ region: opts?.region ?? '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      stopped?: boolean;
      cleared?: boolean;
      running?: boolean;
    }>
  ).data;
}

export async function retryScrapLibraryEnrichFails(opts: {
  region: string;
}): Promise<{
  ok?: boolean;
  reopened?: number;
  region?: string;
  counts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  injected?: boolean;
  running?: boolean;
  error?: string;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/retry-fails', {
    method: 'POST',
    body: JSON.stringify({ region: opts.region || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      reopened?: number;
      region?: string;
      counts?: {
        pending?: number;
        running?: number;
        done?: number;
        soft?: number;
        fail?: number;
      };
      injected?: boolean;
      running?: boolean;
      error?: string;
    }>
  ).data;
}

export async function retryScrapLibraryEnrichSofts(opts: {
  region: string;
}): Promise<{
  ok?: boolean;
  reopened?: number;
  region?: string;
  counts?: {
    pending?: number;
    running?: number;
    done?: number;
    soft?: number;
    fail?: number;
  };
  injected?: boolean;
  running?: boolean;
  error?: string;
}> {
  const res = await apiFetch('/scrap-library/embed/enrich/retry-softs', {
    method: 'POST',
    body: JSON.stringify({ region: opts.region || '' }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (
    (await res.json()) as Envelope<{
      ok?: boolean;
      reopened?: number;
      region?: string;
      counts?: {
        pending?: number;
        running?: number;
        done?: number;
        soft?: number;
        fail?: number;
      };
      injected?: boolean;
      running?: boolean;
      error?: string;
    }>
  ).data;
}

export type EnrichStrategyMode =
  | 'parallel_all'
  | 'adaptive_first'
  | 'adaptive_only';

export type CoverCropMode = 'right' | 'face' | 'none' | 'smart' | string;

export type ScrapEnrichCoverSettings = {
  quality: 'compact' | string;
  cropRatio?: 'full' | 'emby' | string;
  regionCrop: Record<string, CoverCropMode>;
  minShortEdge?: number;
  coverLogicVersion?: number;
};

export type ScrapEnrichStrategy = {
  mode: EnrichStrategyMode | string;
  modeLabel?: string;
  /** 同时处理的番号数 */
  itemWorkers?: number;
  adaptiveWorkers: number;
  flareWorkers: number;
  includeFlare: boolean;
  perSourceTimeoutSec: number;
  regionGroups: Record<string, string[]>;
  /** 番号类型 → 有序刮削源（全局优先级） */
  regionSources?: Record<string, string[]>;
  regionsEnabled?: Record<string, boolean>;
  fillMode?: 'incremental' | 'refresh_weak' | 'overwrite' | string;
  fillModeLabel?: string;
  fillModes?: { value: string; label: string }[];
  /** 女优头像：增量只补缺；覆盖已有也重下 */
  actressAvatarMode?: 'incremental' | 'overwrite' | string;
  /** 无可用中文或机翻过烂时，自动大模型译中 */
  llmTranslateOnJunk?: boolean;
  fieldLanguage?: { title?: string; overview?: string };
  stripTitleActorSuffix?: boolean;
  stripTitleCodePrefix?: boolean;
  fc2SellerAsActor?: boolean;
  coverEnhance?: 'off' | 'official' | string;
  outlineShow?: 'zh' | 'zh_jp' | 'jp_zh' | string;
  forceFields?: string[];
  /** 字段站点优先级覆盖：空 = catalog 默认；有值 = 配置源第一优先，链上首个合格即停 */
  fieldPriority?: Record<string, string[]>;
  /** 字段优先级页：隐藏未配置行 */
  fieldPriorityHideEmpty?: boolean;
  /** 元数据优化：标题/女优/标签映射 + 简介换行 */
  localMaps?: {
    title?: string;
    actors?: string;
    tags?: string;
    compactOutlineNewlines?: boolean;
  };
  cover?: ScrapEnrichCoverSettings;
  modes?: { value: string; label: string }[];
  groupOptions?: { id: string; label: string }[];
  regions?: {
    id: string;
    label: string;
    folderLabel?: string;
    groups: string[];
    sources?: string[];
    enabled?: boolean;
    coverHint?: string;
  }[];
  regionSourceDefaults?: Record<string, string[]>;
  /** 无码官网专用站（按前缀自动注入，不进 UI 链） */
  uncensoredOfficialSources?: string[];
  uncensoredOfficialHint?: string;
  coverCropOptions?: { id: string; label: string }[];
  coverQualityOptions?: { id: string; label: string }[];
  coverRatioOptions?: { id: string; label: string }[];
  fieldLanguageOptions?: { id: string; label: string }[];
  coverEnhanceOptions?: { id: string; label: string }[];
  outlineShowOptions?: { id: string; label: string }[];
  forceFieldOptions?: { id: string; label: string }[];
  fieldPriorityFields?: { id: string; label: string }[];
  sourceOptions?: { id: string; label: string; group?: string; enabled?: boolean }[];
  fieldPriorityDefaults?: Record<string, string[]>;
  localMapModeOptions?: { id: string; label: string }[];
};

export async function getScrapEnrichStrategy(): Promise<ScrapEnrichStrategy> {
  const res = await apiFetch('/scrap-library/embed/enrich/strategy');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapEnrichStrategy>).data;
}

export async function putScrapEnrichStrategy(
  body: Partial<ScrapEnrichStrategy>,
): Promise<ScrapEnrichStrategy> {
  const res = await apiFetch('/scrap-library/embed/enrich/strategy', {
    method: 'PUT',
    body: JSON.stringify({
      mode: body.mode ?? 'parallel_all',
      itemWorkers: body.itemWorkers ?? 5,
      adaptiveWorkers: body.adaptiveWorkers ?? 0,
      flareWorkers: body.flareWorkers ?? 0,
      includeFlare: body.includeFlare !== false,
      perSourceTimeoutSec: body.perSourceTimeoutSec ?? 45,
      regionGroups: body.regionGroups ?? {},
      regionSources:
        body.regionSources && typeof body.regionSources === 'object'
          ? body.regionSources
          : {},
      regionsEnabled: body.regionsEnabled ?? {},
      fillMode:
        body.fillMode === 'overwrite'
          ? 'overwrite'
          : body.fillMode === 'refresh_weak'
            ? 'refresh_weak'
            : 'incremental',
      actressAvatarMode:
        body.actressAvatarMode === 'overwrite' ? 'overwrite' : 'incremental',
      llmTranslateOnJunk: body.llmTranslateOnJunk !== false,
      fieldLanguage: body.fieldLanguage,
      stripTitleActorSuffix: Boolean(body.stripTitleActorSuffix),
      stripTitleCodePrefix: Boolean(body.stripTitleCodePrefix),
      fc2SellerAsActor: body.fc2SellerAsActor !== false,
      coverEnhance: body.coverEnhance === 'official' ? 'official' : 'off',
      outlineShow:
        body.outlineShow === 'zh_jp' || body.outlineShow === 'jp_zh'
          ? body.outlineShow
          : 'zh',
      forceFields: Array.isArray(body.forceFields)
        ? body.forceFields.map((x) => String(x || '').trim()).filter(Boolean)
        : [],
      fieldPriority:
        body.fieldPriority && typeof body.fieldPriority === 'object'
          ? body.fieldPriority
          : {},
      fieldPriorityHideEmpty: Boolean(body.fieldPriorityHideEmpty),
      localMaps: {
        title:
          body.localMaps?.title === 'off'
            ? 'off'
            : body.localMaps?.title === 'force'
              ? 'force'
              : 'prefer',
        actors: body.localMaps?.actors === 'off' ? 'off' : 'fallback',
        tags: body.localMaps?.tags === 'off' ? 'off' : 'fallback',
        compactOutlineNewlines: body.localMaps?.compactOutlineNewlines !== false,
      },
      cover: body.cover,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapEnrichStrategy>).data;
}

export type ScrapPosterRecompressStatus = {
  running: boolean;
  phase?: string;
  dryRun?: boolean;
  quality?: string;
  progress?: {
    done?: number;
    total?: number;
    ok?: number;
    skip?: number;
    fail?: number;
    savedBytes?: number;
    percent?: number;
  };
  result?: {
    ok?: boolean;
    dryRun?: boolean;
    quality?: string;
    total?: number;
    rewritten?: number;
    skipped?: number;
    failed?: number;
    savedBytes?: number;
    error?: string;
  } | null;
  error?: string;
};

export async function startScrapPosterRecompress(opts?: {
  region?: string;
  quality?: string;
  limit?: number;
  dryRun?: boolean;
}): Promise<ScrapPosterRecompressStatus> {
  const res = await apiFetch('/scrap-library/embed/posters/recompress', {
    method: 'POST',
    body: JSON.stringify({
      region: opts?.region || '',
      quality: opts?.quality || '',
      limit: opts?.limit ?? 0,
      dryRun: Boolean(opts?.dryRun),
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapPosterRecompressStatus>).data;
}

export async function getScrapPosterRecompressStatus(): Promise<ScrapPosterRecompressStatus> {
  const res = await apiFetch('/scrap-library/embed/posters/recompress/status');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ScrapPosterRecompressStatus>).data;
}

/** 缺本地海报时，把远程 cover 落到番号目录 poster.jpg */
