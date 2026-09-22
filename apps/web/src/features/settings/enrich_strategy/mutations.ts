import type { ScrapEnrichStrategy } from '@/lib/api';
import { UNCENSORED_OFFICIAL_FALLBACK } from './defaults';

export function toggleRegionSource(
  patchAndPersist: (
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) => void,
  cfg: ScrapEnrichStrategy | null,
  regionId: string,
  sourceId: string,
) {
  const official = new Set(
    (cfg?.uncensoredOfficialSources?.length
      ? cfg.uncensoredOfficialSources
      : UNCENSORED_OFFICIAL_FALLBACK
    ).map((s) => s),
  );
  if (regionId === 'japan_uncensored' && official.has(sourceId)) {
    return;
  }
  patchAndPersist((prev) => {
    const cur = [...((prev.regionSources || {})[regionId] || [])];
    const i = cur.indexOf(sourceId);
    if (i >= 0) cur.splice(i, 1);
    else cur.push(sourceId);
    const regionSources = { ...(prev.regionSources || {}), [regionId]: cur };
    const regions = (prev.regions || []).map((r) =>
      r.id === regionId ? { ...r, sources: cur } : r,
    );
    return { ...prev, regionSources, regions };
  });
}

export function moveRegionSource(
  patchAndPersist: (
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) => void,
  regionId: string,
  sourceId: string,
  dir: -1 | 1,
) {
  patchAndPersist((prev) => {
    const cur = [...((prev.regionSources || {})[regionId] || [])];
    const i = cur.indexOf(sourceId);
    if (i < 0) return prev;
    const j = i + dir;
    if (j < 0 || j >= cur.length) return prev;
    const tmp = cur[i]!;
    cur[i] = cur[j]!;
    cur[j] = tmp;
    return {
      ...prev,
      regionSources: { ...(prev.regionSources || {}), [regionId]: cur },
      regions: (prev.regions || []).map((r) =>
        r.id === regionId ? { ...r, sources: cur } : r,
      ),
    };
  });
}

export function toggleFieldPrioritySite(
  patchAndPersist: (
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) => void,
  fieldId: string,
  sourceId: string,
) {
  patchAndPersist((prev) => {
    const cur = [...((prev.fieldPriority || {})[fieldId] || [])];
    const i = cur.indexOf(sourceId);
    if (i >= 0) cur.splice(i, 1);
    else cur.push(sourceId);
    const next = { ...(prev.fieldPriority || {}) };
    if (cur.length === 0) delete next[fieldId];
    else next[fieldId] = cur;
    return { ...prev, fieldPriority: next };
  });
}

export function moveFieldPrioritySite(
  patchAndPersist: (
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) => void,
  fieldId: string,
  sourceId: string,
  dir: -1 | 1,
) {
  patchAndPersist((prev) => {
    const cur = [...((prev.fieldPriority || {})[fieldId] || [])];
    const i = cur.indexOf(sourceId);
    if (i < 0) return prev;
    const j = i + dir;
    if (j < 0 || j >= cur.length) return prev;
    const tmp = cur[i]!;
    cur[i] = cur[j]!;
    cur[j] = tmp;
    return {
      ...prev,
      fieldPriority: { ...(prev.fieldPriority || {}), [fieldId]: cur },
    };
  });
}

export function setCoverRatio(
  setCfg: (
    next:
      | ScrapEnrichStrategy
      | null
      | ((prev: ScrapEnrichStrategy | null) => ScrapEnrichStrategy | null),
  ) => void,
  cropRatio: 'full' | 'emby',
) {
  setCfg((prev) => {
    if (!prev) return prev;
    return {
      ...prev,
      cover: {
        quality: 'compact',
        cropRatio,
        regionCrop: { ...(prev.cover?.regionCrop || {}) },
        minShortEdge: prev.cover?.minShortEdge,
        coverLogicVersion: prev.cover?.coverLogicVersion,
      },
    };
  });
}

export function setRegionCoverCrop(
  setCfg: (
    next:
      | ScrapEnrichStrategy
      | null
      | ((prev: ScrapEnrichStrategy | null) => ScrapEnrichStrategy | null),
  ) => void,
  regionId: string,
  mode: string,
) {
  const next = mode === 'face' ? 'face' : mode === 'none' ? 'none' : 'right';
  setCfg((prev) => {
    if (!prev) return prev;
    return {
      ...prev,
      cover: {
        quality: 'compact',
        cropRatio: prev.cover?.cropRatio === 'emby' ? 'emby' : 'full',
        regionCrop: {
          ...(prev.cover?.regionCrop || {}),
          [regionId]: next,
        },
        minShortEdge: prev.cover?.minShortEdge,
        coverLogicVersion: prev.cover?.coverLogicVersion,
      },
    };
  });
}
