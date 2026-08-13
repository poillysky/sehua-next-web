import {
  DEFAULT_POSTER_CROP,
  getPosterCrop,
  getScrape,
  type PosterCropConfig,
  type PosterCropMode,
} from '@/lib/api';

const LISTENERS = new Set<() => void>();
let cache: PosterCropConfig = DEFAULT_POSTER_CROP;
let loaded = false;
let inflight: Promise<void> | null = null;

export const POSTER_CROP_KIND_ROWS: Array<{ id: string; label: string }> = [
  { id: 'japan_censored', label: '日本有码' },
  { id: 'japan_gravure', label: '日本写真' },
  { id: 'japan_uncensored', label: '日本无码' },
  { id: 'japan_amateur', label: '日本素人' },
  { id: 'fc2', label: 'FC2' },
  { id: 'china', label: '国产无码' },
  { id: 'western', label: '欧美无码' },
];

export const POSTER_CROP_MODE_OPTIONS: Array<{
  value: PosterCropMode;
  label: string;
}> = [
  { value: 'right', label: '右侧裁剪' },
  { value: 'none', label: '不裁剪' },
  { value: 'face', label: '人脸取景' },
];

export const POSTER_CROP_RATIO_OPTIONS: Array<{
  value: PosterCropConfig['ratio'];
  title: string;
  sub: string;
}> = [
  {
    value: 'full',
    title: '完整海报',
    sub: '显示框 2.12/3，贴近碟片海报区',
  },
  {
    value: 'emby',
    title: 'Emby 比例',
    sub: '显示框 2/3，贴合海报墙格子',
  },
];

/** 显示用竖版框比例（CSS aspect） */
export function displayAspectForCropRatio(
  ratio?: PosterCropConfig['ratio'] | string | null,
): string {
  return String(ratio || 'full').toLowerCase() === 'emby' ? '2 / 3' : '2.12 / 3';
}

/** maker-fs / 搜索 region → 七区 id */
export function normalizeCropRegion(region?: string | null): string {
  const key = String(region || '')
    .trim()
    .toLowerCase();
  if (!key) return 'japan_censored';
  if (key === 'japan' || key === 'jp' || key === 'censored') return 'japan_censored';
  if (key === 'gravure') return 'japan_gravure';
  if (key === 'uncensored') return 'japan_uncensored';
  if (key === 'amateur' || key === '素人') return 'japan_amateur';
  if (key === 'fc2ppv') return 'fc2';
  if (cache.byKind[key]) return key;
  return 'japan_censored';
}

export function objectPositionForCropMode(
  mode: PosterCropMode | undefined,
): 'right top' | 'center top' | 'center' {
  if (mode === 'right') return 'right top';
  if (mode === 'face') return 'center top';
  return 'center';
}

/** 右侧/人脸（及未指定）用竖框；仅「不裁剪」用横框 */
export function isPortraitCropMode(mode?: PosterCropMode | null): boolean {
  return mode !== 'none';
}

/** 展示框宽高比：不裁剪固定横图 3/2，其余用海报竖比 */
export function frameAspectForCropMode(
  mode?: PosterCropMode | null,
  ratio?: PosterCropConfig['ratio'] | string | null,
): string {
  if (mode === 'none') {
    return '3 / 2';
  }
  return displayAspectForCropRatio(ratio ?? getPosterCropCached().ratio);
}

export function objectFitForCropMode(
  mode: PosterCropMode | undefined,
): 'cover' | 'contain' {
  return mode === 'none' ? 'contain' : 'cover';
}

export function getPosterCropCached(): PosterCropConfig {
  return cache;
}

export function setPosterCropCached(next: PosterCropConfig) {
  cache = next;
  loaded = true;
  LISTENERS.forEach((cb) => cb());
}

export function subscribePosterCrop(cb: () => void): () => void {
  LISTENERS.add(cb);
  return () => LISTENERS.delete(cb);
}

export async function ensurePosterCropLoaded(): Promise<PosterCropConfig> {
  if (loaded) return cache;
  if (!inflight) {
    inflight = (async () => {
      try {
        cache = await getPosterCrop();
      } catch {
        try {
          const d = await getScrape();
          if (d.posterCrop) cache = d.posterCrop;
        } catch {
          /* keep default */
        }
      } finally {
        loaded = true;
        inflight = null;
        LISTENERS.forEach((cb) => cb());
      }
    })();
  }
  await inflight;
  return cache;
}

export function cropModeForRegion(region?: string | null): PosterCropMode {
  const id = normalizeCropRegion(region);
  return cache.byKind[id] || DEFAULT_POSTER_CROP.byKind[id] || 'right';
}

export function objectPositionForRegion(region?: string | null): string {
  return objectPositionForCropMode(cropModeForRegion(region));
}
