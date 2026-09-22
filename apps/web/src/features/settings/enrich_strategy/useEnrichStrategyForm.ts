import { useEffect, useRef, useState } from 'react';
import {
  getScrapEnrichStrategy,
  getScrapPosterRecompressStatus,
  putScrapEnrichStrategy,
  startScrapPosterRecompress,
  type ScrapEnrichStrategy,
} from '@/lib/api';
import {
  errorText,
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';
import {
  MODE_OPTIONS,
  clampInt,
  cloneStrategy,
} from './defaults';
import type { SectionId } from './types';
import {
  flushPendingPersist as flushPending,
  patchAndPersist as patchPersist,
  persistStrategy as doPersist,
  type PersistDeps,
} from './persist';
import * as mut from './mutations';

export type EnrichStrategyForm = ReturnType<typeof useEnrichStrategyForm>;

export function useEnrichStrategyForm(
  onStatus: StatusReporter,
  onSaved?: (cfg: ScrapEnrichStrategy) => void,
) {
  const [cfg, setCfg] = useState<ScrapEnrichStrategy | null>(null);
  const [section, setSection] = useState<SectionId | null>(null);
  const [adaptiveWorkersText, setAdaptiveWorkersText] = useState('');
  const [itemWorkersText, setItemWorkersText] = useState('');
  const [flareWorkersText, setFlareWorkersText] = useState('');
  const [timeoutText, setTimeoutText] = useState('');
  const [recompressBusy, setRecompressBusy] = useState(false);
  const [recompressHint, setRecompressHint] = useState('');
  const [fpOpen, setFpOpen] = useState<string | null>(null);
  const [rsOpen, setRsOpen] = useState<string | null>(null);
  const [fpHideEmpty, setFpHideEmpty] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const persistTimerRef = useRef<number | null>(null);
  const pendingPersistRef = useRef<ScrapEnrichStrategy | null>(null);
  const { msg, setMsg, busy, run } = usePanelAction();

  function syncNumDrafts(s: ScrapEnrichStrategy) {
    setItemWorkersText(String(s.itemWorkers ?? 5));
    setAdaptiveWorkersText(String(s.adaptiveWorkers ?? 0));
    setFlareWorkersText(String(s.flareWorkers ?? 0));
    setTimeoutText(String(s.perSourceTimeoutSec ?? 45));
  }

  const persistDeps: PersistDeps = {
    setCfg,
    setFpHideEmpty,
    setAutoSaving,
    setMsg,
    syncNumDrafts,
    onStatus,
    onSaved,
    persistTimerRef,
    pendingPersistRef,
  };

  useEffect(() => {
    if (!rsOpen && !fpOpen) return;
    const onPointer = (e: PointerEvent) => {
      const t = e.target;
      if (!(t instanceof Element)) return;
      if (rsOpen) {
        const box = t.closest('[data-enrich-rs-box]');
        if (box?.getAttribute('data-enrich-rs-box') === rsOpen) return;
        setRsOpen(null);
      }
      if (fpOpen) {
        const box = t.closest('[data-enrich-fp-box]');
        if (box?.getAttribute('data-enrich-fp-box') === fpOpen) return;
        setFpOpen(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setRsOpen(null);
      setFpOpen(null);
    };
    const t = window.setTimeout(() => {
      window.addEventListener('pointerdown', onPointer, true);
    }, 0);
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('keydown', onKey);
    };
  }, [rsOpen, fpOpen]);

  function persistStrategy(next: ScrapEnrichStrategy, soft = true) {
    return doPersist(persistDeps, next, soft);
  }

  function flushPendingPersist() {
    flushPending(persistDeps);
  }

  function patchAndPersist(
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) {
    patchPersist(persistDeps, setCfg, updater);
  }

  useEffect(() => {
    const onHide = () => flushPending(persistDeps);
    window.addEventListener('pagehide', onHide);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') onHide();
    });
    return () => {
      window.removeEventListener('pagehide', onHide);
      flushPending(persistDeps);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- flush on unmount only
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getScrapEnrichStrategy();
        if (!cancelled) {
          const next = cloneStrategy(data);
          setCfg(next);
          setFpHideEmpty(Boolean(next.fieldPriorityHideEmpty));
          syncNumDrafts(next);
        }
      } catch (e) {
        if (!cancelled) {
          setMsg(e instanceof Error ? e.message : '加载失败');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function patch(partial: Partial<ScrapEnrichStrategy>) {
    setCfg((prev) => (prev ? { ...prev, ...partial } : prev));
  }

  function commitItemWorkers(raw = itemWorkersText) {
    const n = clampInt(raw, 5, 1, 16);
    setItemWorkersText(String(n));
    patch({ itemWorkers: n });
    return n;
  }

  function commitAdaptiveWorkers(raw = adaptiveWorkersText) {
    const n = clampInt(raw, 0, 0, 64);
    setAdaptiveWorkersText(String(n));
    patch({ adaptiveWorkers: n });
    return n;
  }

  function commitFlareWorkers(raw = flareWorkersText) {
    const n = clampInt(raw, 0, 0, 32);
    setFlareWorkersText(String(n));
    patch({ flareWorkers: n });
    return n;
  }

  function commitTimeout(raw = timeoutText) {
    const n = clampInt(raw, 45, 5, 180);
    setTimeoutText(String(n));
    patch({ perSourceTimeoutSec: n });
    return n;
  }

  function setMode(mode: string) {
    if (mode === 'adaptive_only') {
      patch({ mode, includeFlare: false });
      return;
    }
    patch({ mode });
  }

  async function onSave() {
    if (!cfg || busy || autoSaving) return;
    if (persistTimerRef.current != null) {
      window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
    }
    pendingPersistRef.current = null;
    const itemWorkers = commitItemWorkers();
    const adaptiveWorkers = commitAdaptiveWorkers();
    const flareWorkers = commitFlareWorkers();
    const perSourceTimeoutSec = commitTimeout();
    const payload = {
      ...cfg,
      itemWorkers,
      adaptiveWorkers,
      flareWorkers,
      perSourceTimeoutSec,
      fieldPriorityHideEmpty: fpHideEmpty,
    };
    await run(
      '保存失败',
      async () => {
        const saved = await putScrapEnrichStrategy(payload);
        const next = cloneStrategy(saved);
        setCfg(next);
        setFpHideEmpty(Boolean(next.fieldPriorityHideEmpty));
        syncNumDrafts(next);
        onSaved?.(next);
        onStatus('刮削策略已保存', 'ok');
        setMsg('已保存');
      },
      (e) => onStatus(errorText(e, '保存失败'), 'warn'),
    );
  }

  async function onRecompressPosters(dryRun: boolean) {
    if (recompressBusy || busy) return;
    setRecompressBusy(true);
    setRecompressHint(dryRun ? '预览中…' : '重压中…');
    try {
      await startScrapPosterRecompress({
        quality: cfg?.cover?.quality || 'compact',
        dryRun,
      });
      for (;;) {
        await new Promise((r) => setTimeout(r, 800));
        const st = await getScrapPosterRecompressStatus();
        const p = st.progress;
        if (st.running) {
          setRecompressHint(
            `${dryRun ? '预览' : '重压'} ${p?.done ?? 0}/${p?.total ?? 0}` +
              (p?.savedBytes
                ? ` · 可省 ${Math.round((p.savedBytes || 0) / 1024)}KB`
                : ''),
          );
          continue;
        }
        const res = st.result;
        if (st.error || res?.ok === false) {
          const text = st.error || res?.error || '重压失败';
          setRecompressHint(text);
          onStatus(text, 'warn');
          break;
        }
        const savedKb = Math.round((res?.savedBytes || 0) / 1024);
        const text = dryRun
          ? `预览：约 ${res?.rewritten ?? 0} 张可压，省 ~${savedKb}KB`
          : `已重压 ${res?.rewritten ?? 0} 张，省 ${savedKb}KB（跳过 ${res?.skipped ?? 0}）`;
        setRecompressHint(text);
        onStatus(text, 'ok');
        break;
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '重压失败';
      setRecompressHint(text);
      onStatus(text, 'warn');
    } finally {
      setRecompressBusy(false);
    }
  }

  const regions = cfg?.regions || [];
  const mode = cfg?.mode || 'parallel_all';
  const modeMeta =
    MODE_OPTIONS.find((m) => m.value === mode) || MODE_OPTIONS[0];
  const allowFlare = mode !== 'adaptive_only';
  const flareOn = allowFlare && Boolean(cfg?.includeFlare);
  const showFlareWorkers = mode === 'adaptive_first' && flareOn;
  const fillMode =
    cfg?.fillMode === 'overwrite'
      ? 'overwrite'
      : cfg?.fillMode === 'refresh_weak'
        ? 'refresh_weak'
        : 'incremental';
  const fillModeHint =
    fillMode === 'overwrite'
      ? '全部重跑覆盖；队列先空壳再其余'
      : fillMode === 'refresh_weak'
        ? '缺口队列，强制写回薄标题 / 空剧情 / 坏封面'
        : '先刮空壳（仅骨架），再补缺数据';
  const actressAvatarMode =
    cfg?.actressAvatarMode === 'overwrite' ? 'overwrite' : 'incremental';
  const actressAvatarModeHint =
    actressAvatarMode === 'overwrite'
      ? '已有头像也重新下载覆盖'
      : '只排队缺头像的人，已有的不进进度';
  const coverQualityLabel = '省盘';
  const coverRatioLabel =
    (cfg?.cover?.cropRatio || 'full') === 'emby' ? 'Emby 2:3' : '完整海报';
  const coverCropSummary = (() => {
    if (!cfg?.cover?.regionCrop) return '分区裁切';
    const modes = Object.values(cfg.cover.regionCrop);
    const right = modes.filter((m) => m === 'right' || m === 'smart').length;
    const face = modes.filter((m) => m === 'face').length;
    const none = modes.filter((m) => m === 'none').length;
    return `右${right}/脸${face}/不裁${none}`;
  })();
  const regionSourceHint = (() => {
    if (!cfg) return '…';
    const rs = cfg.regionSources || {};
    const n = regions.filter((r) => (rs[r.id] || []).length > 0).length;
    return n > 0 ? `${n}/${regions.length || 7} 类型已配源` : '未配置';
  })();
  const fieldPriorityHint = (() => {
    if (!cfg) return '…';
    const fp = cfg.fieldPriority || {};
    const n = Object.values(fp).filter((v) => Array.isArray(v) && v.length > 0)
      .length;
    const total = (cfg.fieldPriorityFields || []).length || 9;
    const base = n > 0 ? `${n}/${total} 字段已配` : '未配置 · 用默认链';
    return `${base} · 仅有码`;
  })();
  const localMapsHint = (() => {
    if (!cfg) return '…';
    const onOff = (on: boolean) => (on ? '开' : '关');
    return [
      `标题${onOff(cfg.localMaps?.title !== 'off')}`,
      `女优${onOff(cfg.localMaps?.actors !== 'off')}`,
      `标签${onOff(cfg.localMaps?.tags !== 'off')}`,
      `换行${onOff(cfg.localMaps?.compactOutlineNewlines !== false)}`,
    ].join(' · ');
  })();

  const hubRows: Array<{ id: SectionId; title: string; desc: string }> = [
    {
      id: 'fill',
      title: '补齐与女优',
      desc: `番号${
        fillMode === 'overwrite'
          ? '覆盖'
          : fillMode === 'refresh_weak'
            ? '弱项'
            : '增量'
      } · 头像${actressAvatarMode === 'overwrite' ? '覆盖' : '增量'}`,
    },
    {
      id: 'schedule',
      title: '调度与并发',
      desc: `番号×${itemWorkersText || '5'} · ${modeMeta.label}${flareOn ? ' · 含过盾' : ''} · 超时 ${timeoutText || '—'}s`,
    },
    { id: 'regions', title: '优先级设置(全局)', desc: regionSourceHint },
    { id: 'fields', title: '字段优先级', desc: fieldPriorityHint },
    { id: 'maps', title: '元数据优化', desc: localMapsHint },
    {
      id: 'cover',
      title: '刮削封面',
      desc: `${coverQualityLabel} · ${coverCropSummary} · ${coverRatioLabel}`,
    },
  ];

  return {
    actressAvatarMode,
    actressAvatarModeHint,
    adaptiveWorkersText,
    allowFlare,
    autoSaving,
    busy,
    cfg,
    commitAdaptiveWorkers,
    commitFlareWorkers,
    commitItemWorkers,
    commitTimeout,
    coverCropSummary,
    coverQualityLabel,
    coverRatioLabel,
    fieldPriorityHint,
    fillMode,
    fillModeHint,
    flareOn,
    flareWorkersText,
    flushPendingPersist,
    fpHideEmpty,
    fpOpen,
    hubRows,
    itemWorkersText,
    localMapsHint,
    mode,
    modeMeta,
    moveFieldPrioritySite: (fieldId: string, sourceId: string, dir: -1 | 1) =>
      mut.moveFieldPrioritySite(patchAndPersist, fieldId, sourceId, dir),
    moveRegionSource: (regionId: string, sourceId: string, dir: -1 | 1) =>
      mut.moveRegionSource(patchAndPersist, regionId, sourceId, dir),
    msg,
    onRecompressPosters,
    onSave,
    patch,
    patchAndPersist,
    pendingPersistRef,
    persistStrategy,
    persistTimerRef,
    recompressBusy,
    recompressHint,
    regionSourceHint,
    regions,
    rsOpen,
    run,
    section,
    setAdaptiveWorkersText,
    setAutoSaving,
    setCfg,
    setCoverRatio: (cropRatio: 'full' | 'emby') =>
      mut.setCoverRatio(setCfg, cropRatio),
    setFlareWorkersText,
    setFpHideEmpty,
    setFpOpen,
    setItemWorkersText,
    setMode,
    setMsg,
    setRecompressBusy,
    setRecompressHint,
    setRegionCoverCrop: (regionId: string, mode: string) =>
      mut.setRegionCoverCrop(setCfg, regionId, mode),
    setRsOpen,
    setSection,
    setTimeoutText,
    showFlareWorkers,
    syncNumDrafts,
    timeoutText,
    toggleFieldPrioritySite: (fieldId: string, sourceId: string) =>
      mut.toggleFieldPrioritySite(patchAndPersist, fieldId, sourceId),
    toggleRegionSource: (regionId: string, sourceId: string) =>
      mut.toggleRegionSource(patchAndPersist, cfg, regionId, sourceId),
  };
}
