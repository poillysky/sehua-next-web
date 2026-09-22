import type { MutableRefObject } from 'react';
import {
  putScrapEnrichStrategy,
  type ScrapEnrichStrategy,
} from '@/lib/api';
import type { StatusReporter } from '@/hooks/usePanelAction';
import { cloneStrategy } from './defaults';

export type PersistDeps = {
  setCfg: (next: ScrapEnrichStrategy | null | ((prev: ScrapEnrichStrategy | null) => ScrapEnrichStrategy | null)) => void;
  setFpHideEmpty: (v: boolean) => void;
  setAutoSaving: (v: boolean) => void;
  setMsg: (v: string) => void;
  syncNumDrafts: (s: ScrapEnrichStrategy) => void;
  onStatus: StatusReporter;
  onSaved?: (cfg: ScrapEnrichStrategy) => void;
  persistTimerRef: MutableRefObject<number | null>;
  pendingPersistRef: MutableRefObject<ScrapEnrichStrategy | null>;
};

export async function persistStrategy(
  deps: PersistDeps,
  next: ScrapEnrichStrategy,
  soft = true,
) {
  const {
    setCfg,
    setFpHideEmpty,
    setAutoSaving,
    setMsg,
    syncNumDrafts,
    onStatus,
    onSaved,
  } = deps;
  try {
    if (soft) setAutoSaving(true);
    const payload: ScrapEnrichStrategy = {
      ...next,
      regionSources: { ...(next.regionSources || {}) },
      fieldPriority: { ...(next.fieldPriority || {}) },
      fieldPriorityHideEmpty: Boolean(next.fieldPriorityHideEmpty),
      localMaps: {
        title:
          next.localMaps?.title === 'off'
            ? 'off'
            : next.localMaps?.title === 'force'
              ? 'force'
              : 'prefer',
        actors: next.localMaps?.actors === 'off' ? 'off' : 'fallback',
        tags: next.localMaps?.tags === 'off' ? 'off' : 'fallback',
        compactOutlineNewlines:
          next.localMaps?.compactOutlineNewlines !== false,
      },
      regionGroups: { ...(next.regionGroups || {}) },
    };
    const saved = await putScrapEnrichStrategy(payload);
    const cloned = cloneStrategy(saved);
    setCfg(cloned);
    setFpHideEmpty(Boolean(cloned.fieldPriorityHideEmpty));
    syncNumDrafts(cloned);
    onSaved?.(cloned);
    if (soft) {
      onStatus('已自动保存', 'ok');
      setMsg('已自动保存');
    }
    return cloned;
  } catch (e) {
    const text = e instanceof Error ? e.message : '保存失败';
    setMsg(text);
    onStatus(text, 'warn');
    return null;
  } finally {
    if (soft) setAutoSaving(false);
  }
}

export function flushPendingPersist(deps: PersistDeps) {
  if (deps.persistTimerRef.current != null) {
    window.clearTimeout(deps.persistTimerRef.current);
    deps.persistTimerRef.current = null;
  }
  const snap = deps.pendingPersistRef.current;
  deps.pendingPersistRef.current = null;
  if (snap) void persistStrategy(deps, snap, true);
}

export function patchAndPersist(
  deps: PersistDeps,
  setCfg: PersistDeps['setCfg'],
  updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
) {
  setCfg((prev) => {
    if (!prev) return prev;
    const next = updater(prev);
    if (next === prev) return prev;
    deps.pendingPersistRef.current = next;
    if (deps.persistTimerRef.current != null) {
      window.clearTimeout(deps.persistTimerRef.current);
    }
    deps.persistTimerRef.current = window.setTimeout(() => {
      const snap = deps.pendingPersistRef.current;
      deps.pendingPersistRef.current = null;
      deps.persistTimerRef.current = null;
      if (snap) void persistStrategy(deps, snap, true);
    }, 120);
    return next;
  });
}
