'use client';

import { useEffect, useState } from 'react';
import { HardDrive } from 'lucide-react';
import {
  getPansouSettings,
  putPansouSettings,
  testPansou,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import {
  testResultText,
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';
import { ConnectionPanelShell } from './connection/ConnectionPanelShell';

export function PansouPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState('http://192.168.2.38:8188');
  const [timeoutSec, setTimeoutSec] = useState('60');
  const [loading, setLoading] = useState(true);
  const { msg, setMsg, busy, run } = usePanelAction();

  function hubStatus(on: boolean, url: string) {
    if (on && url.trim()) return { text: '已启用', tone: 'ok' as const };
    if (url.trim()) return { text: '未启用', tone: 'warn' as const };
    return { text: '未配置', tone: 'warn' as const };
  }

  useEffect(() => {
    void (async () => {
      try {
        const d = await getPansouSettings();
        setEnabled(d.enabled !== false);
        setBaseUrl(d.baseUrl || 'http://192.168.2.38:8188');
        setTimeoutSec(String(d.timeoutSec ?? 60));
        const st = hubStatus(d.enabled !== false, d.baseUrl || '');
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
        const r = await testPansou();
        setMsg(testResultText(r, '连接成功', '连接失败'));
        onStatus(r.ok ? '已连通' : '连接失败', r.ok ? 'ok' : 'warn');
      },
      () => onStatus('连接失败', 'warn'),
    );
  }

  async function onSave() {
    const url = baseUrl.trim();
    if (!url) {
      setMsg('请填写服务地址');
      return;
    }
    const sec = Number(timeoutSec);
    await run('保存失败', async () => {
      const next = await putPansouSettings({
        enabled,
        baseUrl: url,
        timeoutSec: Number.isFinite(sec) ? sec : 60,
        note: '',
      });
      setBaseUrl(next.baseUrl || url);
      setEnabled(next.enabled !== false);
      setTimeoutSec(String(next.timeoutSec ?? 60));
      const st = hubStatus(next.enabled !== false, next.baseUrl || '');
      onStatus(st.text, st.tone);
      setMsg('已保存');
    });
  }

  return (
    <ConnectionPanelShell
      title="盘搜 PanSou"
      onBack={onBack}
      msg={msg}
      onDismissMsg={() => setMsg('')}
      loading={loading}
      busy={busy}
      onTest={() => void onTest()}
      onSave={() => void onSave()}
      testLabel="测试"
    >
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span
              className={cn(
                'settings-nav__status',
                enabled && baseUrl.trim()
                  ? 'settings-nav__status--ok'
                  : 'settings-nav__status--warn',
              )}
            >
              {enabled ? '已启用' : '未启用'}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-nav">
            <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
              <HardDrive size={14} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">启用盘搜</span>
              <span className="settings-nav__desc">影视详情 · 盘搜按钮</span>
            </span>
            <Switch
              checked={enabled}
              disabled={busy || loading}
              onCheckedChange={setEnabled}
            />
          </div>
        </li>
      </ul>

      <p className="settings-group-label">服务</p>
      <section className="app-section">
        <div className="app-section-body">
          <label className="app-field app-field--stack">
            <span className="app-label">地址</span>
            <input
              className="allow-select"
              placeholder="http://192.168.2.38:8188"
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
