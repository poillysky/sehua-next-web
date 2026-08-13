'use client';

import { useEffect, useState } from 'react';
import { Folder, FolderOpen, KeyRound } from 'lucide-react';
import {
  getP115,
  listP115Folders,
  putP115,
  validateP115,
  type P115Config,
  type P115FolderItem,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

type Tab = 'cookie' | 'folder';

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'cookie', label: 'Cookie' },
  { key: 'folder', label: '目录' },
];

function formatQuota(remain: number | null | undefined, total: number | null | undefined) {
  if (remain == null && total == null) return null;
  if (remain != null && total != null) return `${remain} / ${total}`;
  if (remain != null) return String(remain);
  return String(total);
}

function formatBytes(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n) || n < 0) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  const digits = v >= 100 || i < 2 ? 0 : v >= 10 ? 1 : 2;
  const text = Number.isInteger(v) || digits === 0 ? String(Math.round(v)) : v.toFixed(digits);
  return `${text} ${units[i]}`;
}

export function P115Panel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [tab, setTab] = useState<Tab>('cookie');
  const [configured, setConfigured] = useState(false);
  const [hint, setHint] = useState('');
  const [cookie, setCookie] = useState('');
  const [showCookieEdit, setShowCookieEdit] = useState(true);
  const [folderCid, setFolderCid] = useState('0');
  const [folderName, setFolderName] = useState('');
  const [label, setLabel] = useState('');
  const [quota, setQuota] = useState<number | null>(null);
  const [quotaTotal, setQuotaTotal] = useState<number | null>(null);
  const [quotaError, setQuotaError] = useState('');
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [spaceUsedText, setSpaceUsedText] = useState('');
  const [spaceTotalText, setSpaceTotalText] = useState('');
  const [spaceRemainText, setSpaceRemainText] = useState('');
  const [spaceUsed, setSpaceUsed] = useState<number | null>(null);
  const [spaceTotal, setSpaceTotal] = useState<number | null>(null);
  const [offlineLimit, setOfflineLimit] = useState<number | null>(null);
  const [showBrowser, setShowBrowser] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [folderPath, setFolderPath] = useState<P115FolderItem[]>([]);
  const [folders, setFolders] = useState<P115FolderItem[]>([]);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  function applyQuotaInfo(data: Partial<P115Config> & {
    quota?: number | null;
    quotaTotal?: number | null;
    quotaError?: string;
  }) {
    if ('quota' in data || 'quotaTotal' in data) {
      setQuota(data.quota ?? null);
      setQuotaTotal(data.quotaTotal ?? null);
    }
    if (data.quotaError) setQuotaError(data.quotaError);
    else if ('quota' in data) setQuotaError('');

    if (data.spaceUsedText != null) setSpaceUsedText(String(data.spaceUsedText || ''));
    if (data.spaceTotalText != null) setSpaceTotalText(String(data.spaceTotalText || ''));
    if (data.spaceRemainText != null) setSpaceRemainText(String(data.spaceRemainText || ''));
    if ('spaceUsed' in data) setSpaceUsed(data.spaceUsed ?? null);
    if ('spaceTotal' in data) setSpaceTotal(data.spaceTotal ?? null);
    if ('offlineLimit' in data) setOfflineLimit(data.offlineLimit ?? null);
  }

  function applyConfig(data: P115Config) {
    setConfigured(Boolean(data.configured));
    setHint(data.cookieHint || '');
    setFolderCid(data.folderCid || '0');
    setFolderName(data.folderName || '');
    setLabel(data.label || '');
    setCookie('');
    setShowCookieEdit(!data.configured);
    applyQuotaInfo(data);
    onStatus(data.configured ? '已就绪' : '未配置', data.configured ? 'ok' : 'warn');
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        setQuotaLoading(true);
        const data = await getP115();
        if (cancelled) return;
        applyConfig(data);
      } catch (e) {
        if (cancelled) return;
        setMsg(e instanceof Error ? e.message : '读取失败');
      } finally {
        if (!cancelled) setQuotaLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function browseFolders(cid = '0') {
    setBrowsing(true);
    setMsg('');
    try {
      const data = await listP115Folders({
        cid,
        cookie: cookie.trim() || undefined,
      });
      setFolderPath(data.path || []);
      setFolders(data.folders || []);
      setShowBrowser(true);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '获取目录失败');
    } finally {
      setBrowsing(false);
    }
  }

  function selectFolder(item: P115FolderItem) {
    setFolderCid(item.cid);
    setFolderName(item.name);
    setShowBrowser(false);
    setMsg(`已选择「${item.name}」，记得保存`);
  }

  async function onTest() {
    setBusy(true);
    setMsg('');
    try {
      const r = await validateP115({
        cookie: cookie.trim() || undefined,
        folderCid,
      });
      if (r.folderName) setFolderName(String(r.folderName));
      applyQuotaInfo(r);
      const q = formatQuota(r.quota, r.quotaTotal);
      setMsg(
        [r.message || (r.ok ? '验证成功' : '验证失败'), q ? `云转存 ${q}` : '']
          .filter(Boolean)
          .join(' · '),
      );
      if (r.ok) onStatus('已就绪', 'ok');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '验证失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putP115({
        cookie: cookie.trim() || undefined,
        folderCid: folderCid.trim() || '0',
        folderName: folderName.trim(),
        label: label.trim(),
        validate: true,
      });
      applyConfig(next);
      setShowCookieEdit(false);
      const q = formatQuota(next.quota, next.quotaTotal);
      setMsg(
        [next.message || '已保存', q ? `云转存 ${q}` : ''].filter(Boolean).join(' · '),
      );
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  const displayName =
    folderName || (folderCid === '0' ? '根目录' : '自定义目录');
  const locked = busy || browsing;
  const quotaRatio =
    quota != null && quotaTotal != null && quotaTotal > 0
      ? Math.max(0, Math.min(1, quota / quotaTotal))
      : null;
  const quotaLow =
    quota != null && quotaTotal != null && quotaTotal > 0 && quota / quotaTotal <= 0.2;
  const spaceRatio =
    spaceUsed != null && spaceTotal != null && spaceTotal > 0
      ? Math.max(0, Math.min(1, spaceUsed / spaceTotal))
      : null;
  const offlineLimitText = formatBytes(offlineLimit);

  return (
    <AppPush title="115网盘" onBack={onBack}>
      {!configured ? (
        <ul className="settings-group">
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">状态</span>
              <span className="settings-nav__status settings-nav__status--warn">
                待配置
              </span>
            </div>
          </li>
        </ul>
      ) : (
        <section className="p115-stats" aria-label="115 状态">
          <div className="p115-stats__head">
            <span className="p115-stats__badge p115-stats__badge--ok">已就绪</span>
            {offlineLimitText ? (
              <span className="p115-stats__cap allow-select">单任务 ≤ {offlineLimitText}</span>
            ) : null}
          </div>

          <div className="p115-stats__grid">
            <div className="p115-stat">
              <div className="p115-stat__top">
                <span className="p115-stat__label">云转存</span>
                <span
                  className={cn(
                    'p115-stat__pct',
                    quotaLow ? 'is-warn' : 'is-ok',
                  )}
                >
                  {quotaRatio != null ? `${Math.round(quotaRatio * 100)}%` : ''}
                </span>
              </div>
              <div className="p115-stat__value allow-select">
                {quotaLoading && quota == null ? (
                  <span className="p115-stat__muted">读取中…</span>
                ) : quota != null ? (
                  <>
                    <strong>{quota}</strong>
                    {quotaTotal != null ? (
                      <span className="p115-stat__den"> / {quotaTotal}</span>
                    ) : null}
                  </>
                ) : (
                  <span className="p115-stat__muted">
                    {quotaError || '暂无数据'}
                  </span>
                )}
              </div>
              {quotaRatio != null ? (
                <div
                  className={cn('p115-quota-bar', quotaLow && 'p115-quota-bar--low')}
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={quotaTotal ?? 0}
                  aria-valuenow={quota ?? 0}
                  aria-label="云转存剩余额度"
                >
                  <span style={{ width: `${Math.round(quotaRatio * 100)}%` }} />
                </div>
              ) : (
                <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                  <span style={{ width: '0%' }} />
                </div>
              )}
              <p className="p115-stat__hint">剩余任务额度</p>
            </div>

            <div className="p115-stat">
              <div className="p115-stat__top">
                <span className="p115-stat__label">网盘空间</span>
                <span className="p115-stat__pct is-mute">
                  {spaceRatio != null ? `${Math.round(spaceRatio * 100)}%` : ''}
                </span>
              </div>
              <div className="p115-stat__value allow-select">
                {spaceRemainText ? (
                  <>
                    <strong>{spaceRemainText}</strong>
                    <span className="p115-stat__den"> 剩余</span>
                  </>
                ) : spaceUsedText && spaceTotalText ? (
                  <span className="p115-stat__muted">
                    {spaceUsedText} / {spaceTotalText}
                  </span>
                ) : (
                  <span className="p115-stat__muted">暂无数据</span>
                )}
              </div>
              {spaceRatio != null ? (
                <div
                  className="p115-quota-bar p115-quota-bar--space"
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(spaceRatio * 100)}
                  aria-label="网盘已用空间"
                >
                  <span style={{ width: `${Math.round(spaceRatio * 100)}%` }} />
                </div>
              ) : (
                <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                  <span style={{ width: '0%' }} />
                </div>
              )}
              <p className="p115-stat__hint allow-select">
                {spaceUsedText && spaceTotalText
                  ? `已用 ${spaceUsedText} · 共 ${spaceTotalText}`
                  : '容量占用'}
              </p>
            </div>
          </div>
        </section>
      )}
      <div className="app-seg" role="tablist" aria-label="115 分页">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={cn('app-seg__btn', tab === t.key && 'app-seg__btn--active')}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'cookie' ? (
        <>
          <p className="settings-group-label">登录 Cookie</p>
          {configured && !showCookieEdit ? (
            <ul className="settings-group">
              <li>
                <div className="settings-nav">
                  <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                    <KeyRound size={14} strokeWidth={2.25} />
                  </span>
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">已登录</span>
                    <span className="settings-nav__desc allow-select">
                      {hint || '••••'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="settings-inline-action"
                    disabled={locked}
                    onClick={() => setShowCookieEdit(true)}
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
                    <span className="app-label">Cookie</span>
                    <textarea
                      className="allow-select"
                      placeholder="UID=…; CID=…; SEID=…; KID=…"
                      value={cookie}
                      onChange={(e) => setCookie(e.target.value)}
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                      disabled={locked}
                    />
                  </label>
                </div>
              </section>
              <AppFootnote>
                {configured
                  ? '粘贴新 Cookie 后点保存；取消则不修改。'
                  : '从 115 网页复制完整 Cookie（需含 UID / CID / SEID）。'}
              </AppFootnote>
              {configured ? (
                <button
                  type="button"
                  className="settings-text-link"
                  disabled={locked}
                  onClick={() => {
                    setCookie('');
                    setShowCookieEdit(false);
                  }}
                >
                  取消更换
                </button>
              ) : null}
            </>
          )}
        </>
      ) : (
        <>
          <p className="settings-group-label">转存目录</p>
          <ul className="settings-group">
            <li>
              <div className="settings-nav">
                <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
                  <FolderOpen size={14} strokeWidth={2.25} />
                </span>
                <span className="settings-nav__main">
                  <span className="settings-nav__title allow-select">{displayName}</span>
                  <span className="settings-nav__desc allow-select">
                    CID {folderCid || '0'}
                    {label ? ` · ${label}` : ''}
                  </span>
                </span>
                <button
                  type="button"
                  className="settings-inline-action"
                  disabled={locked}
                  onClick={() => void browseFolders(folderCid || '0')}
                >
                  {showBrowser ? '刷新' : '浏览'}
                </button>
              </div>
            </li>
          </ul>

          {showBrowser ? (
            <div className="p115-browser">
              <nav className="p115-browser__path">
                {folderPath.map((p, idx) => (
                  <span key={`${p.cid}-${idx}`} className="p115-browser__crumb">
                    {idx > 0 ? <span className="p115-browser__sep">/</span> : null}
                    <button
                      type="button"
                      className="p115-browser__link"
                      onClick={() => void browseFolders(p.cid)}
                    >
                      {p.name}
                    </button>
                  </span>
                ))}
                <button
                  type="button"
                  className="p115-browser__close"
                  onClick={() => setShowBrowser(false)}
                >
                  收起
                </button>
              </nav>
              <div className="p115-browser__list">
                {browsing ? (
                  <p className="p115-browser__empty">加载中…</p>
                ) : folders.length === 0 ? (
                  <p className="p115-browser__empty">此层无子文件夹，可选用当前路径</p>
                ) : (
                  folders.map((f) => {
                    const selected = f.cid === folderCid;
                    return (
                      <div
                        key={f.cid}
                        className={cn('p115-browser__row', selected && 'is-selected')}
                      >
                        <span className="p115-browser__fold" aria-hidden>
                          <Folder size={16} strokeWidth={2} />
                        </span>
                        <button
                          type="button"
                          className="p115-browser__name"
                          onClick={() => void browseFolders(f.cid)}
                        >
                          {f.name}
                        </button>
                        <button
                          type="button"
                          className={cn('p115-browser__pick', selected && 'is-on')}
                          onClick={() => selectFolder(f)}
                        >
                          {selected ? '已选' : '选用'}
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
              {folderPath.length > 0 ? (
                <div className="p115-browser__foot">
                  <button
                    type="button"
                    className="app-btn-secondary"
                    onClick={() => {
                      const cur = folderPath[folderPath.length - 1];
                      if (cur) selectFolder(cur);
                    }}
                  >
                    选用当前路径
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <>
              <p className="settings-group-label">备注</p>
              <section className="app-section">
                <div className="app-section-body">
                  <label className="app-field">
                    <span className="app-label">备注</span>
                    <input
                      className="allow-select"
                      value={label}
                      onChange={(e) => setLabel(e.target.value)}
                      placeholder="可选"
                      disabled={locked}
                    />
                  </label>
                </div>
              </section>
            </>
          )}
        </>
      )}

      <div className="app-actions">
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
    </AppPush>
  );
}
