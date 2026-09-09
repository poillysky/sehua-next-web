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

function cloneStrategy(s: ScrapEnrichStrategy): ScrapEnrichStrategy {
  return {
    ...s,
    regionGroups: Object.fromEntries(
      Object.entries(s.regionGroups || {}).map(([k, v]) => [k, [...(v || [])]]),
    ),
    regions: (s.regions || []).map((r) => ({
      ...r,
      groups: [...(r.groups || [])],
    })),
  };
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

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getScrapEnrichStrategy();
        if (!cancelled) setCfg(cloneStrategy(data));
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

  async function onSave() {
    if (!cfg || busy) return;
    setBusy(true);
    setMsg('');
    try {
      const saved = await putScrapEnrichStrategy(cfg);
      setCfg(cloneStrategy(saved));
      onStatus('补全并发策略已保存', 'ok');
      setMsg('已保存');
    } catch (e) {
      const text = e instanceof Error ? e.message : '保存失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setBusy(false);
    }
  }

  const modes = cfg?.modes || [
    { value: 'parallel_all', label: '全部并发' },
    { value: 'adaptive_first', label: '自适应优先' },
    { value: 'adaptive_only', label: '仅自适应' },
  ];
  const groupOptions = cfg?.groupOptions || [];
  const regions = cfg?.regions || [];

  return (
    <AppPush title="补全并发策略" onBack={onBack}>
      {msg ? (
        <AppMsg tone={msg === '已保存' ? 'ok' : 'warn'}>{msg}</AppMsg>
      ) : null}

      {!cfg ? (
        <p className="settings-group-label">加载中…</p>
      ) : (
        <>
          <p className="settings-group-label">调度模式</p>
          <ul className="settings-group">
            {modes.map((m) => (
              <li key={m.value}>
                <button
                  type="button"
                  className="settings-nav"
                  disabled={busy}
                  aria-pressed={cfg.mode === m.value}
                  onClick={() => patch({ mode: m.value })}
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{m.label}</span>
                    <span className="settings-nav__desc">
                      {m.value === 'parallel_all'
                        ? '该番号匹配源一起并发（并发数按下方配置，0=全开）'
                        : m.value === 'adaptive_first'
                          ? '先跑自适应；有封面则跳过过盾'
                          : '只请求自适应源，不过盾'}
                    </span>
                  </span>
                  <span className="settings-nav__status">
                    {cfg.mode === m.value ? '当前' : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <p className="settings-group-label settings-group-label--spaced">
            并发参数
          </p>
          <section className="app-section network-proxy-card">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">自适应并发（0=全开）</span>
                <input
                  type="text"
                  className="allow-select"
                  inputMode="numeric"
                  value={String(cfg.adaptiveWorkers)}
                  disabled={busy}
                  onChange={(e) =>
                    patch({
                      adaptiveWorkers: Number(
                        e.target.value.replace(/[^\d]/g, '') || 0,
                      ),
                    })
                  }
                />
              </label>
              <label className="app-field">
                <span className="app-label">过盾并发（0=全开）</span>
                <input
                  type="text"
                  className="allow-select"
                  inputMode="numeric"
                  value={String(cfg.flareWorkers)}
                  disabled={busy || !cfg.includeFlare}
                  onChange={(e) =>
                    patch({
                      flareWorkers: Number(
                        e.target.value.replace(/[^\d]/g, '') || 0,
                      ),
                    })
                  }
                />
              </label>
              <label className="app-field">
                <span className="app-label">单源超时(秒)</span>
                <input
                  type="text"
                  className="allow-select"
                  inputMode="numeric"
                  value={String(cfg.perSourceTimeoutSec)}
                  disabled={busy}
                  onChange={(e) =>
                    patch({
                      perSourceTimeoutSec: Number(
                        e.target.value.replace(/[^\d]/g, '') || 45,
                      ),
                    })
                  }
                />
              </label>
            </div>
          </section>
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">包含过盾源</span>
                <Switch
                  checked={cfg.includeFlare}
                  disabled={busy || cfg.mode === 'adaptive_only'}
                  onCheckedChange={(v) => patch({ includeFlare: Boolean(v) })}
                />
              </div>
            </li>
          </ul>

          <p className="settings-group-label settings-group-label--spaced">
            七区 → 数据源分组
          </p>
          <p className="settings-group-label" style={{ opacity: 0.72, fontWeight: 400 }}>
            仅已启用且有详情实现的源会参与；分组决定每个区拉哪些目录源。
          </p>
          {regions.map((region) => (
            <div key={region.id}>
              <p className="settings-group-label">{region.label}</p>
              <ul className="settings-group">
                {groupOptions.map((g) => {
                  const on = (cfg.regionGroups[region.id] || []).includes(g.id);
                  return (
                    <li key={`${region.id}-${g.id}`}>
                      <div className="settings-kv">
                        <span className="settings-kv__key">{g.label}</span>
                        <Switch
                          checked={on}
                          disabled={busy}
                          onCheckedChange={() =>
                            toggleRegionGroup(region.id, g.id)
                          }
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

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
    </AppPush>
  );
}
