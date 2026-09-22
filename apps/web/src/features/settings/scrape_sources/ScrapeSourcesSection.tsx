'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  getScrapeSources,
  getScrapeSourcesProbeStatus,
  probeAllScrapeSources,
  probeScrapeSource,
  putScrapeSource,
  type ScrapeSourceRow,
  type ScrapeSourcesCatalog,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

function hostOf(url: string): string {
  const s = (url || '').trim();
  if (!s) return '';
  try {
    return new URL(s.includes('://') ? s : `https://${s}`).host;
  } catch {
    return s.replace(/^https?:\/\//i, '').split('/')[0] || s;
  }
}

function hrefOf(url: string): string {
  const s = (url || '').trim();
  if (!s) return '';
  return s.includes('://') ? s : `https://${s}`;
}

function IosSwitch({
  checked,
  disabled,
  'aria-label': ariaLabel,
  onCheckedChange,
}: {
  checked: boolean;
  disabled?: boolean;
  'aria-label': string;
  onCheckedChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      className={cn('makers-ios-switch', checked && 'makers-ios-switch--on')}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onCheckedChange(!checked);
      }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <span className="makers-ios-switch__thumb" />
    </button>
  );
}

function latencyLabel(v: number | null | undefined): string | null {
  if (v === undefined) return null;
  if (v === null) return '…';
  if (v < 0) return '失败';
  return `${v}ms`;
}

function latencyTone(v: number | null | undefined): 'ok' | 'warn' | 'mute' {
  if (v === undefined || v === null) return 'mute';
  if (v < 0) return 'warn';
  if (v < 800) return 'ok';
  if (v < 2000) return 'mute';
  return 'warn';
}

/** 测通失败原因缩成标题行短标签（如 盾拦截） */
function probeFailChip(note: string | undefined): string {
  const s = (note || '').trim();
  if (!s) return '失败';
  if (/盾|拦截|challenge|cloudflare|just a moment|flare/i.test(s)) {
    if (/未能解开|过盾失败/i.test(s)) return '过盾失败';
    if (/未配置/i.test(s)) return '无Flare';
    return '盾拦截';
  }
  if (/年龄|年齢|age_check/i.test(s)) return '年龄门';
  if (/HTTP\s*403/i.test(s)) return 'HTTP 403';
  if (/HTTP\s*\d+/i.test(s)) {
    const m = s.match(/HTTP\s*\d+/i);
    return m ? m[0].toUpperCase() : '失败';
  }
  if (/超时|timeout/i.test(s)) return '超时';
  if (/未识别/i.test(s)) return '未识别';
  if (/无内容/i.test(s)) return '无内容';
  if (/已禁用/i.test(s)) return '已禁用';
  return s.length > 8 ? `${s.slice(0, 8)}…` : s;
}

const GROUP_ICON_TONE: Record<
  string,
  'orange' | 'teal' | 'blue' | 'violet' | 'indigo' | 'green'
> = {
  av: 'orange',
  uncensored: 'teal',
  fc2: 'blue',
  chinese: 'violet',
  western: 'indigo',
  general: 'green',
};

function monogram(label: string): string {
  const s = (label || '').trim();
  if (!s) return '?';
  const ascii = s.match(/[A-Za-z0-9]/)?.[0];
  if (ascii) return ascii.toUpperCase();
  return s.slice(0, 1);
}

function accessChipTone(access?: string): 'adaptive' | 'flare' | 'proxy' | 'direct' {
  if (access === 'proxy_flare') return 'flare';
  if (access === 'proxy') return 'proxy';
  if (access === 'direct') return 'direct';
  return 'adaptive';
}

