'use client';

import { useEffect, useState } from 'react';
import {
  getNetwork,
  putNetwork,
  testFlareSolverr,
  testNetwork,
  type NetworkConfig,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

function toProxyHostPort(raw: string): string {
  const s = raw.trim();
  if (!s) return '';
  try {
    const u = new URL(s.includes('://') ? s : `http://${s}`);
    return u.host || u.hostname;
  } catch {
    return s.replace(/^https?:\/\//i, '').replace(/\/$/, '');
  }
}

function parseProxyParts(raw: string): { host: string; port: string } {
  const hostPort = toProxyHostPort(raw);
  if (!hostPort) return { host: '', port: '' };

  const bracket = hostPort.match(/^\[([^\]]+)\](?::(\d{1,5}))?$/);
  if (bracket) return { host: bracket[1], port: bracket[2] || '' };

  const colon = hostPort.lastIndexOf(':');
  if (colon > 0) {
    const port = hostPort.slice(colon + 1);
    if (/^\d{1,5}$/.test(port)) {
      return { host: hostPort.slice(0, colon), port };
    }
  }
  return { host: hostPort, port: '' };
}

function joinProxy(host: string, port: string): string {
  const h = host.trim();
  const p = port.trim();
  if (!h) return '';
  if (!p) return h;
  if (h.includes(':') && !h.startsWith('[')) return `[${h}]:${p}`;
  return `${h}:${p}`;
}

export function NetworkPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [effective, setEffective] = useState('');
  const [flareHost, setFlareHost] = useState('127.0.0.1');
  const [flarePort, setFlarePort] = useState('8191');
  const [flareEnabled, setFlareEnabled] = useState(false);
  const [flareEffective, setFlareEffective] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  function hubStatus(d: NetworkConfig) {
    const proxyOn = Boolean(d.proxyEnabled) && Boolean(d.proxyUrl);
    const flareOn = Boolean(d.flareSolverrConfigured);
    if (proxyOn && flareOn) return { text: '代理 · Flare', tone: 'ok' as const };
    if (proxyOn) return { text: '代理已启用', tone: 'ok' as const };
    if (flareOn) return { text: 'Flare 已启用', tone: 'ok' as const };
    return { text: '未启用', tone: 'warn' as const };
  }

  function applyPublic(d: NetworkConfig) {
    const parts = parseProxyParts(d.proxyUrl || '');
    setHost(parts.host);
    setPort(parts.port);
    const on = Boolean(d.proxyEnabled) && Boolean(parts.host);
    setEnabled(Boolean(d.proxyEnabled));
    setEffective(
      toProxyHostPort(d.effectiveProxyUrl || (on ? d.proxyUrl || '' : '')),
    );

    const flareParts = parseProxyParts(d.flareSolverrUrl || '');
    setFlareHost(flareParts.host || '127.0.0.1');
    setFlarePort(flareParts.port || '8191');
    setFlareEnabled(Boolean(d.flareSolverrEnabled));
    setFlareEffective(toProxyHostPort(d.effectiveFlareSolverrUrl || ''));

    const st = hubStatus(d);
    onStatus(st.text, st.tone);
  }

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const d = await getNetwork();
        applyPublic(d);
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
        onStatus('异常', 'warn');
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function proxyValue() {
    return joinProxy(host, port);
  }

  function flareValue() {
    return joinProxy(flareHost, flarePort || '8191');
  }

  async function persist(partial: {
    proxyEnabled?: boolean;
    proxyUrl?: string;
    flareSolverrEnabled?: boolean;
    flareSolverrUrl?: string;
  }) {
    setBusy(true);
    setMsg('');
    try {
      const next = await putNetwork({
        proxyUrl: partial.proxyUrl ?? proxyValue(),
        proxyEnabled: partial.proxyEnabled ?? enabled,
        flareSolverrUrl: partial.flareSolverrUrl ?? flareValue(),
        flareSolverrEnabled: partial.flareSolverrEnabled ?? flareEnabled,
      });
      applyPublic(next);
      return next;
    } finally {
      setBusy(false);
    }
  }

  async function onToggle(next: boolean) {
    if (next && !proxyValue()) {
      setMsg('请先填写主机和端口');
      return;
    }
    try {
      const saved = await persist({ proxyEnabled: next });
      setMsg(saved.configured ? '已启用代理' : '已关闭代理');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    }
  }

  async function onToggleFlare(next: boolean) {
    if (next && !flareValue()) {
      setMsg('请先填写 FlareSolverr 主机和端口');
      return;
    }
    try {
      const saved = await persist({
        flareSolverrEnabled: next,
        flareSolverrUrl: flareValue(),
      });
      setMsg(saved.flareSolverrConfigured ? '已启用过盾' : '已关闭过盾');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    }
  }

  async function onTest() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testNetwork({ proxyUrl: proxyValue() });
      setMsg(r.message || (r.ok ? '代理正常' : '代理失败'));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '代理测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onTestFlare() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testFlareSolverr({ flareSolverrUrl: flareValue() });
      setMsg(r.message || (r.ok ? 'FlareSolverr 正常' : 'FlareSolverr 失败'));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'FlareSolverr 测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    try {
      const url = proxyValue();
      const flare = flareValue();
      const saved = await persist({
        proxyUrl: url,
        proxyEnabled: Boolean(url) && enabled,
        flareSolverrUrl: flare,
        flareSolverrEnabled: Boolean(flare) && flareEnabled,
      });
      const bits: string[] = [];
      if (saved.configured) bits.push('代理已启用');
      else if (url) bits.push('代理已保存未启用');
      if (saved.flareSolverrConfigured) bits.push('过盾已启用');
      else if (flare) bits.push('过盾已保存未启用');
      setMsg(bits.length ? bits.join(' · ') : '已清空');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    }
  }

  const active = enabled && Boolean(proxyValue());
  const flareActive = flareEnabled && Boolean(flareValue());
  const locked = busy || loading;

  return (
    <AppPush title="网络代理" onBack={onBack}>
      <div className="network-panel">
        <ul className="settings-group">
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">状态</span>
              <span
                className={cn(
                  'settings-nav__status',
                  active || flareActive
                    ? 'settings-nav__status--ok'
                    : 'settings-nav__status--warn',
                )}
              >
                {loading
                  ? '…'
                  : active && flareActive
                    ? '代理 · Flare'
                    : active
                      ? '代理已启用'
                      : flareActive
                        ? 'Flare 已启用'
                        : '未启用'}
              </span>
            </div>
          </li>
        </ul>

        <p className="settings-group-label">HTTP 代理</p>
        <ul className="settings-group">
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">启用代理</span>
              <Switch
                checked={enabled}
                onCheckedChange={(v) => void onToggle(Boolean(v))}
                disabled={locked}
              />
            </div>
          </li>
          {effective ? (
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">生效中</span>
                <span className="settings-kv__val allow-select">{effective}</span>
              </div>
            </li>
          ) : null}
        </ul>
        <section className="app-section network-proxy-card">
          <div className="app-section-body">
            <label className="app-field">
              <span className="app-label">主机</span>
              <input
                type="text"
                className="allow-select"
                placeholder="127.0.0.1"
                value={host}
                onChange={(e) => setHost(e.target.value.trim())}
                autoCapitalize="off"
                autoCorrect="off"
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
              />
            </label>
            <label className="app-field network-proxy-card__port">
              <span className="app-label">端口</span>
              <input
                type="text"
                className="allow-select"
                placeholder="7890"
                value={port}
                onChange={(e) =>
                  setPort(e.target.value.replace(/[^\d]/g, '').slice(0, 5))
                }
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
              />
            </label>
          </div>
        </section>
        <div className="app-actions">
          <button
            type="button"
            className="app-btn-secondary"
            disabled={locked}
            onClick={() => void onTest()}
          >
            测试代理
          </button>
        </div>

        <p className="settings-group-label settings-group-label--spaced">
          FlareSolverr
        </p>
        <ul className="settings-group">
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">启用过盾</span>
              <Switch
                checked={flareEnabled}
                onCheckedChange={(v) => void onToggleFlare(Boolean(v))}
                disabled={locked}
              />
            </div>
          </li>
          {flareEffective ? (
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">生效中</span>
                <span className="settings-kv__val allow-select">
                  {flareEffective}
                </span>
              </div>
            </li>
          ) : null}
        </ul>
        <section className="app-section network-proxy-card">
          <div className="app-section-body">
            <label className="app-field">
              <span className="app-label">主机</span>
              <input
                type="text"
                className="allow-select"
                placeholder="127.0.0.1"
                value={flareHost}
                onChange={(e) => setFlareHost(e.target.value.trim())}
                autoCapitalize="off"
                autoCorrect="off"
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
              />
            </label>
            <label className="app-field network-proxy-card__port">
              <span className="app-label">端口</span>
              <input
                type="text"
                className="allow-select"
                placeholder="8191"
                value={flarePort}
                onChange={(e) =>
                  setFlarePort(e.target.value.replace(/[^\d]/g, '').slice(0, 5))
                }
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
              />
            </label>
          </div>
        </section>
        <div className="app-actions">
          <button
            type="button"
            className="app-btn-secondary"
            disabled={locked}
            onClick={() => void onTestFlare()}
          >
            测试 Flare
          </button>
          <button
            type="button"
            className="app-btn-primary"
            disabled={locked}
            onClick={() => void onSave()}
          >
            保存
          </button>
        </div>

        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </div>
    </AppPush>
  );
}
