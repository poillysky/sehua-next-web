'use client';

import { useEffect, useState } from 'react';
import {
  getScrapEnrichStrategy,
  putScrapEnrichStrategy,
  type ScrapEnrichStrategy,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

function cloneStrategy(s: ScrapEnrichStrategy): ScrapEnrichStrategy {
  return {
    ...s,
    regionGroups: Object.fromEntries(
      Object.entries(s.regionGroups || {}).map(([k, v]) => [k, [...(v || [])]]),
    ),
    regionsEnabled: { ...(s.regionsEnabled || {}) },
    fillMode: s.fillMode === 'overwrite' ? 'overwrite' : 'incremental',
    llmTranslateOnJunk: s.llmTranslateOnJunk !== false,
    cover: {
      quality: s.cover?.quality === 'low' ? 'low' : 'high',
      cropRatio: s.cover?.cropRatio === 'emby' ? 'emby' : 'full',
      regionCrop: { ...(s.cover?.regionCrop || {}) },
    },
    coverCropOptions: [...(s.coverCropOptions || [])],
    coverQualityOptions: [...(s.coverQualityOptions || [])],
    coverRatioOptions: [...(s.coverRatioOptions || [])],
    regions: (s.regions || []).map((r) => ({
      ...r,
      groups: [...(r.groups || [])],
    })),
  };
}

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

function digitsOnly(raw: string) {
  return String(raw || '').replace(/[^\d]/g, '');
}

function clampInt(raw: string, fallback: number, min: number, max: number) {
  const n = Number(digitsOnly(raw));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

export function EnrichStrategyPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [cfg, setCfg] = useState<ScrapEnrichStrategy | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [adaptiveWorkersText, setAdaptiveWorkersText] = useState('');
  const [flareWorkersText, setFlareWorkersText] = useState('');
  const [timeoutText, setTimeoutText] = useState('');

  function syncNumDrafts(s: ScrapEnrichStrategy) {
    setAdaptiveWorkersText(String(s.adaptiveWorkers ?? 0));
    setFlareWorkersText(String(s.flareWorkers ?? 0));
    setTimeoutText(String(s.perSourceTimeoutSec ?? 45));
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getScrapEnrichStrategy();
        if (!cancelled) {
          const next = cloneStrategy(data);
          setCfg(next);
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

  function toggleRegionGroup(regionId: string, groupId: string) {
    setCfg((prev) => {
      if (!prev) return prev;
      const cur = [...(prev.regionGroups[regionId] || [])];
      const i = cur.indexOf(groupId);
      if (i >= 0) cur.splice(i, 1);
      else cur.push(groupId);
      const regionGroups = { ...prev.regionGroups, [regionId]: cur };
      const regions = (prev.regions || []).map((r) =>
        r.id === regionId ? { ...r, groups: cur } : r,
      );
      return { ...prev, regionGroups, regions };
    });
  }

  function setCoverQuality(quality: 'high' | 'low') {
    setCfg((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        cover: {
          quality,
          cropRatio: prev.cover?.cropRatio === 'emby' ? 'emby' : 'full',
          regionCrop: { ...(prev.cover?.regionCrop || {}) },
        },
      };
    });
  }

  function setCoverRatio(cropRatio: 'full' | 'emby') {
    setCfg((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        cover: {
          quality: prev.cover?.quality === 'low' ? 'low' : 'high',
          cropRatio,
          regionCrop: { ...(prev.cover?.regionCrop || {}) },
        },
      };
    });
  }

  function setRegionCoverCrop(regionId: string, mode: string) {
    setCfg((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        cover: {
          quality: prev.cover?.quality === 'low' ? 'low' : 'high',
          cropRatio: prev.cover?.cropRatio === 'emby' ? 'emby' : 'full',
          regionCrop: {
            ...(prev.cover?.regionCrop || {}),
            [regionId]: mode,
          },
        },
      };
    });
  }

  async function onSave() {
    if (!cfg || busy) return;
    const adaptiveWorkers = commitAdaptiveWorkers();
    const flareWorkers = commitFlareWorkers();
    const perSourceTimeoutSec = commitTimeout();
    const payload = {
      ...cfg,
      adaptiveWorkers,
      flareWorkers,
      perSourceTimeoutSec,
    };
    setBusy(true);
    setMsg('');
    try {
      const saved = await putScrapEnrichStrategy(payload);
      const next = cloneStrategy(saved);
      setCfg(next);
      syncNumDrafts(next);
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

  const groupOptions = cfg?.groupOptions || [];
  const regions = cfg?.regions || [];
  const mode = cfg?.mode || 'parallel_all';
  const modeMeta =
    MODE_OPTIONS.find((m) => m.value === mode) || MODE_OPTIONS[0];
  const allowFlare = mode !== 'adaptive_only';
  const flareOn = allowFlare && Boolean(cfg?.includeFlare);
  const showFlareWorkers = mode === 'adaptive_first' && flareOn;

  return (
    <AppPush title="刮削策略" onBack={onBack}>
      <div className="makers-manage makers-manage--detail enrich-strategy">
        {msg ? (
          <AppMsg
            allowSelect
            tone={msg === '已保存' ? 'ok' : 'warn'}
            onDismiss={() => setMsg('')}
          >
            {msg}
          </AppMsg>
        ) : null}

        {!cfg ? (
          <p className="settings-group-label">加载中…</p>
        ) : (
          <>
            <p className="settings-group-label">调度模式</p>
            <div
              className="app-seg enrich-strategy__seg"
              role="radiogroup"
              aria-label="调度模式"
            >
              {MODE_OPTIONS.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  className={cn(
                    'app-seg__btn',
                    mode === m.value && 'app-seg__btn--active',
                  )}
                  disabled={busy}
                  role="radio"
                  aria-checked={mode === m.value}
                  onClick={() => setMode(m.value)}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <p className="enrich-strategy__caption enrich-strategy__caption--mode">
              {modeMeta.desc}
            </p>

            {allowFlare ? (
              <ul className="settings-group">
                <li>
                  <div className="settings-kv enrich-strategy__mode-row">
                    <span className="settings-nav__main">
                      <span className="settings-kv__key">包含过盾源</span>
                      <span className="settings-nav__desc enrich-strategy__mode-desc">
                        {mode === 'adaptive_first'
                          ? '自适应阶段未补齐时，继续调度 Flare / 过盾源'
                          : '过盾源与自适应源一并参与并发'}
                      </span>
                    </span>
                    <Switch
                      checked={flareOn}
                      disabled={busy}
                      onCheckedChange={(v) =>
                        patch({ includeFlare: Boolean(v) })
                      }
                    />
                  </div>
                </li>
              </ul>
            ) : null}

            <p className="settings-group-label settings-group-label--spaced">
              中文补译
            </p>
            <ul className="settings-group">
              <li>
                <div className="settings-kv enrich-strategy__mode-row">
                  <span className="settings-nav__main">
                    <span className="settings-kv__key">机翻过烂时大模型译中</span>
                    <span className="settings-nav__desc enrich-strategy__mode-desc">
                      合并结果仍是日文，或中文机翻垃圾（如「男孩子女孩」）时，自动用设置里的
                      LLM 译标题/剧情；失败再回落机翻级联
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
                  <span className="settings-kv__key">
                    {mode === 'parallel_all' && flareOn
                      ? '并发上限'
                      : '自适应并发'}
                    <span className="enrich-strategy__key-hint">（0 = 不限制）</span>
                  </span>
                  <input
                    type="text"
                    className="allow-select enrich-strategy__num"
                    inputMode="numeric"
                    value={adaptiveWorkersText}
                    disabled={busy}
                    aria-label={
                      mode === 'parallel_all' && flareOn
                        ? '并发上限'
                        : '自适应并发'
                    }
                    onChange={(e) => setAdaptiveWorkersText(digitsOnly(e.target.value))}
                    onBlur={() => commitAdaptiveWorkers()}
                  />
                </label>
              </li>
              {showFlareWorkers ? (
                <li>
                  <label className="settings-kv enrich-strategy__param-row">
                    <span className="settings-kv__key">
                      过盾并发
                      <span className="enrich-strategy__key-hint">（0 = 不限制）</span>
                    </span>
                    <input
                      type="text"
                      className="allow-select enrich-strategy__num"
                      inputMode="numeric"
                      value={flareWorkersText}
                      disabled={busy}
                      aria-label="过盾并发"
                      onChange={(e) => setFlareWorkersText(digitsOnly(e.target.value))}
                      onBlur={() => commitFlareWorkers()}
                    />
                  </label>
                </li>
              ) : null}
              <li>
                <label className="settings-kv enrich-strategy__param-row">
                  <span className="settings-kv__key">
                    单源超时
                    <span className="enrich-strategy__key-hint">（秒）</span>
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

            <p className="settings-group-label settings-group-label--spaced">
              七区数据源
            </p>
            <p className="enrich-strategy__caption">
              按分区勾选参与补全的目录分组；未启用或未实现详情的源不会参与。
            </p>
            <div className="enrich-strategy__regions">
              {regions.map((region) => {
                const selected = cfg.regionGroups[region.id] || [];
                return (
                  <section
                    key={region.id}
                    className="enrich-strategy__region"
                    aria-label={region.label}
                  >
                    <header className="enrich-strategy__region-head">
                      <h3 className="enrich-strategy__region-title">
                        {region.label}
                      </h3>
                      <span className="enrich-strategy__region-count">
                        {selected.length}/{groupOptions.length}
                      </span>
                    </header>
                    <div
                      className="enrich-strategy__chips"
                      role="group"
                      aria-label={`${region.label} 数据源分组`}
                    >
                      {groupOptions.map((g) => {
                        const on = selected.includes(g.id);
                        return (
                          <button
                            key={`${region.id}-${g.id}`}
                            type="button"
                            className={cn(
                              'enrich-strategy__chip',
                              on && 'enrich-strategy__chip--on',
                            )}
                            disabled={busy}
                            aria-pressed={on}
                            onClick={() => toggleRegionGroup(region.id, g.id)}
                          >
                            {g.label}
                          </button>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>

            <p className="settings-group-label settings-group-label--spaced">
              刮削封面参数
            </p>
            <p className="enrich-strategy__caption">
              本地番号目录只保留一张 poster.jpg；需裁剪时落盘的就是裁剪后的图。
            </p>

            <p className="enrich-strategy__sublabel">图片质量</p>
            <div
              className="app-seg enrich-strategy__seg"
              role="radiogroup"
              aria-label="图片质量"
            >
              {(
                cfg.coverQualityOptions?.length
                  ? cfg.coverQualityOptions
                  : [
                      { id: 'high', label: '高画质' },
                      { id: 'low', label: '低画质' },
                    ]
              ).map((q) => {
                const active =
                  (cfg.cover?.quality || 'high') === q.id;
                return (
                  <button
                    key={q.id}
                    type="button"
                    className={cn(
                      'app-seg__btn',
                      active && 'app-seg__btn--active',
                    )}
                    disabled={busy}
                    role="radio"
                    aria-checked={active}
                    onClick={() =>
                      setCoverQuality(q.id === 'low' ? 'low' : 'high')
                    }
                  >
                    {q.label}
                  </button>
                );
              })}
            </div>

            <p className="enrich-strategy__sublabel enrich-strategy__sublabel--spaced">
              裁剪比例
            </p>
            <div
              className="app-seg enrich-strategy__seg"
              role="radiogroup"
              aria-label="裁剪比例"
            >
              {(
                cfg.coverRatioOptions?.length
                  ? cfg.coverRatioOptions
                  : [
                      { id: 'full', label: '完整海报（2.12:3）' },
                      { id: 'emby', label: 'Emby 比例（2:3）' },
                    ]
              ).map((r) => {
                const active =
                  (cfg.cover?.cropRatio || 'full') === r.id;
                return (
                  <button
                    key={r.id}
                    type="button"
                    className={cn(
                      'app-seg__btn',
                      active && 'app-seg__btn--active',
                    )}
                    disabled={busy}
                    role="radio"
                    aria-checked={active}
                    onClick={() =>
                      setCoverRatio(r.id === 'emby' ? 'emby' : 'full')
                    }
                  >
                    {r.label}
                  </button>
                );
              })}
            </div>

            <p className="enrich-strategy__sublabel enrich-strategy__sublabel--spaced">
              七区封面逻辑
            </p>
            <div className="enrich-strategy__cover-regions">
              {regions.map((region) => {
                const cropMode =
                  cfg.cover?.regionCrop?.[region.id] || 'none';
                const cropOpts =
                  cfg.coverCropOptions?.length
                    ? cfg.coverCropOptions
                    : [
                        { id: 'right', label: '右侧裁剪' },
                        {
                          id: 'face',
                          label: '人脸识别（失败则居中）',
                        },
                        { id: 'none', label: '不裁剪' },
                      ];
                return (
                  <section
                    key={`cover-${region.id}`}
                    className="enrich-strategy__region"
                    aria-label={`${region.label} 封面`}
                  >
                    <header className="enrich-strategy__region-head">
                      <h3 className="enrich-strategy__region-title">
                        {region.label}
                      </h3>
                    </header>
                    {region.coverHint ? (
                      <p className="enrich-strategy__caption enrich-strategy__caption--inline">
                        {region.coverHint}
                      </p>
                    ) : null}
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
                            onClick={() =>
                              setRegionCoverCrop(region.id, opt.id)
                            }
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
