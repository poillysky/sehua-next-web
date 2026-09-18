'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, X } from 'lucide-react';
import {
  getScrapEnrichStrategy,
  putScrapEnrichStrategy,
  startScrapPosterRecompress,
  getScrapPosterRecompressStatus,
  type ScrapEnrichStrategy,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

function cloneStrategy(s: ScrapEnrichStrategy): ScrapEnrichStrategy {
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
const REGION_SOURCE_RESTORE: Record<string, string[]> = {
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

const UNCENSORED_OFFICIAL_FALLBACK = [
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

const FIELD_PRIORITY_RESTORE: Record<string, string[]> = {
  title: ['airav_io', 'iqqtv', 'javbus'],
  overview: ['airav_io', 'iqqtv'],
  actors: ['javbus', 'airav_io', 'iqqtv'],
  poster: ['dmm', 'libredmm', 'r18dev', 'javbus', 'mgstage'],
  tags: ['javbus', 'avbase', 'freejavbt'],
};

const MODE_OPTIONS = [
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

type SectionId = 'fill' | 'schedule' | 'regions' | 'fields' | 'maps' | 'cover';

function digitsOnly(raw: string) {
  return String(raw || '').replace(/[^\d]/g, '');
}

function clampInt(raw: string, fallback: number, min: number, max: number) {
  const n = Number(digitsOnly(raw));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

function SegTwo({
  value,
  left,
  right,
  disabled,
  onChange,
  ariaLabel,
}: {
  value: string;
  left: { id: string; label: string };
  right: { id: string; label: string };
  disabled?: boolean;
  onChange: (id: string) => void;
  ariaLabel: string;
}) {
  return (
    <div className="app-seg enrich-strategy__seg" role="radiogroup" aria-label={ariaLabel}>
      {[left, right].map((opt) => (
        <button
          key={opt.id}
          type="button"
          className={cn(
            'app-seg__btn',
            value === opt.id && 'app-seg__btn--active',
          )}
          disabled={disabled}
          role="radio"
          aria-checked={value === opt.id}
          onClick={() => onChange(opt.id)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export function EnrichStrategyPanel({
  onBack,
  onStatus,
  onSaved,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  onSaved?: (cfg: ScrapEnrichStrategy) => void;
}) {
  const [cfg, setCfg] = useState<ScrapEnrichStrategy | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
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

  function syncNumDrafts(s: ScrapEnrichStrategy) {
    setItemWorkersText(String(s.itemWorkers ?? 5));
    setAdaptiveWorkersText(String(s.adaptiveWorkers ?? 0));
    setFlareWorkersText(String(s.flareWorkers ?? 0));
    setTimeoutText(String(s.perSourceTimeoutSec ?? 45));
  }

  async function persistStrategy(next: ScrapEnrichStrategy, soft = true) {
    try {
      if (soft) setAutoSaving(true);
      // 全局 / 字段优先级相关字段整包写入，避免漏键
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

  function flushPendingPersist() {
    if (persistTimerRef.current != null) {
      window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
    }
    const snap = pendingPersistRef.current;
    pendingPersistRef.current = null;
    if (snap) void persistStrategy(snap, true);
  }

  function patchAndPersist(
    updater: (prev: ScrapEnrichStrategy) => ScrapEnrichStrategy,
  ) {
    setCfg((prev) => {
      if (!prev) return prev;
      const next = updater(prev);
      if (next === prev) return prev;
      pendingPersistRef.current = next;
      // 立即落库（短延迟合并连点 ↑↓）
      if (persistTimerRef.current != null) {
        window.clearTimeout(persistTimerRef.current);
      }
      persistTimerRef.current = window.setTimeout(() => {
        const snap = pendingPersistRef.current;
        pendingPersistRef.current = null;
        persistTimerRef.current = null;
        if (snap) void persistStrategy(snap, true);
      }, 120);
      return next;
    });
  }

  useEffect(() => {
    const onHide = () => flushPendingPersist();
    window.addEventListener('pagehide', onHide);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') onHide();
    });
    return () => {
      window.removeEventListener('pagehide', onHide);
      flushPendingPersist();
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

  function toggleRegionSource(regionId: string, sourceId: string) {
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

  function moveRegionSource(
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

  function setCoverRatio(cropRatio: 'full' | 'emby') {
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

  function setRegionCoverCrop(regionId: string, mode: string) {
    const next =
      mode === 'face' ? 'face' : mode === 'none' ? 'none' : 'right';
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

  function toggleFieldPrioritySite(fieldId: string, sourceId: string) {
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

  function moveFieldPrioritySite(
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
    setBusy(true);
    setMsg('');
    try {
      const saved = await putScrapEnrichStrategy(payload);
      const next = cloneStrategy(saved);
      setCfg(next);
      setFpHideEmpty(Boolean(next.fieldPriorityHideEmpty));
      syncNumDrafts(next);
      onSaved?.(next);
      onStatus('刮削策略已保存', 'ok');
      setMsg('已保存');
    } catch (e) {
      const text = e instanceof Error ? e.message : '保存失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setBusy(false);
    }
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

  const hubRows: Array<{
    id: SectionId;
    title: string;
    desc: string;
  }> = [
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
    {
      id: 'regions',
      title: '优先级设置(全局)',
      desc: regionSourceHint,
    },
    {
      id: 'fields',
      title: '字段优先级',
      desc: fieldPriorityHint,
    },
    {
      id: 'maps',
      title: '元数据优化',
      desc: localMapsHint,
    },
    {
      id: 'cover',
      title: '刮削封面',
      desc: `${coverQualityLabel} · ${coverCropSummary} · ${coverRatioLabel}`,
    },
  ];

  function renderFill() {
    const fillOpts = cfg?.fillModes?.length
      ? cfg.fillModes
      : [
          { value: 'incremental', label: '增量' },
          { value: 'refresh_weak', label: '弱项重刮' },
          { value: 'overwrite', label: '覆盖' },
        ];
    const langOpts = cfg?.fieldLanguageOptions?.length
      ? cfg.fieldLanguageOptions
      : [
          { id: 'prefer_zh', label: '中文优先' },
          { id: 'prefer_ja', label: '日文优先' },
          { id: 'zh_or_translate', label: '中文或译中' },
        ];
    const outlineOpts = cfg?.outlineShowOptions?.length
      ? cfg.outlineShowOptions
      : [
          { id: 'zh', label: '仅中文' },
          { id: 'zh_jp', label: '中日' },
          { id: 'jp_zh', label: '日中' },
        ];
    const titleLang = cfg?.fieldLanguage?.title || 'prefer_zh';
    const overviewLang = cfg?.fieldLanguage?.overview || 'prefer_zh';
    const outline =
      cfg?.outlineShow === 'zh_jp' || cfg?.outlineShow === 'jp_zh'
        ? cfg.outlineShow
        : 'zh';
    return (
      <>
        <p className="settings-group-label">补齐策略</p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">番号补齐</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {fillModeHint}
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="刮削补齐模式"
              >
                {fillOpts.map((opt) => {
                  const id = opt.value;
                  const on = fillMode === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fillMode:
                            id === 'overwrite'
                              ? 'overwrite'
                              : id === 'refresh_weak'
                                ? 'refresh_weak'
                                : 'incremental',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">女优刮削</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {actressAvatarModeHint}
                </span>
              </span>
              <SegTwo
                ariaLabel="女优刮削头像模式"
                value={actressAvatarMode}
                left={{ id: 'incremental', label: '增量' }}
                right={{ id: 'overwrite', label: '覆盖' }}
                disabled={busy}
                onChange={(id) =>
                  patch({
                    actressAvatarMode:
                      id === 'overwrite' ? 'overwrite' : 'incremental',
                  })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          字段语言与标题
        </p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">标题语言</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  合并时标题的语言偏好
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="标题语言"
              >
                {langOpts.map((opt) => {
                  const on = titleLang === opt.id;
                  return (
                    <button
                      key={`title-${opt.id}`}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fieldLanguage: {
                            title: opt.id,
                            overview: overviewLang,
                          },
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剧情语言</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  合并时剧情的语言偏好
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="剧情语言"
              >
                {langOpts.map((opt) => {
                  const on = overviewLang === opt.id;
                  return (
                    <button
                      key={`ov-${opt.id}`}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fieldLanguage: {
                            title: titleLang,
                            overview: opt.id,
                          },
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">详情剧情展示</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  新刮削写入 NFO；双语需同时有中/日剧情
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="详情剧情展示"
              >
                {outlineOpts.map((opt) => {
                  const on = outline === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          outlineShow:
                            opt.id === 'zh_jp' || opt.id === 'jp_zh'
                              ? opt.id
                              : 'zh',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剥标题尾女优名</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  定稿后去掉标题末尾演员名（默认关）
                </span>
              </span>
              <Switch
                checked={Boolean(cfg?.stripTitleActorSuffix)}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ stripTitleActorSuffix: Boolean(v) })
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剥标题前番号</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  定稿后去掉标题开头番号（默认关）
                </span>
              </span>
              <Switch
                checked={Boolean(cfg?.stripTitleCodePrefix)}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ stripTitleCodePrefix: Boolean(v) })
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">FC2 卖家作女优</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  女优空时用卖家名兜底（默认开）
                </span>
              </span>
              <Switch
                checked={cfg?.fc2SellerAsActor !== false}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ fc2SellerAsActor: Boolean(v) })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          增量强制写回
        </p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="enrich-strategy__force">
              <div className="enrich-strategy__force-head">
                <p className="enrich-strategy__force-desc">
                  仅增量生效；覆盖 / 弱项本就全量强制
                </p>
                {(cfg?.forceFields || []).length > 0 ? (
                  <button
                    type="button"
                    className="enrich-strategy__force-clear"
                    disabled={busy}
                    onClick={() => patch({ forceFields: [] })}
                  >
                    清除 · {(cfg?.forceFields || []).length}
                  </button>
                ) : (
                  <span className="enrich-strategy__force-count">未选</span>
                )}
              </div>
              <div
                className="enrich-strategy__force-grid"
                role="group"
                aria-label="增量强制字段"
              >
                {(
                  cfg?.forceFieldOptions?.length
                    ? cfg.forceFieldOptions
                    : [
                        { id: 'title', label: '标题' },
                        { id: 'overview', label: '剧情' },
                        { id: 'actors', label: '女优' },
                        { id: 'studio', label: '片商' },
                        { id: 'poster', label: '海报' },
                        { id: 'tags', label: '标签' },
                        { id: 'badges', label: '角标' },
                      ]
                ).map((opt) => {
                  const on = (cfg?.forceFields || []).includes(opt.id);
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__force-cell',
                        on && 'enrich-strategy__force-cell--on',
                      )}
                      disabled={busy}
                      aria-pressed={on}
                      onClick={() => {
                        const cur = new Set(cfg?.forceFields || []);
                        if (cur.has(opt.id)) cur.delete(opt.id);
                        else cur.add(opt.id);
                        patch({ forceFields: [...cur] });
                      }}
                    >
                      <span
                        className={cn(
                          'enrich-strategy__force-tick',
                          on && 'enrich-strategy__force-tick--on',
                        )}
                        aria-hidden
                      >
                        {on ? <Check strokeWidth={2.75} /> : null}
                      </span>
                      <span className="enrich-strategy__force-label">
                        {opt.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
        </ul>
      </>
    );
  }

  function renderSchedule() {
    if (!cfg) return null;
    const workersLabel =
      mode === 'parallel_all' && flareOn ? '并发上限' : '自适应并发';
    return (
      <>
        <p className="settings-group-label">调度模式</p>
        <ul
          className="settings-group enrich-strategy__choice-group"
          role="radiogroup"
          aria-label="调度模式"
        >
          {MODE_OPTIONS.map((m) => {
            const on = mode === m.value;
            return (
              <li key={m.value}>
                <button
                  type="button"
                  className={cn(
                    'settings-kv enrich-strategy__choice-row',
                    on && 'enrich-strategy__choice-row--on',
                  )}
                  disabled={busy}
                  role="radio"
                  aria-checked={on}
                  onClick={() => setMode(m.value)}
                >
                  <span className="settings-nav__main">
                    <span className="settings-kv__key">{m.label}</span>
                    <span className="settings-nav__desc enrich-strategy__mode-desc">
                      {m.desc}
                    </span>
                  </span>
                  <span
                    className={cn(
                      'enrich-strategy__check',
                      on && 'enrich-strategy__check--on',
                    )}
                    aria-hidden
                  >
                    {on ? <Check strokeWidth={2.5} /> : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        <p className="settings-group-label settings-group-label--spaced">选项</p>
        <ul className="settings-group">
          {allowFlare ? (
            <li>
              <div className="settings-kv enrich-strategy__mode-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">包含过盾源</span>
                  <span className="settings-nav__desc enrich-strategy__mode-desc">
                    {mode === 'adaptive_first'
                      ? '自适应未补齐时再调度 Flare'
                      : '过盾源一并参与并发'}
                  </span>
                </span>
                <Switch
                  checked={flareOn}
                  disabled={busy}
                  onCheckedChange={(v) => patch({ includeFlare: Boolean(v) })}
                />
              </div>
            </li>
          ) : null}
          <li>
            <div className="settings-kv enrich-strategy__mode-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">机翻过烂时大模型译中</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  无可用中文或机翻垃圾时，用设置里的 LLM 译标题/剧情
                </span>
              </span>
              <Switch
                checked={cfg.llmTranslateOnJunk !== false}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ llmTranslateOnJunk: Boolean(v) })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          并发参数
        </p>
        <ul className="settings-group enrich-strategy__params">
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">番号并发</span>
                <span className="settings-nav__desc">同时刮几部 · 1–16</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={itemWorkersText}
                disabled={busy}
                aria-label="番号并发"
                onChange={(e) =>
                  setItemWorkersText(digitsOnly(e.target.value))
                }
                onBlur={() => commitItemWorkers()}
              />
            </label>
          </li>
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">{workersLabel}</span>
                <span className="settings-nav__desc">0 = 不限制</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={adaptiveWorkersText}
                disabled={busy}
                aria-label={workersLabel}
                onChange={(e) =>
                  setAdaptiveWorkersText(digitsOnly(e.target.value))
                }
                onBlur={() => commitAdaptiveWorkers()}
              />
            </label>
          </li>
          {showFlareWorkers ? (
            <li>
              <label className="settings-kv enrich-strategy__param-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">过盾并发</span>
                  <span className="settings-nav__desc">0 = 不限制</span>
                </span>
                <input
                  type="text"
                  className="allow-select enrich-strategy__num"
                  inputMode="numeric"
                  value={flareWorkersText}
                  disabled={busy}
                  aria-label="过盾并发"
                  onChange={(e) =>
                    setFlareWorkersText(digitsOnly(e.target.value))
                  }
                  onBlur={() => commitFlareWorkers()}
                />
              </label>
            </li>
          ) : null}
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">单源超时</span>
                <span className="settings-nav__desc">单位：秒</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={timeoutText}
                disabled={busy}
                aria-label="单源超时（秒）"
                onChange={(e) => setTimeoutText(digitsOnly(e.target.value))}
                onBlur={() => commitTimeout()}
              />
            </label>
          </li>
        </ul>
      </>
    );
  }

  function renderRegions() {
    if (!cfg) return null;
    const sources = cfg.sourceOptions?.length ? cfg.sourceOptions : [];
    const labelOf = (sid: string) =>
      sources.find((s) => s.id === sid)?.label || sid;
    const isOn = (sid: string) =>
      sources.find((s) => s.id === sid)?.enabled !== false;
    const officialSet = new Set(
      (cfg.uncensoredOfficialSources?.length
        ? cfg.uncensoredOfficialSources
        : UNCENSORED_OFFICIAL_FALLBACK
      ).map((s) => s),
    );
    const visibleChain = (regionId: string, chain: string[]) =>
      regionId === 'japan_uncensored'
        ? chain.filter((sid) => !officialSet.has(sid))
        : chain;
    return (
      <div className="enrich-strategy__rs">
        <p className="enrich-strategy__rs-note">
          {cfg.uncensoredOfficialHint ||
            '无码：专用站按番号前缀自动启用（含 Tokyo Hot / Nyoshin）；此处只排通用兜底站。'}
        </p>
        <ul className="enrich-strategy__rs-list">
          {regions.map((region) => {
            const chain = visibleChain(
              region.id,
              (cfg.regionSources || {})[region.id] || region.sources || [],
            );
            const open = rsOpen === region.id;
            return (
              <li key={region.id} className="enrich-strategy__rs-row">
                <span className="enrich-strategy__rs-label">{region.label}</span>
                <div
                  className={cn(
                    'enrich-strategy__rs-box',
                    open && 'enrich-strategy__rs-box--open',
                  )}
                  data-enrich-rs-box={region.id}
                >
                  <button
                    type="button"
                    className="enrich-strategy__rs-trigger"
                    disabled={busy}
                    aria-expanded={open}
                    aria-haspopup="listbox"
                    aria-label={`${region.label} 源优先级`}
                    onClick={() =>
                      setRsOpen((cur) =>
                        cur === region.id ? null : region.id,
                      )
                    }
                  >
                    <span className="enrich-strategy__rs-tags">
                      {chain.length === 0 ? (
                        <span className="enrich-strategy__rs-empty">点选添加源</span>
                      ) : (
                        chain.map((sid, idx) => (
                          <span
                            key={`${region.id}-tag-${sid}`}
                            className={cn(
                              'enrich-strategy__rs-tag',
                              !isOn(sid) && 'enrich-strategy__rs-tag--off',
                            )}
                            title={
                              isOn(sid)
                                ? `${idx + 1}. ${labelOf(sid)}`
                                : `${labelOf(sid)} · 已关总开关，不参与`
                            }
                          >
                            <span className="enrich-strategy__rs-tag-text">
                              {labelOf(sid)}
                            </span>
                            <span
                              role="button"
                              tabIndex={-1}
                              className="enrich-strategy__rs-tag-x"
                              aria-label={`移除 ${labelOf(sid)}`}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                toggleRegionSource(region.id, sid);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  toggleRegionSource(region.id, sid);
                                }
                              }}
                            >
                              <X size={12} strokeWidth={2.4} aria-hidden />
                            </span>
                          </span>
                        ))
                      )}
                    </span>
                    <ChevronDown
                      className={cn(
                        'enrich-strategy__rs-chev',
                        open && 'enrich-strategy__rs-chev--open',
                      )}
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                  {open ? (
                    <div
                      className="enrich-strategy__rs-menu"
                      role="listbox"
                      aria-multiselectable
                      aria-label={`${region.label} 可选源`}
                    >
                      {chain.length > 1 ? (
                        <div className="enrich-strategy__rs-menu-hint">
                          ↑↓ 调序；总开关关闭的源会灰显且不参与刮削
                        </div>
                      ) : null}
                      {chain.map((sid, idx) => (
                        <div
                          key={`${region.id}-sel-${sid}`}
                          className={cn(
                            'enrich-strategy__rs-menu-row enrich-strategy__rs-menu-row--on',
                            !isOn(sid) && 'enrich-strategy__rs-menu-row--off',
                          )}
                        >
                          <button
                            type="button"
                            className="enrich-strategy__rs-menu-main"
                            disabled={busy}
                            onClick={() => toggleRegionSource(region.id, sid)}
                          >
                            <Check
                              className="enrich-strategy__rs-menu-check"
                              size={15}
                              strokeWidth={2.6}
                              aria-hidden
                            />
                            <span>
                              {idx + 1}. {labelOf(sid)}
                              {!isOn(sid) ? ' · 已关' : ''}
                            </span>
                          </button>
                          <span className="enrich-strategy__rs-menu-move">
                            <button
                              type="button"
                              disabled={busy || idx === 0}
                              aria-label="前移"
                              onClick={() =>
                                moveRegionSource(region.id, sid, -1)
                              }
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={busy || idx >= chain.length - 1}
                              aria-label="后移"
                              onClick={() =>
                                moveRegionSource(region.id, sid, 1)
                              }
                            >
                              ↓
                            </button>
                          </span>
                        </div>
                      ))}
                      {sources
                        .filter(
                          (s) =>
                            !chain.includes(s.id) &&
                            !(
                              region.id === 'japan_uncensored' &&
                              officialSet.has(s.id)
                            ),
                        )
                        .map((src) => (
                          <button
                            key={`${region.id}-opt-${src.id}`}
                            type="button"
                            className={cn(
                              'enrich-strategy__rs-menu-row',
                              src.enabled === false &&
                                'enrich-strategy__rs-menu-row--off',
                            )}
                            role="option"
                            aria-selected={false}
                            disabled={busy}
                            onClick={() =>
                              toggleRegionSource(region.id, src.id)
                            }
                          >
                            <span className="enrich-strategy__rs-menu-check enrich-strategy__rs-menu-check--off" />
                            <span>
                              {src.label}
                              {src.enabled === false ? ' · 已关' : ''}
                            </span>
                          </button>
                        ))}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="enrich-strategy__rs-foot">
          <button
            type="button"
            className="enrich-strategy__rs-reset"
            disabled={busy || autoSaving}
            onClick={() => {
              const nextMap: Record<string, string[]> = {};
              for (const r of regions) {
                nextMap[r.id] = [
                  ...(REGION_SOURCE_RESTORE[r.id] ||
                    cfg.regionSourceDefaults?.[r.id] ||
                    []),
                ];
              }
              patchAndPersist((prev) => ({
                ...prev,
                regionSources: nextMap,
                regionSourceDefaults: Object.fromEntries(
                  Object.entries(REGION_SOURCE_RESTORE).map(([k, v]) => [
                    k,
                    [...v],
                  ]),
                ),
                regions: (prev.regions || []).map((r) => ({
                  ...r,
                  sources: [...(nextMap[r.id] || [])],
                })),
              }));
              setRsOpen(null);
            }}
          >
            恢复默认
          </button>
        </div>
      </div>
    );
  }

  function renderFields() {
    if (!cfg) return null;
    const fields = cfg.fieldPriorityFields?.length
      ? cfg.fieldPriorityFields
      : [
          { id: 'title', label: '标题' },
          { id: 'overview', label: '简介' },
          { id: 'poster', label: '海报' },
          { id: 'actors', label: '女优' },
          { id: 'studio', label: '片商' },
          { id: 'maker', label: '制作商' },
          { id: 'date', label: '发行日' },
          { id: 'year', label: '年份' },
          { id: 'tags', label: '标签' },
        ];
    const sources = cfg.sourceOptions?.length ? cfg.sourceOptions : [];
    const labelOf = (sid: string) =>
      sources.find((s) => s.id === sid)?.label || sid;
    const isOn = (sid: string) =>
      sources.find((s) => s.id === sid)?.enabled !== false;
    const visibleFields = fpHideEmpty
      ? fields.filter(
          (f) => ((cfg.fieldPriority || {})[f.id] || []).length > 0,
        )
      : fields;
    const configuredCount = fields.filter(
      (f) => ((cfg.fieldPriority || {})[f.id] || []).length > 0,
    ).length;

    return (
      <div className="enrich-strategy__rs">
        <p className="enrich-strategy__rs-note settings-nav__desc">
          仅对有码区生效；无码 / 素人 / FC2 等只看「优先级设置(全局)」分区源。
        </p>
        <div className="enrich-strategy__rs-toolbar enrich-strategy__rs-toolbar--split">
          <label className="enrich-strategy__rs-hide">
            <span>隐藏未配置</span>
            <Switch
              checked={fpHideEmpty}
              disabled={busy || autoSaving}
              onCheckedChange={(v) => {
                const on = Boolean(v);
                setFpHideEmpty(on);
                patchAndPersist((prev) => ({
                  ...prev,
                  fieldPriorityHideEmpty: on,
                }));
              }}
            />
          </label>
          <span className="enrich-strategy__rs-count">
            {configuredCount}/{fields.length} 已配
          </span>
        </div>
        <ul className="enrich-strategy__rs-list">
          {visibleFields.map((field) => {
            const chain = (cfg.fieldPriority || {})[field.id] || [];
            const open = fpOpen === field.id;
            return (
              <li key={field.id} className="enrich-strategy__rs-row">
                <span className="enrich-strategy__rs-label">{field.label}</span>
                <div
                  className={cn(
                    'enrich-strategy__rs-box',
                    open && 'enrich-strategy__rs-box--open',
                  )}
                  data-enrich-fp-box={field.id}
                >
                  <button
                    type="button"
                    className="enrich-strategy__rs-trigger"
                    disabled={busy}
                    aria-expanded={open}
                    aria-haspopup="listbox"
                    aria-label={`${field.label} 优先级`}
                    onClick={() =>
                      setFpOpen((cur) => (cur === field.id ? null : field.id))
                    }
                  >
                    <span className="enrich-strategy__rs-tags">
                      {chain.length === 0 ? (
                        <span className="enrich-strategy__rs-empty">默认</span>
                      ) : (
                        chain.map((sid, idx) => (
                          <span
                            key={`${field.id}-tag-${sid}`}
                            className={cn(
                              'enrich-strategy__rs-tag',
                              !isOn(sid) && 'enrich-strategy__rs-tag--off',
                            )}
                            title={
                              isOn(sid)
                                ? `${idx + 1}. ${labelOf(sid)}`
                                : `${labelOf(sid)} · 已关总开关，不参与`
                            }
                          >
                            <span className="enrich-strategy__rs-tag-text">
                              {labelOf(sid)}
                            </span>
                            <span
                              role="button"
                              tabIndex={-1}
                              className="enrich-strategy__rs-tag-x"
                              aria-label={`移除 ${labelOf(sid)}`}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                toggleFieldPrioritySite(field.id, sid);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  toggleFieldPrioritySite(field.id, sid);
                                }
                              }}
                            >
                              <X size={11} strokeWidth={2.6} aria-hidden />
                            </span>
                          </span>
                        ))
                      )}
                    </span>
                    <ChevronDown
                      className={cn(
                        'enrich-strategy__rs-chev',
                        open && 'enrich-strategy__rs-chev--open',
                      )}
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                  {open ? (
                    <div
                      className="enrich-strategy__rs-menu"
                      role="listbox"
                      aria-multiselectable
                      aria-label={`${field.label} 可选源`}
                    >
                      {chain.length > 1 ? (
                        <div className="enrich-strategy__rs-menu-hint">
                          ↑↓ 调序；总开关关闭的源会灰显且不参与合并
                        </div>
                      ) : null}
                      {chain.map((sid, idx) => (
                        <div
                          key={`${field.id}-sel-${sid}`}
                          className={cn(
                            'enrich-strategy__rs-menu-row enrich-strategy__rs-menu-row--on',
                            !isOn(sid) && 'enrich-strategy__rs-menu-row--off',
                          )}
                        >
                          <button
                            type="button"
                            className="enrich-strategy__rs-menu-main"
                            disabled={busy}
                            onClick={() =>
                              toggleFieldPrioritySite(field.id, sid)
                            }
                          >
                            <Check
                              className="enrich-strategy__rs-menu-check"
                              size={15}
                              strokeWidth={2.6}
                              aria-hidden
                            />
                            <span>
                              {idx + 1}. {labelOf(sid)}
                              {!isOn(sid) ? ' · 已关' : ''}
                            </span>
                          </button>
                          <span className="enrich-strategy__rs-menu-move">
                            <button
                              type="button"
                              disabled={busy || idx === 0}
                              aria-label="前移"
                              onClick={() =>
                                moveFieldPrioritySite(field.id, sid, -1)
                              }
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={busy || idx >= chain.length - 1}
                              aria-label="后移"
                              onClick={() =>
                                moveFieldPrioritySite(field.id, sid, 1)
                              }
                            >
                              ↓
                            </button>
                          </span>
                        </div>
                      ))}
                      {sources
                        .filter((s) => !chain.includes(s.id))
                        .map((src) => (
                          <button
                            key={`${field.id}-opt-${src.id}`}
                            type="button"
                            className={cn(
                              'enrich-strategy__rs-menu-row',
                              src.enabled === false &&
                                'enrich-strategy__rs-menu-row--off',
                            )}
                            role="option"
                            aria-selected={false}
                            disabled={busy}
                            onClick={() =>
                              toggleFieldPrioritySite(field.id, src.id)
                            }
                          >
                            <span className="enrich-strategy__rs-menu-check enrich-strategy__rs-menu-check--off" />
                            <span>
                              {src.label}
                              {src.enabled === false ? ' · 已关' : ''}
                            </span>
                          </button>
                        ))}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="enrich-strategy__rs-foot">
          <button
            type="button"
            className="enrich-strategy__rs-reset"
            disabled={busy || autoSaving}
            onClick={() => {
              const defaults = FIELD_PRIORITY_RESTORE;
              patchAndPersist((prev) => ({
                ...prev,
                fieldPriority: Object.fromEntries(
                  Object.entries(defaults).map(([k, v]) => [k, [...v]]),
                ),
                fieldPriorityDefaults: Object.fromEntries(
                  Object.entries(defaults).map(([k, v]) => [k, [...v]]),
                ),
              }));
              setFpOpen(null);
            }}
          >
            恢复默认
          </button>
        </div>
      </div>
    );
  }

  function renderMaps() {
    const titleOn = cfg?.localMaps?.title !== 'off';
    const actorsOn = cfg?.localMaps?.actors !== 'off';
    const tagsOn = cfg?.localMaps?.tags !== 'off';
    const nlOn = cfg?.localMaps?.compactOutlineNewlines !== false;

    function patchLocalMaps(
      partial: Partial<NonNullable<ScrapEnrichStrategy['localMaps']>>,
    ) {
      patchAndPersist((prev) => ({
        ...prev,
        localMaps: {
          title: prev.localMaps?.title === 'off' ? 'off' : prev.localMaps?.title === 'force' ? 'force' : 'prefer',
          actors: prev.localMaps?.actors === 'off' ? 'off' : 'fallback',
          tags: prev.localMaps?.tags === 'off' ? 'off' : 'fallback',
          compactOutlineNewlines:
            prev.localMaps?.compactOutlineNewlines !== false,
          ...partial,
        },
      }));
    }

    const rows: Array<{
      key: 'title' | 'actors' | 'tags' | 'nl';
      label: string;
      desc: string;
      checked: boolean;
      onChange: (on: boolean) => void;
    }> = [
      {
        key: 'title',
        label: '色花堂中文标题',
        desc: '源站先出标题，再与映射比分优选（非强制、非兜底）',
        checked: titleOn,
        onChange: (on) =>
          patchLocalMaps({ title: on ? 'prefer' : 'off' }),
      },
      {
        key: 'actors',
        label: '演员数据映射',
        desc: '用内置表规范化演员名（对齐 MDCX）',
        checked: actorsOn,
        onChange: (on) =>
          patchLocalMaps({ actors: on ? 'fallback' : 'off' }),
      },
      {
        key: 'tags',
        label: '标签数据映射',
        desc: '用内置表规范化标签（对齐 MDCX）',
        checked: tagsOn,
        onChange: (on) =>
          patchLocalMaps({ tags: on ? 'fallback' : 'off' }),
      },
      {
        key: 'nl',
        label: '精简多余的换行符',
        desc: '简介中连续换行精简为单个',
        checked: nlOn,
        onChange: (on) =>
          patchLocalMaps({ compactOutlineNewlines: on }),
      },
    ];

    return (
      <>
        <p className="settings-group-label">映射与清洗</p>
        <ul className="settings-group enrich-strategy__fill-group">
          {rows.map((row) => (
            <li key={row.key}>
              <div className="settings-kv enrich-strategy__fill-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">{row.label}</span>
                  <span className="settings-nav__desc enrich-strategy__mode-desc">
                    {row.desc}
                  </span>
                </span>
                <Switch
                  checked={row.checked}
                  disabled={busy || autoSaving}
                  onCheckedChange={row.onChange}
                  aria-label={row.label}
                />
              </div>
            </li>
          ))}
        </ul>
      </>
    );
  }

  function renderCover() {
    if (!cfg) return null;
    const ratio = cfg.cover?.cropRatio === 'emby' ? 'emby' : 'full';
    const ratioHint =
      ratio === 'emby' ? '按 Emby 常见 2:3 裁切' : '保留完整海报比例 2.12:3';
    const cropOpts = cfg.coverCropOptions?.length
      ? cfg.coverCropOptions.filter(
          (o) => o.id === 'right' || o.id === 'face' || o.id === 'none',
        )
      : [
          { id: 'right', label: '右裁' },
          { id: 'face', label: '人脸' },
          { id: 'none', label: '不裁剪' },
        ];
    const enhance = cfg.coverEnhance === 'official' ? 'official' : 'off';
    const enhanceOpts = cfg.coverEnhanceOptions?.length
      ? cfg.coverEnhanceOptions
      : [
          { id: 'off', label: '关闭' },
          { id: 'official', label: '官网/官方CDN' },
        ];

    return (
      <>
        <p className="settings-group-label">落盘规则</p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">图片质量</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  固定省盘；只留 poster.jpg。右裁/人脸：pl 优先，ps
                  过小丢弃后横图裁（不改高度）；不裁剪：只要网站横图
                </span>
              </span>
              <div className="enrich-strategy__chips" role="group" aria-label="图片质量">
                <span className="enrich-strategy__chip enrich-strategy__chip--on">
                  省盘
                </span>
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">裁剪比例</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {ratioHint}
                </span>
              </span>
              <SegTwo
                ariaLabel="裁剪比例"
                value={ratio}
                left={{ id: 'full', label: '完整' }}
                right={{ id: 'emby', label: 'Emby' }}
                disabled={busy}
                onChange={(id) =>
                  setCoverRatio(id === 'emby' ? 'emby' : 'full')
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">官方升清</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  短边不达标时试官网/官方 CDN（不开 Amazon/Google）
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="官方升清"
              >
                {enhanceOpts.map((opt) => {
                  const on = enhance === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          coverEnhance:
                            opt.id === 'official' ? 'official' : 'off',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">批量重压海报</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {recompressHint ||
                    '按省盘重压已落盘 poster.jpg，不改构图；体积几乎不降则跳过'}
                </span>
              </span>
              <div className="enrich-strategy__chips" role="group">
                <button
                  type="button"
                  className="enrich-strategy__chip"
                  disabled={busy || recompressBusy}
                  onClick={() => void onRecompressPosters(true)}
                >
                  预览
                </button>
                <button
                  type="button"
                  className="enrich-strategy__chip enrich-strategy__chip--on"
                  disabled={busy || recompressBusy}
                  onClick={() => void onRecompressPosters(false)}
                >
                  {recompressBusy ? '处理中…' : '开始重压'}
                </button>
              </div>
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          六区封面逻辑
        </p>
        <div className="enrich-strategy__cover-regions">
          {regions.map((region) => {
            const raw = cfg.cover?.regionCrop?.[region.id] || 'right';
            const cropMode =
              raw === 'face' ? 'face' : raw === 'none' ? 'none' : 'right';
            const activeOpt = cropOpts.find((o) => o.id === cropMode);
            return (
              <section
                key={`cover-${region.id}`}
                className="enrich-strategy__region"
                aria-label={`${region.label} 封面`}
              >
                <header className="enrich-strategy__region-head">
                  <div className="enrich-strategy__region-head-main">
                    <h3 className="enrich-strategy__region-title">
                      {region.label}
                      {region.coverHint ? (
                        <span className="enrich-strategy__region-hint">
                          {region.coverHint}
                        </span>
                      ) : null}
                    </h3>
                  </div>
                  <span className="enrich-strategy__region-count enrich-strategy__region-count--on">
                    {activeOpt?.label || '右裁'}
                  </span>
                </header>
                <div
                  className="enrich-strategy__chips"
                  role="radiogroup"
                  aria-label={`${region.label} 封面裁剪`}
                >
                  {cropOpts.map((opt) => {
                    const on = cropMode === opt.id;
                    return (
                      <button
                        key={`${region.id}-${opt.id}`}
                        type="button"
                        className={cn(
                          'enrich-strategy__chip',
                          on && 'enrich-strategy__chip--on',
                        )}
                        disabled={busy}
                        role="radio"
                        aria-checked={on}
                        onClick={() => setRegionCoverCrop(region.id, opt.id)}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </>
    );
  }

  const sectionTitle: Record<SectionId, string> = {
    fill: '补齐与女优',
    schedule: '调度与并发',
    regions: '优先级设置(全局)',
    fields: '字段优先级',
    maps: '元数据优化',
    cover: '刮削封面',
  };

  if (section) {
    return (
      <AppPush
        title={sectionTitle[section]}
        onBack={() => {
          flushPendingPersist();
          setSection(null);
          setFpOpen(null);
          setRsOpen(null);
        }}
        skipEnterAnimation
        scrollKey={`enrich-strategy-${section}`}
      >
        <div className="makers-manage makers-manage--detail enrich-strategy">
          {msg ? (
            <AppMsg
              allowSelect
              tone={
                msg === '已保存' || msg === '已自动保存' ? 'ok' : 'warn'
              }
              onDismiss={() => setMsg('')}
            >
              {msg}
            </AppMsg>
          ) : null}
          {!cfg ? (
            <p className="settings-group-label">加载中…</p>
          ) : (
            <>
              {section === 'fill'
                ? renderFill()
                : section === 'schedule'
                  ? renderSchedule()
                  : section === 'regions'
                    ? renderRegions()
                    : section === 'fields'
                      ? renderFields()
                      : section === 'maps'
                        ? renderMaps()
                        : renderCover()}
              <div className="app-actions">
                <button
                  type="button"
                  className="app-btn-primary"
                  disabled={busy}
                  onClick={() => void onSave()}
                >
                  {busy ? '保存中…' : '保存'}
                </button>
              </div>
            </>
          )}
        </div>
      </AppPush>
    );
  }

  return (
    <AppPush title="刮削策略" onBack={onBack}>
      <div className="makers-manage makers-manage--detail enrich-strategy">
        {msg ? (
          <AppMsg
            allowSelect
            tone={
              msg === '已保存' || msg === '已自动保存' ? 'ok' : 'warn'
            }
            onDismiss={() => setMsg('')}
          >
            {msg}
          </AppMsg>
        ) : null}

        {!cfg ? (
          <p className="settings-group-label">加载中…</p>
        ) : (
          <>
            <p className="settings-group-label">策略分组</p>
            <ul className="settings-group makers-manage__rise">
              {hubRows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="settings-nav makers-manage__catalog-row"
                    disabled={busy}
                    onClick={() => {
                      setSection(row.id);
                      setFpOpen(null);
                    }}
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{row.title}</span>
                      <span className="settings-nav__desc">{row.desc}</span>
                    </span>
                    <ChevronRight
                      className="settings-nav__chev"
                      size={17}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                </li>
              ))}
            </ul>

            <div className="app-actions">
              <button
                type="button"
                className="app-btn-primary"
                disabled={busy}
                onClick={() => void onSave()}
              >
                {busy ? '保存中…' : '保存'}
              </button>
            </div>
          </>
        )}
      </div>
    </AppPush>
  );
}
