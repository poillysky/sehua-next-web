'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  pauseScrapLibraryEnrich,
  stopScrapLibraryEnrich,
  getScrapLibraryEnrichStatus,
  getScrapLibraryEnrichLogs,
  listScrapLibraryEmbedItems,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichFieldRow,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { AutoscrollLogList } from './AutoscrollLogList';

type LiveTab = 'pending' | 'running' | 'done' | 'fail' | 'log';

const TAB_META: Array<{ id: LiveTab; label: string }> = [
  { id: 'pending', label: '未处理' },
  { id: 'running', label: '处理中' },
  { id: 'done', label: '成功' },
  { id: 'fail', label: '失败' },
  { id: 'log', label: '日志' },
];

const GAP_LABEL: Record<string, string> = {
  no_local: '封面',
  no_media: '外链',
  no_actress: '女优',
  no_studio: '片商',
  no_plot: '剧情',
  thin_title: '标题',
};

function statusLabel(s?: string) {
  if (s === 'running') return '处理中';
  if (s === 'done') return '成功';
  if (s === 'fail') return '失败';
  return '未处理';
}

function rowStatus(s?: string): LiveTab {
  if (s === 'running' || s === 'done' || s === 'fail') return s;
  return 'pending';
}

function statusTone(s?: string): 'pending' | 'running' | 'ok' | 'fail' {
  if (s === 'running') return 'running';
  if (s === 'done') return 'ok';
  if (s === 'fail') return 'fail';
  return 'pending';
}

function gapsText(gaps?: string[]) {
  const parts = (gaps || [])
    .map((g) => GAP_LABEL[g] || g)
    .filter(Boolean);
  return parts.length ? parts.join(' · ') : '—';
}

const LOG_CAP = 200;

function mergeLogLines(base: string[], extra: string[]) {
  const out = [...base];
  for (const line of extra) {
    if (!line) continue;
    if (out.length && out[out.length - 1] === line) continue;
    out.push(line);
  }
  return out.slice(-LOG_CAP);
}

function rowKey(row: ScrapLibraryEnrichQueueItem) {
  return `${row.index ?? ''}:${row.itemId || row.code || ''}`;
}

function detailFromRow(
  row: ScrapLibraryEnrichQueueItem,
  current?: ScrapLibraryEnrichCurrent | null,
): ScrapLibraryEnrichCurrent {
  const same =
    current &&
    ((row.itemId && current.itemId === row.itemId) ||
      (row.code &&
        current.code &&
        row.code.toUpperCase() === current.code.toUpperCase()));
  if (same && current) {
    return {
      ...current,
      code: current.code || row.code,
      itemId: current.itemId || row.itemId,
      gaps: current.gaps?.length ? current.gaps : row.gaps,
      status: current.status || row.status,
      error: current.error || row.error,
      source: current.source || row.source,
      fetchMs:
        typeof current.fetchMs === 'number' ? current.fetchMs : row.fetchMs,
      detailTitle: current.detailTitle || row.detailTitle,
      vectorSynced:
        typeof current.vectorSynced === 'boolean'
          ? current.vectorSynced
          : row.vectorSynced,
      vectorError: current.vectorError || row.vectorError,
      sourceTimings: current.sourceTimings?.length
        ? current.sourceTimings
        : row.sourceTimings,
      fields: current.fields?.length ? current.fields : row.fields,
    };
  }
  return {
    code: row.code,
    itemId: row.itemId,
    gaps: row.gaps,
    status: row.status,
    index: row.index,
    error: row.error,
    source: row.source,
    fetchMs: row.fetchMs,
    detailTitle: row.detailTitle,
    actors: row.actors,
    nfoChanged: row.nfoChanged,
    posterDownloaded: row.posterDownloaded,
    vectorSynced: row.vectorSynced,
    vectorError: row.vectorError,
    sourceTimings: row.sourceTimings,
    fields: row.fields,
    wouldFill: row.wouldFill,
  };
}

