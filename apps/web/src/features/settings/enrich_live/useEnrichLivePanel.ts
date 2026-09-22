'use client';

import { startTransition, useEffect, useRef, useState } from 'react';
import {
  getScrapLibraryEnrichLogs,
  type EnrichMonitorInflight,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import {
  detailFromRow,
  formatQueueScanLabel,
  isPartialOk,
  LOG_CAP,
  mergeLogLines,
  normalizeSoftSuccessRow,
  QUEUE_PAGE_SIZE,
  readCachedPendingTotal,
  rowKey,
  rowStatus,
  type LiveTab,
} from './queueFormat';
import { buildEnrichLiveActions } from './enrichLiveActions';
import { attachEnrichLiveRegionBoot } from './enrichLiveBootstrap';
import { attachEnrichLiveDetailHydrate } from './enrichLiveDetail';
import { buildEnrichLiveQueueOps } from './enrichLiveQueueOps';
import { buildEnrichLiveStatusHandlers } from './enrichLiveStatus';

export function useEnrichLivePanel({
  regionId,
  label,
  onBack,
  onStatus,
  initialStatus = null,
  initialLogs = [],
}: {
  regionId: string;
  label: string;
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
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
  const [clearing, setClearing] = useState(false);
  const [rescraping, setRescraping] = useState(false);
  const [hydrated, setHydrated] = useState(Boolean(initialStatus));

  const [logsCleared, setLogsCleared] = useState(false);
  const [queueScanning, setQueueScanning] = useState(false);
  const [retryingFails, setRetryingFails] = useState(false);
  const [retryingSofts, setRetryingSofts] = useState(false);
  const [codeQuery, setCodeQuery] = useState('');
  const [searchCode, setSearchCode] = useState('');
  const [searchItems, setSearchItems] = useState<ScrapLibraryEnrichQueueItem[]>(
    [],
  );
  const [searching, setSearching] = useState(false);
  const sessionLiveRef = useRef(false);
  const queueScanDoneRef = useRef(false);
  const searchActiveRef = useRef(false);
  searchActiveRef.current = Boolean(searchCode);
  const [queueItems, setQueueItems] = useState<ScrapLibraryEnrichQueueItem[]>(
    [],
  );
  const [queueCounts, setQueueCounts] = useState({
    pending: 0,
    running: 0,
    done: 0,
    soft: 0,
    fail: 0,
  });
  /** 各 tab 库内可翻页行数；角标用 queueCounts 全量 */
  const [listTotals, setListTotals] = useState<Partial<Record<LiveTab, number>>>(
    {},
  );
  const [queuePage, setQueuePage] = useState(1);
  const [queuePaging, setQueuePaging] = useState(false);
  /** 引导读表完成；tab effect 依赖它，避免「引导未完就切 tab → 永久空列表」 */
  const [queueReady, setQueueReady] = useState(false);
  const queuePageRef = useRef(1);
  queuePageRef.current = queuePage;
  /** 切 tab / 翻页拉库期间，禁止 SSE 用工作队列重排列表 */
  const queueHydratingRef = useRef(false);
  /** 清空·扫描进行中：角标只跟 queueScan */
  const queueScanActiveRef = useRef(false);
  /**
   * 失败/软成功重试后，SSE 旧角标不得再抬回去，直到服务端报到不高于该值。
   * ⚠️ 必须带 TTL：重试后服务端真值往往就是 0（失败/软成功全被转走），
   * 而「服务端报 ≤ 上限才解除」这个条件在真值 0 时永远不成立 ——
   * 于是重试过一次的分区，失败/软成功角标被**永久钉死在 0**，
   * 后面新产生的失败也显示不出来。TTL 到期即失效，回归「只压住重试瞬间的
   * 陈旧 SSE 帧」这个本意。
   */
  const CEIL_TTL_MS = 30_000;
  const failCeilRef = useRef<{ v: number; until: number } | null>(null);
  const softCeilRef = useRef<{ v: number; until: number } | null>(null);
  /** 成功/软成功/失败：角标上涨时防抖回读库表（按 updated_at），勿用工作队列插旧号 */
  const resultTabReloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const resultTabCountRef = useRef({ soft: 0, done: 0, fail: 0 });
  /**
   * 角标最新值。SSE 回调是长生命周期闭包，直接读 `queueCounts` 会拿到陈旧值；
   * 防塌陷比较（服务端读库失败时保留旧角标）必须用 ref。
   */
  const queueCountsRef = useRef(queueCounts);
  queueCountsRef.current = queueCounts;
  const queuePaneRef = useRef<HTMLDivElement | null>(null);
  /** 缺口总数（可大于列表条数）；tab 切换读表时仍保留 */
  const pendingTotalRef = useRef(0);
  /** 各 tab 仅缓存第 1 页，避免翻页结果污染回切 */
  const tabCacheRef = useRef<Partial<Record<LiveTab, ScrapLibraryEnrichQueueItem[]>>>(
    {},
  );
  /**
   * 成功类 tab 已从库表 hydrate 过：扫描 SSE 的 samples*（按扫序多为 AARM）
   * 不得再盖掉库表按 updated_at 的真列表。
   */
  const tabDbLoadedRef = useRef<Partial<Record<LiveTab, boolean>>>({});
  const loadSeqRef = useRef(0);
  const tabRef = useRef<LiveTab>(tab);
  tabRef.current = tab;

  const {
    applyQueuePayload,
    loadQueueTab,
    goQueuePage,
    clearCodeSearch,
    runCodeSearch,
    runQueueScan,
  } = buildEnrichLiveQueueOps({
    regionId,
    st,
    tab,
    queuePage,
    searchCode,
    codeQuery,
    listTotals,
    queueCounts,
    setSearchCode,
    setCodeQuery,
    setSearchItems,
    setSearching,
    setSelectedKey,
    setDbDetail,
    setQueueItems,
    setQueueCounts,
    setListTotals,
    setQueuePage,
    setQueuePaging,
    setQueueScanning,
    setMsg,
    setTab,
    setTabTouched,
    queuePageRef,
    queueHydratingRef,
    queueScanActiveRef,
    queueScanDoneRef,
    searchActiveRef,
    pendingTotalRef,
    tabCacheRef,
    tabDbLoadedRef,
    loadSeqRef,
    tabRef,
    onStatus,
    logsCleared,
    setLogsCleared,
  });

  useEffect(() => {
    queueScanDoneRef.current = false;
    pendingTotalRef.current = readCachedPendingTotal(regionId);
    tabCacheRef.current = {};
    tabDbLoadedRef.current = {};
    queueScanActiveRef.current = false;
    failCeilRef.current = null;
    softCeilRef.current = null;
    loadSeqRef.current += 1;
    setQueueReady(false);
    setQueueItems([]);
    setQueueCounts({ pending: 0, running: 0, done: 0, soft: 0, fail: 0 });
    setListTotals({});
    setQueuePage(1);
    setLogsCleared(false);
    setQueueScanning(false);
  }, [regionId]);

  // 进页：有队列只读表；空队列不自动全量扫描。再进同区不重扫。
  useEffect(() => {
    return attachEnrichLiveRegionBoot({
      regionId,
      applyQueuePayload,
      pendingTotalRef,
      queueScanDoneRef,
      tabRef,
      setQueueScanning,
      setMsg,
      setQueueReady,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅 region 引导
  }, [regionId]);

  // 切换 tab / 翻页：第 1 页可用缓存瞬切，再拉当前页（同步写入列表）
  useEffect(() => {
    if (!queueReady || logsCleared) return;
    queuePaneRef.current?.scrollTo?.({ top: 0 });
    if (queuePage === 1) {
      const cached = tabCacheRef.current[tab];
      // 仅非空缓存瞬切；空数组多半是竞态脏缓存，交给下面重拉
      if (cached && cached.length > 0) {
        setQueueItems(cached);
      } else {
        setQueueItems([]);
      }
    } else {
      // 翻页先清空，避免仍显示上一页造成「没变」的错觉
      setQueueItems([]);
    }
    let alive = true;
    setQueuePaging(true);
    void (async () => {
      try {
        await loadQueueTab(tab, queuePage);
      } catch {
        if (!alive) return;
      } finally {
        if (alive) setQueuePaging(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tab/页码/引导完成拉一次
  }, [tab, queuePage, regionId, logsCleared, queueReady]);

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

  const { attach: attachStatusSubscription } = buildEnrichLiveStatusHandlers({
    regionId,
    logsCleared,
    setSt,
    setHydrated,
    setPersistedLogs,
    setQueueItems,
    setQueueCounts,
    setMsg,
    sessionLiveRef,
    queueScanActiveRef,
    queueHydratingRef,
    searchActiveRef,
    failCeilRef,
    softCeilRef,
    resultTabReloadTimerRef,
    resultTabCountRef,
    queueCountsRef,
    pendingTotalRef,
    tabCacheRef,
    tabDbLoadedRef,
    tabRef,
    queuePageRef,
    loadQueueTab,
  });

  useEffect(() => {
    return attachStatusSubscription();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅 region / 清日志重订 SSE
  }, [regionId, logsCleared]);

  const hasCheckpoint = Boolean(st?.checkpoints?.[regionId]);

  const queue = queueItems;
  const current = (st?.current || null) as ScrapLibraryEnrichCurrent | null;
  const queueScanHere =
    Boolean(st?.queueScan?.active) &&
    (!st?.queueScan?.region || st.queueScan.region === regionId);
  const scanTip =
    (clearing || queueScanning || queueScanHere) &&
    (formatQueueScanLabel(st?.queueScan) ||
      (clearing && !queueScanning
        ? '清空日志…'
        : queueScanning || queueScanHere
          ? '扫描本地分类…'
          : ''));

  const monitorInflightEarly = Array.isArray(st?.monitor?.inflight)
    ? st.monitor.inflight
    : [];
  const queueRunningN = (st?.queue || []).filter(
    (r) => rowStatus(r.status) === 'running',
  ).length;
  const currentLive = Boolean(
    st?.running &&
      st.current &&
      (String(st.current.code || '').trim() ||
        String(st.current.itemId || '').trim()) &&
      rowStatus(st.current.status) !== 'done' &&
      rowStatus(st.current.status) !== 'fail',
  );
  const inflightN = Math.max(
    Number(st?.monitor?.summary?.inflightN || 0),
    monitorInflightEarly.length,
    queueRunningN,
    currentLive ? 1 : 0,
  );
  const tabCounts: Record<LiveTab, number> = {
    pending: Number(queueCounts.pending || 0),
    // 处理中 = 占槽；监控空时用队列 running 行和 current 兜底
    running: st?.running ? inflightN : 0,
    done: Number(queueCounts.done || 0),
    soft: Number(queueCounts.soft || 0),
    fail: Number(queueCounts.fail || 0),
  };

  // 有进行中时默认切到「处理中」（用户点过 tab 后不再抢）；勿重置页码
  useEffect(() => {
    if (tabTouched) return;
    if (st?.running || tabCounts.running > 0) {
      if (tab !== 'running') setTab('running');
    } else if (tabCounts.pending > 0) {
      if (tab !== 'pending') setTab('pending');
    }
  }, [st?.running, tabCounts.running, tabCounts.pending, tabTouched, tab]);

  const searchActive = Boolean(searchCode);
  const filteredQueue = searchActive
    ? searchItems.map(normalizeSoftSuccessRow)
    : queue
        .map(normalizeSoftSuccessRow)
        .filter((r) => {
          if (tab === 'fail') return rowStatus(r.status) === 'fail';
          if (tab === 'soft')
            return rowStatus(r.status) === 'done' && isPartialOk(r);
          if (tab === 'done')
            return rowStatus(r.status) === 'done' && !isPartialOk(r);
          return rowStatus(r.status) === tab;
        });
  const queueTotalForTab = Number(
    listTotals[tab] ?? tabCounts[tab] ?? 0,
  );
  const queuePageTotal = Math.max(
    1,
    Math.ceil(queueTotalForTab / QUEUE_PAGE_SIZE),
  );
  const pageShown = Math.min(queuePage, queuePageTotal);
  const showQueuePager =
    !searchActive &&
    tab !== 'running' &&
    filteredQueue.length > 0 &&
    queuePageTotal > 1;
  const monitor = st?.monitor || null;
  const monitorInflight = monitorInflightEarly;
  const liveRunningPool = (() => {
    const fromStatus = (st?.queue || []).filter(
      (r) => rowStatus(r.status) === 'running',
    );
    if (fromStatus.length) return fromStatus;
    return queueItems.filter((r) => rowStatus(r.status) === 'running');
  })();
  const currentRunningRow: EnrichMonitorInflight | null = currentLive
    ? {
        code: st?.current?.code,
        itemId: st?.current?.itemId,
        phase: 'fetch',
        phaseLabel: '处理中',
        elapsedMs:
          typeof st?.current?.totalMs === 'number'
            ? st.current.totalMs
            : typeof st?.current?.fetchMs === 'number'
              ? st.current.fetchMs
              : 0,
        sources: st?.current?.sourceTimings,
      }
    : null;
  const runningViewRows: EnrichMonitorInflight[] = monitorInflight.length
    ? monitorInflight
    : liveRunningPool.length
      ? liveRunningPool.map((r) => ({
        code: r.code,
        itemId: r.itemId,
        phase: 'fetch',
        phaseLabel: '处理中',
        elapsedMs:
          typeof r.totalMs === 'number'
            ? r.totalMs
            : typeof r.fetchMs === 'number'
              ? r.fetchMs
              : 0,
        sources: r.sourceTimings,
        stall: r.stallLabel ? { label: r.stallLabel } : null,
      }))
      : currentRunningRow
        ? [currentRunningRow]
        : [];
  const hasRunningRows = runningViewRows.length > 0;

  const selectedRow =
    selectedKey == null
      ? null
      : searchItems.find((r) => rowKey(r) === selectedKey) ||
        queue.find((r) => rowKey(r) === selectedKey) ||
        liveRunningPool.find((r) => rowKey(r) === selectedKey) ||
        (st?.queue || []).find((r) => rowKey(r) === selectedKey) ||
        null;
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
        base.vectorSkipped || dbDetail.vectorSkipped
          ? false
          : typeof base.vectorSynced === 'boolean'
            ? base.vectorSynced
            : dbDetail.vectorSynced,
      vectorSkipped:
        typeof base.vectorSkipped === 'boolean'
          ? base.vectorSkipped
          : dbDetail.vectorSkipped,
      posterDownloaded:
        typeof base.posterDownloaded === 'boolean'
          ? base.posterDownloaded
          : dbDetail.posterDownloaded,
    };
  })();

  const {
    onPause,
    onRetryFails,
    onRetrySofts,
    onClearAndScan,
    onRescrapeSelected,
  } = buildEnrichLiveActions({
    regionId,
    onStatus,
    st,
    setSt,
    stopping,
    clearing,
    rescraping,
    retryingFails,
    retryingSofts,
    queueScanning,
    queueCounts,
    setStopping,
    setClearing,
    setRescraping,
    setRetryingFails,
    setRetryingSofts,
    setQueueScanning,
    setMsg,
    setLogsCleared,
    setPersistedLogs,
    setTab,
    setTabTouched,
    setQueuePage,
    setQueueItems,
    setQueueCounts,
    setListTotals,
    setSelectedKey,
    setDbDetail,
    selectedRow,
    queueScanDoneRef,
    queueScanActiveRef,
    failCeilRef,
    softCeilRef,
    tabCacheRef,
    tabDbLoadedRef,
    tabRef,
    loadSeqRef,
    pendingTotalRef,
    CEIL_TTL_MS,
    applyQueuePayload,
    loadQueueTab,
    runQueueScan,
  });


  // 切 tab 时关掉详情；当前条若已不在队列则清空
  useEffect(() => {
    setSelectedKey(null);
    setDbDetail(null);
  }, [tab]);
  useEffect(() => {
    // selectedKey empty: do not setState — SSE st.queue identity churn
    // caused Maximum update depth even with functional bailout.
    // Clear dbDetail wherever selectedKey is cleared.
    if (!selectedKey) return;
    const runningFromStatus = (st?.queue || []).filter(
      (r) => rowStatus(r.status) === 'running',
    );
    const inPool =
      searchItems.some((r) => rowKey(r) === selectedKey) ||
      queueItems.some((r) => rowKey(r) === selectedKey) ||
      runningFromStatus.some((r) => rowKey(r) === selectedKey);
    if (!inPool) {
      setSelectedKey(null);
      setDbDetail(null);
    }
  }, [queueItems, searchItems, selectedKey, st?.queue]);

  // 成功/失败点进详情：优先用队列表已落库字段；空壳再从向量库补
  useEffect(() => {
    return attachEnrichLiveDetailHydrate({
      regionId,
      selectedRow,
      setQueueItems,
      setDbDetail,
    });
  }, [selectedRow, regionId]);

  function selectTab(next: LiveTab) {
    if (searchActive) clearCodeSearch();
    setTabTouched(true);
    setQueuePage(1);
    const qs = st?.queueScan;
    const qsHere =
      Boolean(qs?.active) && (!qs?.region || qs.region === regionId);
    const live =
      Boolean(st?.running) &&
      (!st?.currentRegion || st.currentRegion === regionId);
    if (
      (qsHere || live) &&
      (next === 'done' || next === 'soft' || next === 'fail')
    ) {
      delete tabCacheRef.current[next];
      tabDbLoadedRef.current[next] = true;
      setQueueItems([]);
      setTab(next);
      return;
    }
    const cached = tabCacheRef.current[next];
    if (cached) {
      startTransition(() => setQueueItems(cached));
    }
    setTab(next);
  }

  return {
    regionId,
    label,
    onBack,
    tab,
    setTab,
    tabTouched,
    setTabTouched,
    selectedKey,
    setSelectedKey,
    dbDetail,
    setDbDetail,
    st,
    msg,
    stopping,
    clearing,
    rescraping,
    hydrated,
    queueScanning,
    retryingFails,
    retryingSofts,
    codeQuery,
    setCodeQuery,
    searchCode,
    searching,
    queueItems,
    queuePage,
    queuePaging,
    queuePaneRef,
    tabCacheRef,
    tabDbLoadedRef,
    hasCheckpoint,
    queueScanHere,
    scanTip,
    monitor,
    monitorInflight,
    liveRunningPool,
    runningViewRows,
    hasRunningRows,
    tabCounts,
    searchActive,
    filteredQueue,
    queueTotalForTab,
    queuePageTotal,
    pageShown,
    showQueuePager,
    selectedRow,
    selectedDetail,
    applyQueuePayload,
    loadQueueTab,
    goQueuePage,
    clearCodeSearch,
    runCodeSearch,
    runQueueScan,
    onPause,
    onRetryFails,
    onRetrySofts,
    onClearAndScan,
    onRescrapeSelected,
    selectTab,
  };
}
