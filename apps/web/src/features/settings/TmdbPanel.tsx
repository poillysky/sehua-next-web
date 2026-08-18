'use client';

import { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { getTmdb, putTmdb, testTmdb } from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

export function TmdbPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [apiKey, setApiKey] = useState('');
  const [hint, setHint] = useState('');
  const [configured, setConfigured] = useState(false);
  const [fromEnv, setFromEnv] = useState(false);
  const [showEdit, setShowEdit] = useState(true);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  function applyStatus(nextConfigured: boolean, nextFromEnv: boolean) {
    setConfigured(nextConfigured);
    setFromEnv(nextFromEnv);
    if (!nextConfigured) {
      onStatus('未配置', 'warn');
      return;
    }
    onStatus(nextFromEnv ? '环境变量' : '已就绪', 'ok');
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
    setBusy(true);
    setMsg('');
    try {
      const r = await testTmdb({ apiKey: apiKey.trim() });
      setMsg(r.message || (r.ok ? '测试成功' : '失败'));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putTmdb({ apiKey: apiKey.trim() });
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
            ? apiKey.trim()
              ? '已保存'
              : '未修改原有 Key'
            : '未配置',
      );
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  const statusLabel = !configured
    ? '待配置'
    : fromEnv
      ? '环境变量'
      : '已就绪';
  const statusOk = configured;

  return (
    <AppPush title="TMDB" onBack={onBack}>
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
          <AppFootnote>
            {fromEnv
              ? '当前优先使用环境变量 TMDB_API_KEY。'
              : '用于标题翻译；已有 Key 时，只有输入新 Key 并保存才会替换。'}
          </AppFootnote>
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

      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={busy}
          onClick={() => void onTest()}
        >
          测试
        </button>
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy || (configured && !fromEnv && !showEdit)}
          onClick={() => void onSave()}
        >
          保存
        </button>
      </div>
      <AppMsg allowSelect onDismiss={() => setMsg('')}>
        {msg}
      </AppMsg>
    </AppPush>
  );
}
