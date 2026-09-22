'use client';

import { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { getTmdb, putTmdb, testTmdb } from '@/lib/api';
import { cn } from '@/lib/utils';
import {
  testResultText,
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';
import { ConnectionPanelShell } from './connection/ConnectionPanelShell';

export function TmdbPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const [apiKey, setApiKey] = useState('');
  const [hint, setHint] = useState('');
  const [configured, setConfigured] = useState(false);
  const [fromEnv, setFromEnv] = useState(false);
  const [showEdit, setShowEdit] = useState(true);
  const { msg, setMsg, busy, run } = usePanelAction();

  function applyStatus(nextConfigured: boolean, nextFromEnv: boolean) {
    setConfigured(nextConfigured);
    setFromEnv(nextFromEnv);
    const saved = nextConfigured && !nextFromEnv;
    onStatus(saved ? '已配置' : '未配置', saved ? 'ok' : 'warn');
  }

  useEffect(() => {
    void (async () => {
      try {
        const d = await getTmdb();
        setHint(d.apiKeyHint || '');
        const ok = Boolean(d.configured);
        const env = Boolean(d.fromEnv);
        setShowEdit(!ok || env);
        applyStatus(ok, env);
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onTest() {
    await run('测试失败', async () => {
      const r = await testTmdb({ apiKey: apiKey.trim() });
      setMsg(testResultText(r, '测试成功', '失败'));
    });
  }

  async function onSave() {
    const key = apiKey.trim();
    if (!key && !configured) {
      setMsg('请填写 API Key');
      return;
    }
    await run('保存失败', async () => {
      const next = await putTmdb({ apiKey: key });
      setHint(next.apiKeyHint || '');
      setApiKey('');
      const ok = Boolean(next.configured);
      const env = Boolean(next.fromEnv);
      setShowEdit(!ok || env);
      applyStatus(ok, env);
      setMsg(
        next.fromEnv
          ? '已保存（仍以环境变量为准）'
          : next.configured
            ? key
              ? '已保存'
              : '未修改原有 Key'
            : '未配置',
      );
    });
  }

  const statusLabel = configured && !fromEnv ? '已配置' : '未配置';
  const statusOk = configured && !fromEnv;

  return (
    <ConnectionPanelShell
      title="TMDB"
      onBack={onBack}
      msg={msg}
      onDismissMsg={() => setMsg('')}
      busy={busy}
      onTest={() => void onTest()}
      onSave={() => void onSave()}
      testLabel="测试"
      saveDisabled={configured && !fromEnv && !showEdit}
    >
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span
              className={cn(
                'settings-nav__status',
                statusOk
                  ? 'settings-nav__status--ok'
                  : 'settings-nav__status--warn',
              )}
            >
              {statusLabel}
            </span>
          </div>
        </li>
      </ul>

      <p className="settings-group-label">API Key</p>
      {configured && !showEdit ? (
        <ul className="settings-group">
          <li>
            <div className="settings-nav">
              <span className="settings-nav__icon settings-nav__icon--blue" aria-hidden>
                <KeyRound size={14} strokeWidth={2.25} />
              </span>
              <span className="settings-nav__main">
                <span className="settings-nav__title">已配置</span>
                <span className="settings-nav__desc allow-select">
                  {hint || '••••'}
                </span>
              </span>
              <button
                type="button"
                className="settings-inline-action"
                disabled={busy}
                onClick={() => setShowEdit(true)}
              >
                更换
              </button>
            </div>
          </li>
        </ul>
      ) : (
        <>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field app-field--stack">
                <span className="app-label">Key</span>
                <input
                  type="password"
                  className="allow-select"
                  placeholder={hint ? `已配置 ${hint}` : '粘贴 TMDB API Key'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoCapitalize="off"
                  autoCorrect="off"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={busy}
                />
              </label>
            </div>
          </section>
          {configured && !fromEnv ? (
            <button
              type="button"
              className="settings-text-link"
              disabled={busy}
              onClick={() => {
                setApiKey('');
                setShowEdit(false);
              }}
            >
              取消更换
            </button>
          ) : null}
        </>
      )}
    </ConnectionPanelShell>
  );
}
