'use client';

import { useEffect, useState } from 'react';
import { Cloud } from 'lucide-react';
import {
  getCloudSaverSettings,
  putCloudSaverSettings,
  testCloudSaver,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import {
  testResultText,
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';
import { ConnectionPanelShell } from './connection/ConnectionPanelShell';

export function CloudSaverPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState('http://192.168.2.38:8008');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [hasPassword, setHasPassword] = useState(false);
  const [timeoutSec, setTimeoutSec] = useState('60');
  const [loading, setLoading] = useState(true);
  const { msg, setMsg, busy, run } = usePanelAction();

  function hubStatus(on: boolean, user: string, pwdOk: boolean) {
    if (on && user && pwdOk) return { text: '已登录配置', tone: 'ok' as const };
    if (user || pwdOk) return { text: '未完整', tone: 'warn' as const };
    return { text: '未配置', tone: 'warn' as const };
  }

  useEffect(() => {
    void (async () => {
      try {
        const d = await getCloudSaverSettings();
        setEnabled(d.enabled !== false);
        setBaseUrl(d.baseUrl || 'http://192.168.2.38:8008');
        setUsername(d.username || '');
        setHasPassword(Boolean(d.hasPassword));
        setTimeoutSec(String(d.timeoutSec ?? 60));
        const st = hubStatus(
          d.enabled !== false,
          d.username || '',
          Boolean(d.hasPassword),
        );
        onStatus(st.text, st.tone);
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
        onStatus('异常', 'warn');
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onTest() {
    await run(
      '测试失败',
      async () => {
        await putCloudSaverSettings({
          enabled,
          baseUrl: baseUrl.trim(),
          username: username.trim(),
          password: password,
          timeoutSec: Number(timeoutSec) || 60,
          note: '',
        });
        if (password.trim()) {
          setHasPassword(true);
          setPassword('');
        }
        const r = await testCloudSaver();
        setMsg(testResultText(r, '登录成功', '登录失败'));
        onStatus(r.ok ? '已连通' : '连接失败', r.ok ? 'ok' : 'warn');
      },
      () => onStatus('连接失败', 'warn'),
    );
  }

  async function onSave() {
    const url = baseUrl.trim();
    const user = username.trim();
    if (!url) {
      setMsg('请填写服务地址');
      return;
    }
    if (!user) {
      setMsg('请填写用户名');
      return;
    }
    if (!password.trim() && !hasPassword) {
      setMsg('请填写密码');
      return;
    }
    await run('保存失败', async () => {
      const next = await putCloudSaverSettings({
        enabled,
        baseUrl: url,
        username: user,
        password: password,
        timeoutSec: Number(timeoutSec) || 60,
        note: '',
      });
      setEnabled(next.enabled !== false);
      setBaseUrl(next.baseUrl || url);
      setUsername(next.username || user);
      setHasPassword(Boolean(next.hasPassword));
      setPassword('');
      setTimeoutSec(String(next.timeoutSec ?? 60));
      const st = hubStatus(
        next.enabled !== false,
        next.username || '',
        Boolean(next.hasPassword),
      );
      onStatus(st.text, st.tone);
      setMsg('已保存');
    });
  }

  return (
    <ConnectionPanelShell
      title="CloudSaver"
      onBack={onBack}
      msg={msg}
      onDismissMsg={() => setMsg('')}
      loading={loading}
      busy={busy}
      onTest={() => void onTest()}
      onSave={() => void onSave()}
      testLabel="测试登录"
    >
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span
              className={cn(
                'settings-nav__status',
                enabled && username && hasPassword
                  ? 'settings-nav__status--ok'
                  : 'settings-nav__status--warn',
              )}
            >
              {enabled && username && hasPassword ? '已配置' : '未完整'}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-nav">
            <span className="settings-nav__icon settings-nav__icon--green" aria-hidden>
              <Cloud size={14} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">启用 CloudSaver</span>
              <span className="settings-nav__desc">影视详情 · CS 按钮</span>
            </span>
            <Switch
              checked={enabled}
              disabled={busy || loading}
              onCheckedChange={setEnabled}
            />
          </div>
        </li>
      </ul>

      <p className="settings-group-label">服务与登录</p>
      <section className="app-section">
        <div className="app-section-body">
          <label className="app-field app-field--stack">
            <span className="app-label">地址</span>
            <input
              className="allow-select"
              placeholder="http://192.168.2.38:8008"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
              disabled={busy || loading}
            />
          </label>
          <label className="app-field app-field--stack">
            <span className="app-label">用户名</span>
            <input
              className="allow-select"
              placeholder="CloudSaver 登录名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="username"
              spellCheck={false}
              disabled={busy || loading}
            />
          </label>
          <label className="app-field app-field--stack">
            <span className="app-label">密码</span>
            <input
              type="password"
              className="allow-select"
              placeholder={hasPassword ? '已保存，留空不改' : 'CloudSaver 密码'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              disabled={busy || loading}
            />
          </label>
          <label className="app-field app-field--stack">
            <span className="app-label">超时（秒）</span>
            <input
              className="allow-select"
              inputMode="numeric"
              placeholder="60"
              value={timeoutSec}
              onChange={(e) => setTimeoutSec(e.target.value)}
              disabled={busy || loading}
            />
          </label>
        </div>
      </section>
    </ConnectionPanelShell>
  );
}
