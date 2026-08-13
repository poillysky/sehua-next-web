'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  getFlareMonitor,
  getScrape,
  putScrape,
  recycleFlareSolverr,
  restartFlareSolverr,
  testFlareSolverr,
  testScrapeProxy,
  type FlareMonitorSnapshot,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';

const FLARE_DEFAULT = '127.0.0.1:8191';
const PROXY_PLACEHOLDER = '127.0.0.1:7890';

/** 展示/编辑用 host:port，后端会自动补 http:// 与 /v1 */
function toHostPort(raw: string): string {
  const s = raw.trim();
  if (!s) return '';
  try {
    const u = new URL(s.includes('://') ? s : `http://${s}`);
    if (u.port) return `${u.hostname}:${u.port}`;
    return u.hostname;
  } catch {
    return s
      .replace(/^https?:\/\//i, '')
      .replace(/\/v1\/?$/i, '')
      .replace(/\/$/, '');
  }
}

function toProxyHostPort(raw: string): string {
  const s = raw.trim();
  if (!s) return '';
  try {
    const u = new URL(s.includes('://') ? s : `http://${s}`);
    if (u.port) return `${u.hostname}:${u.port}`;
    return u.hostname;
  } catch {
    return s.replace(/^https?:\/\//i, '').replace(/\/$/, '');
  }
}

function statusLabel(flare: string, proxy: string): { text: string; tone: 'ok' | 'warn' } {
  const f = Boolean(flare.trim());
  const p = Boolean(proxy.trim());
  if (f && p) return { text: '已就绪', tone: 'ok' };
  if (f) return { text: '过盾已配', tone: 'ok' };
  if (p) return { text: '代理已配', tone: 'ok' };
  return { text: '未配置', tone: 'warn' };
}

function levelLabel(level: FlareMonitorSnapshot['level'] | undefined): string {
  if (level === 'ok') return '正常';
  if (level === 'warn') return '偏高';
  if (level === 'critical') return '过载';
  if (level === 'down') return '离线';
  return '—';
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${Math.round(n)}%`;
}

function fmtMs(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return '—';
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(1)}s`;
}

/** 网络管理：过盾 + 代理（原 FlareSolverr 入口） */
export function FlareSolverrPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [flare, setFlare] = useState('');
  const [proxy, setProxy] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mon, setMon] = useState<FlareMonitorSnapshot | null>(null);

  function publish(nextFlare: string, nextProxy: string) {
    const st = statusLabel(nextFlare, nextProxy);
    onStatus(st.text, st.tone);
  }

  const refreshMonitor = useCallback(async () => {
    try {
      const d = await getFlareMonitor();
      setMon(d);
    } catch {
      /* 刮削未起时忽略 */
    }
  }, []);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const d = await getScrape();
        const nextFlare = toHostPort(d.flareSolverrUrl || '');
        const nextProxy = toProxyHostPort(d.proxyUrl || '');
        setFlare(nextFlare);
        setProxy(nextProxy);
        publish(nextFlare, nextProxy);
        await refreshMonitor();
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setInterval(() => void refreshMonitor(), 15000);
    return () => clearInterval(t);
  }, [refreshMonitor]);

  async function onTestProxy() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testScrapeProxy({ proxyUrl: proxy.trim() });
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
      const r = await testFlareSolverr({
        flareSolverrUrl: flare.trim(),
        proxyUrl: proxy.trim(),
      });
      setMsg(r.message || (r.ok ? '过盾正常' : '过盾失败'));
      await refreshMonitor();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '过盾测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onRecycle() {
    setBusy(true);
    setMsg('');
    try {
      const r = await recycleFlareSolverr();
      setMon(r.data);
      setMsg(r.message || '已回收会话');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '回收失败');
    } finally {
      setBusy(false);
    }
  }

  async function onRestart() {
    setBusy(true);
    setMsg('');
    try {
      const r = await restartFlareSolverr();
      setMon(r.data);
      setMsg(r.message || '已重启');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '重启失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putScrape({
        enabled: true,
        flareSolverrUrl: flare.trim(),
        proxyUrl: proxy.trim(),
      });
      const savedFlare = toHostPort(next.flareSolverrUrl || '');
      const savedProxy = toProxyHostPort(next.proxyUrl || '');
      setFlare(savedFlare);
      setProxy(savedProxy);
      publish(savedFlare, savedProxy);
      setMsg('已保存');
      await refreshMonitor();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  const monTone =
    mon?.level === 'ok'
      ? 'ok'
      : mon?.level === 'warn'
        ? 'warn'
        : mon?.level === 'critical' || mon?.level === 'down'
          ? 'error'
          : 'unknown';

  return (
    <AppPush title="网络管理" onBack={onBack}>
      {loading ? (
        <p className="app-loading">加载中…</p>
      ) : (
        <>
          <p className="settings-group-label">代理</p>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">HTTP 代理</span>
                <input
                  className="allow-select"
                  value={proxy}
                  onChange={(e) => setProxy(e.target.value)}
                  placeholder={PROXY_PLACEHOLDER}
                  inputMode="url"
                  autoCapitalize="off"
                  autoCorrect="off"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={busy}
                />
              </label>
            </div>
          </section>
          <div className="app-actions">
            <button
              type="button"
              className="app-btn-secondary"
              style={{ flex: 1 }}
              disabled={busy || !proxy.trim()}
              onClick={() => void onTestProxy()}
            >
              测试代理
            </button>
          </div>

          <p className="settings-group-label">过盾</p>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">FlareSolverr</span>
                <input
                  className="allow-select"
                  value={flare}
                  onChange={(e) => setFlare(e.target.value)}
                  placeholder={FLARE_DEFAULT}
                  inputMode="url"
                  autoCapitalize="off"
                  autoCorrect="off"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={busy}
                />
              </label>
            </div>
          </section>

          <p className="settings-group-label">过盾监控</p>
          <section className="app-section">
            <div className="app-section-body">
              <div className="scrape-src-edit__row">
                <span className="scrape-src-edit__lab">状态</span>
                <span className={`scrape-src-edit__val scrape-src-dot--${monTone}`}>
                  {levelLabel(mon?.level)}
                  {mon?.autoEnabled ? ' · 自动治理' : ''}
                </span>
              </div>
              <div className="scrape-src-edit__row">
                <span className="scrape-src-edit__lab">会话</span>
                <span className="scrape-src-edit__val allow-select">
                  {mon ? `${mon.sessions}（孤儿 ${mon.orphanSessions}）` : '—'}
                </span>
              </div>
              <div className="scrape-src-edit__row">
                <span className="scrape-src-edit__lab">CPU / 内存</span>
                <span className="scrape-src-edit__val allow-select">
                  {fmtPct(mon?.cpuPercent)} / {fmtPct(mon?.memPercent)}
                  {mon?.memUsedMb != null ? ` · ${mon.memUsedMb}MB` : ''}
                </span>
              </div>
              <div className="scrape-src-edit__row">
                <span className="scrape-src-edit__lab">延迟</span>
                <span className="scrape-src-edit__val allow-select">
                  均 {fmtMs(mon?.latencyAvgMs)} · P95 {fmtMs(mon?.latencyP95Ms)}
                </span>
              </div>
              <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                <span className="scrape-src-edit__lab">说明</span>
                <span className="scrape-src-edit__val mute">
                  {(mon?.reasons || []).join(' · ') || '等待采样'}
                  {mon?.statsSource && mon.statsSource !== 'none'
                    ? ` · 指标 ${mon.statsSource}`
                    : ' · 未接 CPU 指标（可配 SSH）'}
                  {mon?.lastAction
                    ? ` · 最近 ${mon.lastAction}${mon.lastActionDetail ? `：${mon.lastActionDetail}` : ''}`
                    : ''}
                </span>
              </div>
            </div>
          </section>

          <div className="app-actions" style={{ flexDirection: 'column' }}>
            <button
              type="button"
              className="app-btn-secondary"
              disabled={busy || !flare.trim()}
              onClick={() => void onTestFlare()}
            >
              测试过盾
            </button>
            <button
              type="button"
              className="app-btn-secondary"
              disabled={busy || !flare.trim()}
              onClick={() => void onRecycle()}
            >
              回收会话
            </button>
            <button
              type="button"
              className="app-btn-secondary"
              disabled={busy || !flare.trim()}
              onClick={() => void onRestart()}
            >
              重启过盾
            </button>
            <button
              type="button"
              className="app-btn-primary"
              disabled={busy}
              onClick={() => void onSave()}
            >
              保存
            </button>
          </div>
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </>
      )}
    </AppPush>
  );
}
