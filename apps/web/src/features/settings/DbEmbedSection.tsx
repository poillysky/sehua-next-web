'use client';

import { useCallback, useEffect, useState } from 'react';
import { AppFootnote } from '@/components/ui/AppMsg';

export type DbEmbedStats = {
  ok?: boolean;
  resources?: number;
  embedded?: number;
  pending?: number;
  hasHnsw?: boolean;
  indexes?: string[];
  model?: string;
  dim?: number;
  error?: string;
};

export type DbEmbedJobStatus = {
  running: boolean;
  phase?: string;
  progress?: {
    stage?: string;
    done?: number;
    total?: number | null;
    percent?: number | null;
    label?: string;
  } | null;
  log?: string[];
  result?: {
    written?: number;
    embedded?: number;
    resources?: number;
    paused?: boolean;
  } | null;
  error?: string | null;
  startedAt?: number | null;
  stop?: boolean;
};

function formatPct(n: number | null | undefined): string | null {
  if (n == null || !Number.isFinite(Number(n))) return null;
  return `${Number(n).toFixed(2)}%`;
}

function formatEta(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '';
  if (sec < 45) return '约不到 1 分钟';
  if (sec < 3600) {
    const m = Math.max(1, Math.round(sec / 60));
    return `约 ${m} 分钟`;
  }
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  if (m <= 0) return `约 ${h} 小时`;
  return `约 ${h} 小时 ${m} 分`;
}

function estimateEta(status: DbEmbedJobStatus | null): string {
  if (!status?.running) return '';
  const done = Number(status.progress?.done || 0);
  const total = Number(status.progress?.total || 0);
  const startedAt = Number(status.startedAt || 0);
  if (!(done > 0 && total > done && startedAt > 0)) return '';
  const elapsedMs = Date.now() - startedAt;
  if (elapsedMs < 3000) return '';
  const rate = done / (elapsedMs / 1000);
  if (!(rate > 0)) return '';
  const remainSec = (total - done) / rate;
  return formatEta(remainSec);
}

export function DbEmbedSection({
  disabled,
  getStats,
  getStatus,
  startEmbed,
  stopEmbed,
  createIndex,
  onMessage,
}: {
  disabled?: boolean;
  getStats: () => Promise<DbEmbedStats>;
  getStatus: () => Promise<DbEmbedJobStatus>;
  startEmbed: (opts?: { force?: boolean }) => Promise<{ started: boolean }>;
  stopEmbed: () => Promise<{ ok?: boolean; pausing?: boolean }>;
  createIndex: () => Promise<unknown>;
  onMessage: (text: string) => void;
}) {
  const [stats, setStats] = useState<DbEmbedStats | null>(null);
  const [status, setStatus] = useState<DbEmbedJobStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [, setTick] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [s, j] = await Promise.all([getStats(), getStatus()]);
      setStats(s);
      setStatus(j);
      return j;
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '向量状态读取失败');
      return null;
    }
  }, [getStats, getStatus, onMessage]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!status?.running) return;
    const t = window.setInterval(() => {
      void refresh();
      setTick((n) => n + 1);
    }, 1500);
    return () => window.clearInterval(t);
  }, [status?.running, refresh]);

  async function onStart(force = false) {
    setBusy(true);
    try {
      await startEmbed({ force });
      onMessage(force ? '已开始强制重写向量…' : '已开始同步向量…');
      await refresh();
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '启动失败');
    } finally {
      setBusy(false);
    }
  }

  async function onPause() {
    setBusy(true);
    try {
      await stopEmbed();
      onMessage('正在暂停，当前批次写完后停止…');
      await refresh();
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '暂停失败');
    } finally {
      setBusy(false);
    }
  }

  async function onIndex() {
    setBusy(true);
    try {
      await createIndex();
      onMessage('HNSW 索引已创建');
      await refresh();
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '建索引失败');
    } finally {
      setBusy(false);
    }
  }

  const running = Boolean(status?.running);
  const pausing = running && (Boolean(status?.stop) || status?.phase === 'pausing');
  const pending = Number(stats?.pending ?? 0);
  const embedded = stats?.embedded ?? 0;
  const resources = stats?.resources ?? 0;
  const canResume = !running && embedded > 0 && pending > 0;
  const locked = Boolean(disabled) || busy;
  const pct = status?.progress?.percent;
  const pctText = formatPct(pct);
  const etaText = estimateEta(status);
  const done = Number(status?.progress?.done || 0);
  const total = Number(status?.progress?.total || 0);

  let desc: string;
  if (running) {
    const parts: string[] = [];
    if (pausing) parts.push('暂停中');
    else if (pctText) parts.push(pctText);
    if (total > 0) {
      parts.push(`${done.toLocaleString()} / ${total.toLocaleString()}`);
    } else if (status?.progress?.label) {
      parts.push(String(status.progress.label));
    } else {
      parts.push(status?.phase || '同步中…');
    }
    if (!pausing && etaText) parts.push(`预计还要 ${etaText.replace(/^约\s*/, '')}`);
    desc = parts.join(' · ');
  } else if (status?.phase === 'paused' || status?.result?.paused) {
    desc = `已暂停 · ${embedded.toLocaleString()} / ${resources.toLocaleString()}，可继续同步`;
  } else if (stats?.error) {
    desc = stats.error;
  } else if (resources > 0) {
    desc = `已灌 ${embedded.toLocaleString()} / ${resources.toLocaleString()}${
      stats?.hasHnsw ? ' · HNSW' : ''
    }`;
  } else {
    desc = '资源库未就绪或为空';
  }

  let primaryLabel = '开始同步';
  if (running) {
    primaryLabel = pausing ? '暂停中…' : '暂停';
  } else if (canResume) {
    primaryLabel = '继续同步';
  }

  return (
    <>
      <p className="settings-group-label">资源向量</p>
      <ul className="settings-group">
        <li>
          <div
            className="settings-nav"
            style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10 }}
          >
            <span className="settings-nav__main">
              <span className="settings-nav__title">同步向量数据库</span>
              <span className="settings-nav__desc" style={{ whiteSpace: 'normal' }}>
                {desc}
              </span>
              {running && pct != null ? (
                <div
                  style={{
                    marginTop: 8,
                    height: 4,
                    borderRadius: 2,
                    background: 'var(--app-fill-tertiary, #e5e5ea)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${Math.max(0, Math.min(100, Number(pct)))}%`,
                      height: '100%',
                      background: 'var(--app-tint, #007aff)',
                    }}
                  />
                </div>
              ) : null}
            </span>
            <button
              type="button"
              className="app-btn-secondary"
              style={{ width: '100%' }}
              disabled={locked || pausing}
              onClick={() => {
                if (running) void onPause();
                else void onStart(false);
              }}
            >
              {primaryLabel}
            </button>
          </div>
        </li>
      </ul>
      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked || running}
          onClick={() => void refresh()}
        >
          刷新
        </button>
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked || running}
          onClick={() => void onIndex()}
        >
          建索引
        </button>
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked || running}
          onClick={() => void onStart(true)}
        >
          强制重写
        </button>
      </div>
      {status?.log && status.log.length > 0 ? (
        <AppFootnote>{status.log.slice(-3).join(' · ')}</AppFootnote>
      ) : null}
    </>
  );
}