export function ScrapeSourcesSection({
  onBack,
  onStatus,
}: {
  onBack?: () => void;
  onStatus?: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [catalog, setCatalog] = useState<ScrapeSourcesCatalog | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probingOne, setProbingOne] = useState<string | null>(null);
  const [probeProgress, setProbeProgress] = useState<{
    done: number;
    total: number;
    current: string;
  } | null>(null);
  const [latency, setLatency] = useState<Record<string, number | null>>({});
  const [probeNote, setProbeNote] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState('');

  const [draftEnabled, setDraftEnabled] = useState(true);
  const [draftBase, setDraftBase] = useState('');
  const [draftCookie, setDraftCookie] = useState('');
  const [draftApiKey, setDraftApiKey] = useState('');

  const applyCatalog = useCallback(
    (data: ScrapeSourcesCatalog) => {
      setCatalog(data);
      const latNext: Record<string, number | null> = {};
      const noteNext: Record<string, string> = {};
      for (const s of data.sources || []) {
        const lp = s.lastProbe;
        if (!lp) continue;
        latNext[s.id] =
          lp.ok && typeof lp.ms === 'number' ? lp.ms : lp.ok ? 0 : -1;
        if (lp.message) noteNext[s.id] = lp.message;
      }
      setLatency((prev) => ({ ...prev, ...latNext }));
      setProbeNote((prev) => ({ ...prev, ...noteNext }));
      const enabled = (data.sources || []).filter((s) => s.enabled).length;
      onStatus?.(enabled ? '已就绪' : '未启用', enabled ? 'ok' : 'warn');
    },
    [onStatus],
  );

  const reload = useCallback(async () => {
    const data = await getScrapeSources();
    applyCatalog(data);
    return data;
  }, [applyCatalog]);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        await reload();
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
        onStatus?.('异常', 'warn');
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rowOf = (id: string): ScrapeSourceRow | undefined =>
    catalog?.sources.find((s) => s.id === id);

  function openDetail(sid: string) {
    const row = rowOf(sid);
    if (!row) return;
    setMsg('');
    setDraftEnabled(row.enabled);
    setDraftBase(row.baseUrl || '');
    setDraftCookie(row.cookie || '');
    setDraftApiKey(row.apiKey || '');
    setDetailId(sid);
  }

  async function onToggle(sid: string, enabled: boolean) {
    if (busy || probing) return;
    setBusy(true);
    setMsg('');
    try {
      applyCatalog(await putScrapeSource(sid, { enabled }));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '更新失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSaveDetail() {
    if (!detailId || busy) return;
    setBusy(true);
    setMsg('');
    try {
      applyCatalog(
        await putScrapeSource(detailId, {
          enabled: draftEnabled,
          baseUrl: draftBase.trim(),
          cookie: draftCookie,
          apiKey: draftApiKey,
        }),
      );
      setMsg('已保存');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  async function onProbeOne(sid: string) {
    if (probing || probingOne) return;
    setBusy(true);
    setProbingOne(sid);
    setLatency((prev) => ({ ...prev, [sid]: null }));
    setProbeNote((prev) => ({ ...prev, [sid]: '' }));
    setMsg('正在测主页…');
    try {
      const r = await probeScrapeSource(sid, true);
      setLatency((prev) => ({
        ...prev,
        [sid]: r.ok && typeof r.ms === 'number' ? r.ms : -1,
      }));
      setProbeNote((prev) => ({
        ...prev,
        [sid]: r.message || (r.ok ? '主页可达' : '主页无法打开'),
      }));
      await reload();
      setMsg(r.message || (r.ok ? '主页可达' : '主页无法打开'));
    } catch (e) {
      const text = e instanceof Error ? e.message : '测链失败';
      setLatency((prev) => ({ ...prev, [sid]: -1 }));
      setProbeNote((prev) => ({ ...prev, [sid]: text }));
      setMsg(text);
    } finally {
      setProbingOne(null);
      setBusy(false);
    }
  }

  async function onProbeAll() {
    if (busy || probing || loading) return;
    setProbing(true);
    setMsg('');
    try {
      const started = await probeAllScrapeSources(true);
      setProbeProgress({
        done: 0,
        total: started.total,
        current: '',
      });
      for (;;) {
        await new Promise((r) => setTimeout(r, 600));
        const st = await getScrapeSourcesProbeStatus();
        setProbeProgress({
          done: st.done,
          total: st.total,
          current: st.current,
        });
        for (const r of st.results || []) {
          if (!r.source) continue;
          setLatency((prev) => ({
            ...prev,
            [r.source!]:
              r.ok && typeof r.ms === 'number' ? r.ms : r.ok ? 0 : -1,
          }));
          setProbeNote((prev) => ({
            ...prev,
            [r.source!]: r.message || (r.ok ? '已识别' : '主页无法打开'),
          }));
        }
        if (!st.running) break;
      }
      await reload();
      setMsg('测链完成');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '测链失败');
    } finally {
      setProbing(false);
      setProbeProgress(null);
    }
  }

  const locked = busy || loading || probing;
  const detail = detailId ? rowOf(detailId) : null;

  if (detail && detailId) {
    const live = detail.activeBase || '';
    const liveHref = hrefOf(live);
    return (
      <AppPush
        title={detail.label}
        onBack={() => setDetailId(null)}
        skipEnterAnimation
      >
        <div className="makers-manage makers-manage--detail">
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">启用</span>
                <IosSwitch
                  checked={draftEnabled}
                  disabled={locked}
                  aria-label={`启用 ${detail.label}`}
                  onCheckedChange={setDraftEnabled}
                />
              </div>
            </li>
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">连接方式</span>
                <span className="settings-kv__val">
                  {detail.accessLabel || detail.access || '—'}
                </span>
              </div>
            </li>
            {detail.notes ? (
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">说明</span>
                  <span className="settings-kv__val allow-select">
                    {detail.notes}
                  </span>
                </div>
              </li>
            ) : null}
          </ul>

          <p className="settings-group-label">网站地址</p>
          <section className="makers-manage__editor makers-manage__rise">
            <label className="makers-manage__editor-label">
              <input
                className="allow-select makers-manage__input"
                value={draftBase}
                onChange={(e) => setDraftBase(e.target.value)}
                placeholder={
                  detail.defaultUrl
                    ? `默认 ${detail.defaultUrl}`
                    : 'https://…'
                }
                disabled={locked}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                aria-label="网站地址"
              />
            </label>
            <div className="makers-manage__editor-meta">
              <span>留空则用目录主站；测通只打主站，跳转落地会记入当前生效</span>
            </div>
          </section>

          <p className="settings-group-label">当前生效</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">落地链接</span>
                {liveHref ? (
                  <a
                    className="makers-manage__link makers-manage__link--kv allow-select"
                    href={liveHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={liveHref}
                  >
                    {hostOf(live) || live}
                  </a>
                ) : (
                  <span className="settings-kv__val">未测通</span>
                )}
              </div>
            </li>
          </ul>

          <p className="settings-group-label">Cookie</p>
          <section className="makers-manage__editor makers-manage__rise">
            <label className="makers-manage__editor-label">
              <textarea
                className="allow-select makers-manage__textarea makers-manage__textarea--cookie"
                rows={3}
                value={draftCookie}
                onChange={(e) => setDraftCookie(e.target.value)}
                placeholder={detail.defaultCookie || '可选'}
                disabled={locked}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                aria-label="Cookie"
              />
            </label>
          </section>

          {detail.needsApiKey ? (
            <>
              <p className="settings-group-label">API Key</p>
              <section className="makers-manage__editor makers-manage__rise">
                <label className="makers-manage__editor-label">
                  <input
                    className="allow-select makers-manage__input"
                    value={draftApiKey}
                    onChange={(e) => setDraftApiKey(e.target.value)}
                    placeholder="必填"
                    disabled={locked}
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    aria-label="API Key"
                  />
                </label>
              </section>
            </>
          ) : null}

          <div className="makers-manage__actions makers-manage__rise">
            <button
              type="button"
              className="app-btn-secondary"
              disabled={locked}
              onClick={() => void onProbeOne(detailId)}
            >
              测通
            </button>
            <button
              type="button"
              className="app-btn-primary"
              disabled={locked}
              onClick={() => void onSaveDetail()}
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

  const enabledCount = (catalog?.sources || []).filter((s) => s.enabled).length;

  const listBody = (
    <div className="makers-manage">
      <ul className="settings-group makers-manage__rise">
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">站点目录</span>
              <span className="settings-nav__desc">
                {loading
                  ? '加载中…'
                  : `${enabledCount}/${catalog?.sources.length ?? 0} 已启用`}
              </span>
            </span>
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={locked}
              onClick={() => void onProbeAll()}
            >
              {probing && probeProgress
                ? `${probeProgress.done}/${probeProgress.total}`
                : probing
                  ? '测链中…'
                  : '测试全部'}
            </button>
          </div>
        </li>
      </ul>

      {(catalog?.groups || []).map((group) =>
        group.sources.length ? (
          <div key={group.id}>
            <p className="settings-group-label">{group.label}</p>
            <ul className="settings-group makers-manage__rise">
              {group.sources.map((src) => {
                const lat = latency[src.id];
                const note = probeNote[src.id];
                const last = src.lastProbe;
                const failed =
                  (lat !== undefined && lat !== null && lat < 0) ||
                  (lat === undefined && last?.ok === false);
                const display = src.activeBase || src.displayUrl || src.defaultUrl;
                const href = hrefOf(display);
                const host = hostOf(display);
                const linkPending = src.enabled && !src.activeBase && !last;
                const iconTone = GROUP_ICON_TONE[src.group] || 'blue';
                const probeOk =
                  (lat !== undefined && lat !== null && lat >= 0) ||
                  (lat === undefined && last?.ok === true);
                const live = Boolean(src.enabled && probeOk && !failed);
                const probingThis =
                  probingOne === src.id ||
                  (probing && probeProgress?.current === src.id);
                let statusTone: 'live' | 'pending' | 'off' | 'fail' = 'off';
                if (!src.enabled) statusTone = 'off';
                else if (failed) statusTone = 'fail';
                else if (live) statusTone = 'live';
                else statusTone = 'pending';

                const failNote =
                  note ||
                  (last && !last.ok ? last.message : '') ||
                  '主页不可达';
                const okNote =
                  note || (last?.ok ? last.message || '' : '') || '';

                let subtitle: ReactNode;
                if (probingThis) {
                  subtitle = (
                    <span className="settings-nav__desc">测链中…</span>
                  );
                } else if (failed) {
                  subtitle = (
                    <span className="settings-nav__desc makers-manage__probe-fail">
                      {failNote}
                    </span>
                  );
                } else if (probeOk && href) {
                  const label =
                    okNote && /已识别/.test(okNote)
                      ? okNote.length > 42
                        ? `${okNote.slice(0, 42)}…`
                        : okNote
                      : `当前 · ${host}`;
                  subtitle = (
                    <a
                      className="makers-manage__link allow-select"
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={okNote || href}
                      onClick={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                    >
                      {label}
                    </a>
                  );
                } else if (linkPending) {
                  subtitle = (
                    <span className="settings-nav__desc">
                      {note || (probing ? '排队中…' : '待测通')}
                    </span>
                  );
                } else if (src.enabled) {
                  subtitle = (
                    <span className="settings-nav__desc">
                      {note || host || src.defaultUrl || '待测通'}
                    </span>
                  );
                } else {
                  subtitle = (
                    <span className="settings-nav__desc">已关闭</span>
                  );
                }

                const trailLabel = failed
                  ? probeFailChip(failNote)
                  : latencyLabel(
                      lat !== undefined
                        ? lat
                        : last?.ok
                          ? typeof last.ms === 'number'
                            ? last.ms
                            : 0
                          : undefined,
                    );

                return (
                  <li key={src.id}>
                    <div
                      className={cn(
                        'settings-nav makers-manage__source',
                        !src.enabled && 'makers-manage__source--off',
                        live && 'makers-manage__source--live',
                      )}
                      role="button"
                      tabIndex={loading ? -1 : 0}
                      aria-label={`配置 ${src.label}`}
                      onClick={() => {
                        if (!loading) openDetail(src.id);
                      }}
                      onKeyDown={(e) => {
                        if (loading) return;
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          openDetail(src.id);
                        }
                      }}
                    >
                      <span
                        className={cn(
                          'settings-nav__icon',
                          `settings-nav__icon--${iconTone}`,
                          'makers-manage__source-icon',
                        )}
                        aria-hidden
                      >
                        {monogram(src.label)}
                      </span>
                      <span className="settings-nav__main">
                        <span className="makers-manage__title-row">
                          <span className="makers-manage__title-lead">
                            <span
                              className={cn(
                                'makers-manage__status-dot',
                                `makers-manage__status-dot--${statusTone}`,
                                probingThis && 'makers-manage__status-dot--pulse',
                              )}
                              aria-hidden
                            />
                            <span className="settings-nav__title">{src.label}</span>
                            {src.accessLabel ? (
                              <span
                                className={cn(
                                  'makers-manage__access-chip',
                                  `makers-manage__access-chip--${accessChipTone(src.access)}`,
                                )}
                              >
                                {src.accessLabel}
                              </span>
                            ) : null}
                          </span>
                          {trailLabel ? (
                            <span
                              className={cn(
                                'makers-manage__latency',
                                `makers-manage__latency--${latencyTone(lat)}`,
                              )}
                              title={failed ? note || trailLabel : undefined}
                            >
                              {trailLabel}
                            </span>
                          ) : null}
                        </span>
                        {subtitle}
                      </span>
                      {src.enabled ? (
                        <button
                          type="button"
                          className="makers-manage__probe-btn makers-manage__probe-btn--row"
                          disabled={locked}
                          aria-label={`测通 ${src.label}`}
                          title="测通此源"
                          onClick={(e) => {
                            e.stopPropagation();
                            void onProbeOne(src.id);
                          }}
                          onPointerDown={(e) => e.stopPropagation()}
                        >
                          {probingOne === src.id ? '…' : '测通'}
                        </button>
                      ) : null}
                      <span
                        className="makers-manage__switch-wrap"
                        onClick={(e) => e.stopPropagation()}
                        onPointerDown={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                      >
                        <IosSwitch
                          checked={src.enabled}
                          disabled={locked}
                          aria-label={`启用 ${src.label}`}
                          onCheckedChange={(v) => void onToggle(src.id, Boolean(v))}
                        />
                      </span>
                      <ChevronRight
                        className="settings-nav__chev makers-manage__source-chev"
                        size={16}
                        strokeWidth={2.4}
                        aria-hidden
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null,
      )}

      <AppMsg allowSelect onDismiss={() => setMsg('')}>
        {msg}
      </AppMsg>
    </div>
  );

  if (onBack) {
    return (
      <AppPush title="数据源" onBack={onBack}>
        {listBody}
      </AppPush>
    );
  }

  return listBody;
}
