'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/providers/AuthProvider';
import {
  createResourceDbEmbedIndex,
  exportResourceDbBackup,
  getResourceDb,
  getResourceDbEmbedStats,
  getResourceDbEmbedStatus,
  listResourceDbBackups,
  putResourceDb,
  startResourceDbEmbed,
  stopResourceDbEmbed,
  testResourceDb,
  uploadImportResourceDbBackup,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { DbDataBackupSection } from './DbDataBackupSection';
import { DbEmbedSection } from './DbEmbedSection';
import {
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';

type DsnParts = {
  host: string;
  port: string;
  user: string;
  database: string;
};

function parsePostgresDsn(dsn: string): DsnParts & {
  password: string;
  hasPassword: boolean;
} {
  const fallback = {
    host: '',
    port: '5435',
    user: 'postgres',
    password: '',
    database: 'ed2k',
    hasPassword: false,
  };
  const raw = dsn.trim();
  if (!raw) return fallback;
  try {
    const u = new URL(raw);
    const db = decodeURIComponent(
      (u.pathname.replace(/^\//, '').split('/')[0] || 'ed2k').trim(),
    );
    return {
      host: u.hostname || '',
      port: u.port || '5435',
      user: decodeURIComponent(u.username || 'postgres'),
      password: decodeURIComponent(u.password || ''),
      database: db || 'ed2k',
      hasPassword: Boolean(u.password),
    };
  } catch {
    return fallback;
  }
}

function buildPostgresDsn(parts: DsnParts & { password: string }): string {
  const user = encodeURIComponent(parts.user.trim() || 'postgres');
  const pass = encodeURIComponent(parts.password || '');
  const host = parts.host.trim() || '127.0.0.1';
  const port = parts.port.trim() || '5435';
  const database = (parts.database.trim() || 'ed2k').replace(/^\/+/, '');
  return `postgresql://${user}:${pass}@${host}:${port}/${database}`;
}

export function ResourceDbPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const { isAdmin } = useAuth();
  const savedPassword = useRef('');
  const [enabled, setEnabled] = useState(false);
  const [host, setHost] = useState('');
  const [port, setPort] = useState('5435');
  const [user, setUser] = useState('postgres');
  const [password, setPassword] = useState('');
  const [database, setDatabase] = useState('ed2k');
  const [note, setNote] = useState('');
  const [hasPassword, setHasPassword] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const { msg, setMsg, busy, run } = usePanelAction();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const cfg = await getResourceDb();
        if (cancelled) return;
        const parsed = parsePostgresDsn(cfg.dsn || '');
        setEnabled(Boolean(cfg.enabled));
        setHost(parsed.host);
        setPort(parsed.port);
        setUser(parsed.user);
        setDatabase(parsed.database);
        setNote(cfg.note || '');
        setHasPassword(parsed.hasPassword);
        savedPassword.current = parsed.password;
        setPassword('');
        if (cfg.enabled && cfg.dsn) {
          setConnected(null);
          try {
            const r = await testResourceDb(cfg.dsn);
            if (cancelled) return;
            setConnected(r.ok);
            onStatus(r.ok ? '已连接' : '连接失败', r.ok ? 'ok' : 'warn');
          } catch {
            if (cancelled) return;
            setConnected(false);
            onStatus('连接失败', 'warn');
          }
        } else {
          setConnected(false);
          onStatus(cfg.dsn ? '未启用' : '未配置', 'warn');
        }
      } catch (e) {
        if (cancelled) return;
        setMsg(e instanceof Error ? e.message : '读取失败');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function resolvePassword() {
    const typed = password.trim();
    return typed || (hasPassword ? savedPassword.current : '');
  }

  function resolveDsn() {
    return buildPostgresDsn({
      host,
      port,
      user,
      database,
      password: resolvePassword(),
    });
  }

  async function onTest() {
    if (!isAdmin) {
      setMsg('仅管理员可测试');
      return;
    }
    if (!host.trim()) {
      setMsg('请填写主机');
      return;
    }
    await run(
      '测试失败',
      async () => {
        const r = await testResourceDb(resolveDsn());
        setConnected(r.ok);
        setMsg(r.ok ? '连接成功' : `失败：${r.message}`);
        onStatus(r.ok ? '已连接' : '连接失败', r.ok ? 'ok' : 'warn');
      },
      () => setConnected(false),
    );
  }

  async function onSave() {
    if (!isAdmin) {
      setMsg('仅管理员可修改');
      return;
    }
    if (!host.trim()) {
      setMsg('请填写主机');
      return;
    }
    await run('保存失败', async () => {
      const dsn = resolveDsn();
      await putResourceDb({ enabled, dsn, note });
      const savedPwd = resolvePassword();
      savedPassword.current = savedPwd;
      setHasPassword(Boolean(savedPwd));
      setPassword('');
      setMsg('已保存');
      if (enabled && dsn) {
        try {
          const r = await testResourceDb(dsn);
          setConnected(r.ok);
          onStatus(r.ok ? '已连接' : '连接失败', r.ok ? 'ok' : 'warn');
          if (!r.ok) setMsg(`已保存，但连接失败：${r.message}`);
        } catch {
          setConnected(null);
          onStatus('已启用', 'ok');
        }
      } else {
        setConnected(false);
        onStatus(dsn ? '未启用' : '未配置', 'warn');
      }
    });
  }

  function fillDefaults() {
    setHost((h) => h.trim() || '127.0.0.1');
    setPort('5435');
    setUser('postgres');
    setDatabase('ed2k');
    setMsg('已填入常用默认值');
  }

  const statusText =
    connected === null
      ? '检测中'
      : connected
        ? '已连接'
        : enabled
          ? '连接失败'
          : host.trim()
            ? '未启用'
            : '未配置';
  const statusTone =
    connected === true ? 'ok' : connected === null ? 'mute' : 'warn';

  const locked = !isAdmin || busy || backupBusy;

  return (
    <AppPush title="色花资源库" onBack={onBack}>
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span
              className={cn(
                'settings-nav__status',
                statusTone === 'ok' && 'settings-nav__status--ok',
                statusTone === 'warn' && 'settings-nav__status--warn',
              )}
            >
              {statusText}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">启用查询</span>
            <Switch
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={locked}
            />
          </div>
        </li>
      </ul>

      <p className="settings-group-label">连接</p>
      <section className="app-section">
        <div className="app-section-body">
          <label className="app-field">
            <span className="app-label">主机</span>
            <input
              className="allow-select"
              placeholder="192.168.x.x"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              disabled={locked}
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="app-field">
            <span className="app-label">端口</span>
            <input
              className="allow-select"
              placeholder="5435"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              disabled={locked}
              inputMode="numeric"
              autoComplete="off"
            />
          </label>
          <label className="app-field">
            <span className="app-label">库名</span>
            <input
              className="allow-select"
              placeholder="ed2k"
              value={database}
              onChange={(e) => setDatabase(e.target.value)}
              disabled={locked}
              autoCapitalize="off"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
        </div>
      </section>

      <p className="settings-group-label">账号</p>
      <section className="app-section">
        <div className="app-section-body">
          <label className="app-field">
            <span className="app-label">用户</span>
            <input
              className="allow-select"
              placeholder="postgres"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              disabled={locked}
              autoCapitalize="off"
              autoComplete="username"
            />
          </label>
          <label className="app-field">
            <span className="app-label">密码</span>
            <input
              className="allow-select"
              type="password"
              placeholder={hasPassword ? '已保存，留空不改' : '可留空'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={locked}
              autoComplete="new-password"
            />
          </label>
        </div>
      </section>

      {isAdmin ? (
        <>
          <DbDataBackupSection
            dirHint="backups/resource-db/"
            disabled={busy}
            listBackups={listResourceDbBackups}
            exportBackup={exportResourceDbBackup}
            uploadImportBackup={uploadImportResourceDbBackup}
            onMessage={setMsg}
            onBusyChange={setBackupBusy}
          />

          <DbEmbedSection
            disabled={busy || backupBusy}
            getStats={getResourceDbEmbedStats}
            getStatus={getResourceDbEmbedStatus}
            startEmbed={startResourceDbEmbed}
            stopEmbed={stopResourceDbEmbed}
            createIndex={createResourceDbEmbedIndex}
            onMessage={setMsg}
          />

          <div className="app-actions">
            <button
              type="button"
              className="app-btn-secondary"
              disabled={locked}
              onClick={fillDefaults}
            >
              默认值
            </button>
            <button
              type="button"
              className="app-btn-secondary"
              disabled={locked}
              onClick={() => void onTest()}
            >
              测试
            </button>
            <button
              type="button"
              className="app-btn-primary"
              style={{ flex: 1 }}
              disabled={locked}
              onClick={() => void onSave()}
            >
              保存
            </button>
          </div>
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </>
      ) : (
        <AppFootnote>普通用户仅可查看连接状态。色花资源库与启动元库分开。</AppFootnote>
      )}
    </AppPush>
  );
}