function EnrichItemDetail({ detail }: { detail: ScrapLibraryEnrichCurrent }) {
  const timings = detail.sourceTimings || [];
  const fields = detail.fields || [];
  return (
    <div className="enrich-live__detail">
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">番号</span>
            <span className="settings-kv__val allow-select">
              {detail.code || '—'}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span className="settings-kv__val">
              {statusLabel(detail.status)}
              {typeof detail.index === 'number' &&
              typeof detail.total === 'number'
                ? ` · ${detail.index + 1}/${detail.total}`
                : typeof detail.fetchMs === 'number'
                  ? ` · ${detail.fetchMs}ms`
                  : ''}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">缺口</span>
            <span className="settings-kv__val">{gapsText(detail.gaps)}</span>
          </div>
        </li>
        {detail.detailTitle ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">标题</span>
              <span className="settings-kv__val allow-select">
                {detail.detailTitle}
              </span>
            </div>
          </li>
        ) : null}
        {detail.source ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">命中源</span>
              <span className="settings-kv__val">
                {detail.source}
                {typeof detail.fetchMs === 'number'
                  ? ` · ${detail.fetchMs}ms`
                  : ''}
              </span>
            </div>
          </li>
        ) : null}
        {typeof detail.posterDownloaded === 'boolean' ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">封面下载</span>
              <span className="settings-kv__val">
                {detail.posterDownloaded ? '已落盘' : '未落盘'}
              </span>
            </div>
          </li>
        ) : null}
        {detail.status === 'done' ||
        detail.status === 'fail' ||
        typeof detail.vectorSynced === 'boolean' ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">向量</span>
              <span className="settings-kv__val">
                {detail.vectorSynced
                  ? '已同步'
                  : detail.vectorError
                    ? `未同步 · ${detail.vectorError}`
                    : detail.status === 'running'
                      ? '同步中…'
                      : '未同步'}
              </span>
            </div>
          </li>
        ) : null}
        {detail.error ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">错误</span>
              <span className="settings-kv__val">{detail.error}</span>
            </div>
          </li>
        ) : null}
      </ul>

      <p className="settings-group-label">字段情况</p>
      <ul className="settings-group">
        {fields.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                {detail.status === 'running'
                  ? '拉取中…'
                  : '暂无字段结果（旧任务可能未保留）'}
              </span>
            </div>
          </li>
        ) : (
          fields.map((f) => (
            <li key={f.id || f.label}>
              <div className="settings-kv">
                <span className="settings-kv__key">
                  {f.ok ? '✓ ' : '· '}
                  {f.label || f.id}
                </span>
                <span className="settings-kv__val allow-select">
                  {f.ok ? f.value || '有' : '无'}
                </span>
              </div>
            </li>
          ))
        )}
      </ul>

      <p className="settings-group-label">
        源耗时
        {timings.length > 0 ? ` · ${timings.length}` : ''}
      </p>
      <ul className="settings-group">
        {timings.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                暂无源耗时（旧任务可能未保留）
              </span>
            </div>
          </li>
        ) : (
          timings.map((t, i) => {
            const tone =
              t.status === 'done' || t.ok
                ? 'done'
                : t.status === 'fail' || t.error
                  ? 'fail'
                  : t.status === 'skipped'
                    ? 'skip'
                    : 'pending';
            return (
              <li key={`${t.id || i}-${t.ms || 0}`}>
                <div className="settings-kv">
                  <span className="settings-kv__key">
                    <span
                      className={cn(
                        'enrich-live__src-mark',
                        `enrich-live__src-mark--${tone}`,
                      )}
                    />
                    {t.id || '源'}
                  </span>
                  <span className="settings-kv__val">
                    {typeof t.ms === 'number' ? `${t.ms}ms` : '—'}
                    {t.poster ? ' · 封面' : ''}
                    {typeof t.actors === 'number' && t.actors > 0
                      ? ` · 女优${t.actors}`
                      : ''}
                    {t.error ? ` · ${t.error}` : ''}
                  </span>
                </div>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}

function fieldsFromSourceText(src: string): ScrapLibraryEnrichFieldRow[] {
  const text = String(src || '');
  const pick = (label: string, re: RegExp) => {
    const m = text.match(re);
    const val = (m?.[1] || '').trim();
    return { id: label, label, ok: Boolean(val), value: val || undefined };
  };
  return [
    pick('女优', /^女优：(.+)$/m),
    pick('片商', /^片商：(.+)$/m),
    pick('剧情', /^剧情：(.+)$/m),
    pick('标题', /^标题：(.+)$/m),
  ];
}

export function EnrichLivePanel({
  regionId,
  label,
  onBack,
  onStatus,
  onStopped,
  initialStatus = null,
  initialLogs = [],
}: {
  regionId: string;
  label: string;
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  /** 停止后通知列表页关开关、清进度 */
  onStopped?: () => void;
  /** 列表页已有状态，进场即展示，避免空白闪一下 */
  initialStatus?: ScrapLibraryEnrichJobStatus | null;
  initialLogs?: string[];
}) {
  const [tab, setTab] = useState<LiveTab>('pending');
  const [tabTouched, setTabTouched] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [dbDetail, setDbDetail] = useState<ScrapLibraryEnrichCurrent | null>(
    null,
  );
  const [st, setSt] = useState<ScrapLibraryEnrichJobStatus | null>(
    initialStatus,
  );
  const [persistedLogs, setPersistedLogs] = useState<string[]>(() =>
    Array.isArray(initialLogs) ? initialLogs.slice(-LOG_CAP) : [],
  );
  const [msg, setMsg] = useState('');
  const [stopping, setStopping] = useState(false);
  const [hydrated, setHydrated] = useState(Boolean(initialStatus));

  const [logsCleared, setLogsCleared] = useState(false);
  const sessionLiveRef = useRef(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      if (logsCleared) return;
      // 任务进行中不要灌历史库日志，否则角标一上来就是 200
      if (initialStatus?.running) return;
      try {
        const data = await getScrapLibraryEnrichLogs({
          region: regionId,
          limit: LOG_CAP,
        });
        if (!alive || logsCleared || sessionLiveRef.current) return;
        const lines = Array.isArray(data.log) ? data.log : [];
        if (lines.length) {
          setPersistedLogs((prev) =>
            prev.length ? mergeLogLines(prev, lines) : lines.slice(-LOG_CAP),
          );
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      alive = false;
    };
  }, [regionId, logsCleared, initialStatus?.running]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const data = await getScrapLibraryEnrichStatus();
        if (!alive) return;
        setSt(data);
        setHydrated(true);
        if (data.running && logsCleared) {
          setLogsCleared(false);
        }
        const live = data.regionLogs?.[regionId] || [];
        const liveHere =
          Boolean(data.running) &&
          (!data.currentRegion || data.currentRegion === regionId);
        if (liveHere) {
          if (!sessionLiveRef.current) {
            // 本轮开始：只用内存日志，丢掉历史 200
            sessionLiveRef.current = true;
            setPersistedLogs(Array.isArray(live) ? live.slice(-LOG_CAP) : []);
          } else if (!logsCleared && Array.isArray(live) && live.length) {
            setPersistedLogs((prev) => mergeLogLines(prev, live));
          }
        } else {
          sessionLiveRef.current = false;
          if (!logsCleared) {
            if (Array.isArray(live) && live.length) {
              setPersistedLogs((prev) => mergeLogLines(prev, live));
            }
          } else if (!data.running) {
            if (!live.length) {
              setPersistedLogs([]);
            }
          }
        }
        timer = setTimeout(tick, data.running ? 450 : 1200);
      } catch (e) {
        if (!alive) return;
        setHydrated(true);
        setMsg(e instanceof Error ? e.message : '状态读取失败');
        timer = setTimeout(tick, 1600);
      }
    }

    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [regionId, logsCleared]);

  const hasCheckpoint = Boolean(st?.checkpoints?.[regionId]);
  const canStop =
    (st?.running &&
      (!st.currentRegion || st.currentRegion === regionId)) ||
    hasCheckpoint;

  async function onPause() {
    if (stopping || !st?.running) return;
    setStopping(true);
    try {
      await pauseScrapLibraryEnrich();
      onStatus('正在暂停刮削…', 'mute');
      setMsg('已请求暂停 · 进度保留');
    } catch (e) {
      const text = e instanceof Error ? e.message : '暂停失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setStopping(false);
    }
  }

  async function onStop() {
    if (stopping || !canStop) return;
    setStopping(true);
    // 立刻清空本页 UI
    setLogsCleared(true);
    setPersistedLogs([]);
    setSt((prev) =>
      prev
        ? {
            ...prev,
            running: false,
            phase: 'cleared',
            queue: [],
            current: null,
            log: [],
            regionLogs: {
              ...(prev.regionLogs || {}),
              [regionId]: [],
            },
            checkpoints: Object.fromEntries(
              Object.entries(prev.checkpoints || {}).filter(
                ([k]) => k !== regionId,
              ),
            ),
            progress: {
              stage: 'cleared',
              percent: 0,
              done: 0,
              total: 0,
              label: '已停止',
            },
          }
        : prev,
    );
    onStopped?.();
    onStatus('已停止刮削（队列与日志已清除）', 'ok');
    setMsg('已停止 · 队列与日志已清除');
    try {
      await stopScrapLibraryEnrich({ region: regionId });
    } catch (e) {
      const text = e instanceof Error ? e.message : '停止失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setStopping(false);
    }
  }

  const queue = (st?.queue || []) as ScrapLibraryEnrichQueueItem[];
  const current = (st?.current || null) as ScrapLibraryEnrichCurrent | null;

  const tabCounts: Record<LiveTab, number> = {
    pending: Number(st?.queueCounts?.pending ?? 0),
    running: Number(st?.queueCounts?.running ?? 0),
    done: Number(st?.queueCounts?.done ?? 0),
    fail: Number(st?.queueCounts?.fail ?? 0),
    log: 0,
  };
  // 后端未带 queueCounts 时按本地队列统计
  if (!st?.queueCounts) {
    tabCounts.pending = 0;
    tabCounts.running = 0;
    tabCounts.done = 0;
    tabCounts.fail = 0;
    for (const row of queue) {
      tabCounts[rowStatus(row.status)] += 1;
    }
  }

  // 分区日志页只用本区日志，禁止回退到全局 st.log（停止后会误显旧内容）
  const logs = (
    logsCleared
      ? []
      : persistedLogs.length
        ? persistedLogs
        : st?.regionLogs?.[regionId] || []
  ).slice(-LOG_CAP);
  const logCountRaw = Number(st?.regionLogCounts?.[regionId] || 0);
  tabCounts.log =
    logCountRaw > 0
      ? logCountRaw
      : logs.length;

  // 有进行中时默认切到「处理中」（用户点过 tab 后不再抢）
  useEffect(() => {
    if (tabTouched) return;
    if (tabCounts.running > 0) setTab('running');
    else if (tabCounts.pending > 0) setTab('pending');
  }, [tabCounts.running, tabCounts.pending, tabTouched]);

  const filteredQueue =
    tab === 'log'
      ? []
      : queue.filter((row) => rowStatus(row.status) === tab);

  const selectedRow =
    selectedKey == null
      ? null
      : queue.find((r) => rowKey(r) === selectedKey) || null;
  const selectedDetail = (() => {
    if (!selectedRow) return null;
    const base = detailFromRow(selectedRow, current);
    if (!dbDetail) return base;
    // 成功/失败入库回填：补标题与字段（不覆盖本轮源耗时）
    return {
      ...base,
      detailTitle: base.detailTitle || dbDetail.detailTitle,
      fields:
        base.fields && base.fields.length > 0 ? base.fields : dbDetail.fields,
      vectorSynced:
        typeof base.vectorSynced === 'boolean'
          ? base.vectorSynced
          : dbDetail.vectorSynced,
      posterDownloaded:
        typeof base.posterDownloaded === 'boolean'
          ? base.posterDownloaded
          : dbDetail.posterDownloaded,
    };
  })();

  // 切 tab 时关掉详情；当前条若已不在队列则清空
  useEffect(() => {
    setSelectedKey(null);
    setDbDetail(null);
  }, [tab]);
  useEffect(() => {
    if (!selectedKey) {
      setDbDetail(null);
      return;
    }
    if (!queue.some((r) => rowKey(r) === selectedKey)) {
      setSelectedKey(null);
      setDbDetail(null);
    }
  }, [queue, selectedKey]);

  // 成功/失败点进详情时，若队列未留字段，从向量库补一份
  useEffect(() => {
    if (!selectedRow) return;
    const stt = rowStatus(selectedRow.status);
    if (stt !== 'done' && stt !== 'fail') return;
    if ((selectedRow.fields || []).length > 0) return;
    const code = String(selectedRow.code || '').trim();
    const iid = String(selectedRow.itemId || '').trim();
    if (!code && !iid) return;
    let alive = true;
    void (async () => {
      try {
        const page = await listScrapLibraryEmbedItems({
          q: code || iid,
          limit: 8,
        });
        if (!alive) return;
        const hit =
          (page.items || []).find(
            (it) =>
              (iid && it.itemId === iid) ||
              (code &&
                String(it.code || '').toUpperCase() === code.toUpperCase()),
          ) || (page.items || [])[0];
        if (!hit) return;
        const src = String(hit.sourceText || '');
        setDbDetail({
          code: hit.code || code,
          itemId: hit.itemId || iid,
          detailTitle: hit.title || '',
          status: selectedRow.status,
          fields: fieldsFromSourceText(src),
          vectorSynced: true,
          posterDownloaded: Boolean(hit.posterApi || hit.thumbApi),
        });
      } catch {
        /* ignore */
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedRow]);
  const qc = st?.queueCounts;
  const pct = (() => {
    // 与顶栏文案同一套：优先 queueCounts，禁止脱节的 progress.percent
    const src = qc || {
      pending: tabCounts.pending,
      running: tabCounts.running,
      done: tabCounts.done,
      fail: tabCounts.fail,
    };
    const fin = Number(src.done || 0) + Number(src.fail || 0);
    const rem = Number(src.pending || 0) + Number(src.running || 0);
    const tot = fin + rem;
    if (tot > 0) {
      return Math.max(0, Math.min(100, Math.round((100 * fin) / tot)));
    }
    if (
      hasCheckpoint &&
      typeof st?.checkpoints?.[regionId]?.ok === 'number' &&
      typeof st?.checkpoints?.[regionId]?.failed === 'number' &&
      typeof st?.checkpoints?.[regionId]?.remaining === 'number'
    ) {
      const cpFin =
        Number(st.checkpoints[regionId].ok || 0) +
        Number(st.checkpoints[regionId].failed || 0);
      const cpRem = Number(st.checkpoints[regionId].remaining || 0);
      const cpTot = cpFin + cpRem;
      if (cpTot > 0) {
        return Math.max(0, Math.min(100, Math.round((100 * cpFin) / cpTot)));
      }
    }
    return null;
  })();
  const countLabel = (() => {
    if (qc) {
      const fin = Number(qc.done || 0) + Number(qc.fail || 0);
      const rem = Number(qc.pending || 0) + Number(qc.running || 0);
      const tot = fin + rem;
      if (tot > 0) {
        return `${fin.toLocaleString()} / ${tot.toLocaleString()}`;
      }
    }
    if (
      typeof st?.progress?.done === 'number' &&
      typeof st?.progress?.total === 'number' &&
      st.progress.total > 0
    ) {
      return `${st.progress.done.toLocaleString()} / ${st.progress.total.toLocaleString()}`;
    }
    if (hasCheckpoint) {
      return `${(st?.checkpoints?.[regionId]?.done ?? 0).toLocaleString()} / ${(st?.checkpoints?.[regionId]?.total ?? 0).toLocaleString()}`;
    }
    return '';
  })();

  const phaseText = !hydrated && !st
    ? '加载中…'
    : st?.running
      ? st.phase || st.progress?.label || '刮削中…'
      : hasCheckpoint
        ? '已暂停 · 再开继续'
        : st?.phase === 'stopped' || st?.result?.cancelled
          ? '已停止'
          : st?.phase === 'paused' || st?.result?.paused
            ? '已暂停'
            : st?.result
              ? '本轮已结束'
              : '等待任务';

  return (
    <AppPush
      title={
        selectedDetail?.code
          ? `${selectedDetail.code} · 详情`
          : `${label} · 刮削`
      }
      onBack={selectedKey ? () => setSelectedKey(null) : onBack}
      scrollKey={
        selectedDetail?.code
          ? `enrich-live-detail-${selectedDetail.code}`
          : `enrich-live-${regionId}`
      }
      scrollMode="top"
      scrollPin="once"
      right={
        selectedKey ? null : (
        <span className="makers-manage__status-actions">
          {st?.running ? (
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={stopping}
              onClick={() => void onPause()}
            >
              {stopping ? '处理中' : '暂停'}
            </button>
          ) : null}
          {canStop ? (
            <button
              type="button"
              className="makers-manage__probe-btn makers-manage__probe-btn--danger"
              disabled={stopping}
              onClick={() => void onStop()}
            >
              {stopping ? '处理中' : '停止'}
            </button>
          ) : null}
        </span>
        )
      }
    >
      <div
        className={cn(
          'makers-manage makers-manage--detail enrich-live',
          hydrated && 'enrich-live--ready',
        )}
      >
        {selectedDetail ? (
          <EnrichItemDetail detail={selectedDetail} />
        ) : (
          <>
        <div className="enrich-live__head">
          <p className="enrich-live__phase">
            {phaseText}
            {countLabel ? ` · ${countLabel}` : ''}
          </p>
          {st?.running || pct != null || hasCheckpoint ? (
            <div
              className="makers-manage__scan-bar enrich-live__bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct != null ? Math.round(pct) : 0}
            >
              <span style={{ width: `${pct != null ? pct : 0}%` }} />
            </div>
          ) : null}
        </div>

        <div
          className="app-seg enrich-live__tabs enrich-live__tabs--status"
          role="tablist"
          aria-label="队列与日志"
        >
          {TAB_META.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={cn(
                'app-seg__btn',
                tab === t.id && 'app-seg__btn--active',
              )}
              onClick={() => {
                setTabTouched(true);
                setTab(t.id);
              }}
            >
              {t.label}
              {t.id === 'log' ? null : (
                <span className="enrich-live__tab-count">
                  {tabCounts[t.id]}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="enrich-live__pane">
          {tab === 'log' ? (
            <AutoscrollLogList
              className="makers-manage__scan-log allow-select enrich-live__log"
              active={tab === 'log'}
              empty={
                !hydrated
                  ? '加载日志…'
                  : st?.running
                    ? '刮削中，等待日志…'
                    : '暂无日志'
              }
              lines={logs}
            />
          ) : filteredQueue.length === 0 ? (
            <p className="enrich-live__empty">
              {!hydrated
                ? '加载队列…'
                : st?.running && tab === 'pending'
                  ? '正在筛选队列…'
                  : `暂无${TAB_META.find((t) => t.id === tab)?.label || ''}项`}
            </p>
          ) : (
            <>
              {tabCounts[tab] > filteredQueue.length ? (
                <p className="enrich-live__empty enrich-live__queue-hint">
                  显示 {filteredQueue.length.toLocaleString()} /{' '}
                  {tabCounts[tab].toLocaleString()}
                </p>
              ) : (
                <p className="enrich-live__queue-hint">
                  共 {filteredQueue.length.toLocaleString()} 条 · 点条目看详情
                </p>
              )}
              <ul className="settings-group enrich-live__queue">
                {filteredQueue.map((row) => (
                  <li key={`${row.index}-${row.code || row.itemId}`}>
                    <button
                      type="button"
                      className={cn(
                        'settings-nav enrich-live__queue-row',
                        row.status === 'running' &&
                          'enrich-live__queue-row--on',
                        row.status === 'done' &&
                          'enrich-live__queue-row--ok',
                        row.status === 'fail' &&
                          'enrich-live__queue-row--fail',
                      )}
                      onClick={() => {
                        setDbDetail(null);
                        setSelectedKey(rowKey(row));
                      }}
                    >
                      <span
                        className={cn(
                          'enrich-live__queue-badge',
                          `enrich-live__queue-badge--${statusTone(row.status)}`,
                        )}
                      >
                        {statusLabel(row.status)}
                      </span>
                      <span className="settings-nav__main enrich-live__queue-main">
                        <span className="settings-nav__title">
                          {row.code || '—'}
                        </span>
                        <span className="settings-nav__desc">
                          {row.gaps?.length ? gapsText(row.gaps) : '—'}
                          {row.error ? ` · ${row.error}` : ''}
                        </span>
                      </span>
                      <span className="enrich-live__queue-meta">
                        {typeof row.fetchMs === 'number'
                          ? `${row.fetchMs}ms`
                          : ''}
                      </span>
                      <ChevronRight
                        className="settings-nav__chev"
                        size={17}
                        strokeWidth={2.4}
                        aria-hidden
                      />
                    </button>
                  </li>
                ))}
            </ul>
            </>
          )}
        </div>
          </>
        )}

        {msg ? <AppMsg tone="info">{msg}</AppMsg> : null}
      </div>
    </AppPush>
  );
}
