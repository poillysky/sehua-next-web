'use client';

import { startTransition } from 'react';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import {
  getScrapLibraryEnrichQueueLog,
  scanScrapLibraryEnrichQueue,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import {
  enrichLiveBootstrapped,
  isPartialOk,
  normalizeSoftSuccessRow,
  pendingTotalStorageKey,
  QUEUE_PAGE_SIZE,
  readCachedPendingTotal,
  rowStatus,
  type LiveTab,
  writeCachedPendingTotal,
} from './queueFormat';

export type EnrichLiveQueueOpsDeps = {
  regionId: string;
  st: ScrapLibraryEnrichJobStatus | null;
  tab: LiveTab;
  queuePage: number;
  searchCode: string;
  codeQuery: string;
  listTotals: Partial<Record<LiveTab, number>>;
  queueCounts: {
    pending: number;
    running: number;
    done: number;
    soft: number;
    fail: number;
  };
  setSearchCode: Dispatch<SetStateAction<string>>;
  setCodeQuery: Dispatch<SetStateAction<string>>;
  setSearchItems: Dispatch<SetStateAction<ScrapLibraryEnrichQueueItem[]>>;
  setSearching: Dispatch<SetStateAction<boolean>>;
  setSelectedKey: Dispatch<SetStateAction<string | null>>;
  setDbDetail: Dispatch<SetStateAction<ScrapLibraryEnrichCurrent | null>>;
  setQueueItems: Dispatch<SetStateAction<ScrapLibraryEnrichQueueItem[]>>;
  setQueueCounts: Dispatch<
    SetStateAction<{
      pending: number;
      running: number;
      done: number;
      soft: number;
      fail: number;
    }>
  >;
  setListTotals: Dispatch<SetStateAction<Partial<Record<LiveTab, number>>>>;
  setQueuePage: Dispatch<SetStateAction<number>>;
  setQueuePaging: Dispatch<SetStateAction<boolean>>;
  setQueueScanning: Dispatch<SetStateAction<boolean>>;
  setMsg: Dispatch<SetStateAction<string>>;
  setTab: Dispatch<SetStateAction<LiveTab>>;
  setTabTouched: Dispatch<SetStateAction<boolean>>;
  queuePageRef: MutableRefObject<number>;
  queueHydratingRef: MutableRefObject<boolean>;
  queueScanActiveRef: MutableRefObject<boolean>;
  queueScanDoneRef: MutableRefObject<boolean>;
  searchActiveRef: MutableRefObject<boolean>;
  pendingTotalRef: MutableRefObject<number>;
  tabCacheRef: MutableRefObject<Partial<Record<LiveTab, ScrapLibraryEnrichQueueItem[]>>>;
  tabDbLoadedRef: MutableRefObject<Partial<Record<LiveTab, boolean>>>;
  loadSeqRef: MutableRefObject<number>;
  tabRef: MutableRefObject<LiveTab>;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  /** 清空日志后为 true；拉表前短路 */
  logsCleared: boolean;
  setLogsCleared: Dispatch<SetStateAction<boolean>>;
};

export function buildEnrichLiveQueueOps(d: EnrichLiveQueueOpsDeps) {
  const {
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
  } = d;

  function applyQueuePayload(data: {
    counts?: {
      pending?: number;
      running?: number;
      done?: number;
      soft?: number;
      fail?: number;
    };
    items?: ScrapLibraryEnrichQueueItem[];
    pendingTotal?: number;
    scannedN?: number;
    /** 库内可翻页行数；角标与分类全量对齐 */
    total?: number;
    localDone?: number;
    localSoft?: number;
    localFail?: number;
    /** 写入哪个 tab 的缓存；默认当前 tab */
    cacheTab?: LiveTab;
    /** 切 tab 只刷列表时勿改角标，避免数字跟着 tab 跳 */
    updateCounts?: boolean;
    /** 列表页码；仅第 1 页写入 tab 缓存 */
    page?: number;
  }) {
    const counts = data.counts || {
      pending: 0,
      running: 0,
      done: 0,
      soft: 0,
      fail: 0,
    };
    const shouldUpdateCounts = data.updateCounts !== false;
    if (shouldUpdateCounts) {
      // 角标只认队列表 counts；pendingTotal / local* 是历史旁路，不再覆盖。
      const pending = Number(counts.pending || 0);
      if (pending > 0) {
        pendingTotalRef.current = pending;
        writeCachedPendingTotal(regionId, pending);
      } else {
        pendingTotalRef.current = 0;
        try {
          sessionStorage.removeItem(pendingTotalStorageKey(regionId));
        } catch {
          /* ignore */
        }
      }
      const noMid =
        !st?.running ||
        st?.halt === 'pause' ||
        st?.halt === 'stop' ||
        st?.phase === 'paused' ||
        st?.phase === 'stopped';
      const doneN = Number(counts.done || 0);
      const softN = Number(counts.soft || 0);
      const failN = Number(counts.fail || 0);
      const runN = Number(counts.running || 0);
      setQueueCounts({
        pending: noMid ? pending + runN : pending,
        running: noMid ? 0 : runN,
        done: doneN,
        soft: softN,
        fail: failN,
      });
      setListTotals((prev) => ({
        ...prev,
        pending: noMid ? pending + runN : pending,
        done: doneN,
        soft: softN,
        fail: failN,
      }));
    } else {
      // 切 tab 读表：counts 来自同一队列表 COUNT，允许降到 0。
      const doneN = Number(counts.done || 0);
      const softN = Number(counts.soft || 0);
      const failN = Number(counts.fail || 0);
      setQueueCounts((prev) => ({
        ...prev,
        done: doneN,
        soft: softN,
        fail: failN,
      }));
      setListTotals((prev) => ({
        ...prev,
        done: doneN,
        soft: softN,
        fail: failN,
      }));
    }
    const curTab = data.cacheTab || tabRef.current;
    if (typeof data.total === 'number' && Number.isFinite(data.total)) {
      const listed = Math.max(0, Math.floor(Number(data.total) || 0));
      setListTotals((prev) => {
        if (curTab !== 'pending') {
          return { ...prev, [curTab]: listed };
        }
        // 未处理 total 以本次接口为准（队列表），不与旧缓存取大
        if (listed > 0) {
          pendingTotalRef.current = listed;
          writeCachedPendingTotal(regionId, listed);
        }
        return { ...prev, pending: listed };
      });
    }
    const noMid =
      !st?.running ||
      st?.halt === 'pause' ||
      st?.halt === 'stop' ||
      st?.phase === 'paused' ||
      st?.phase === 'stopped';
    if (curTab === 'running' && noMid) {
      tabCacheRef.current.running = [];
      if (tabRef.current === 'running') {
        setQueueItems([]);
      }
      return;
    }
    if (Array.isArray(data.items)) {
      const raw = data.items;
      // 软缺口只影响本页展示，不改全局角标（角标以 SSE/扫描 counts 为准）
      let items = raw.map(normalizeSoftSuccessRow);
      // 服务端已按 status 过滤；客户端再滤一层防脏数据。
      // 注意：必须用 cacheTab（请求时的 tab），不能拿「用户后来切到的 tab」去滤，
      // 否则 pending 回包会被滤成空并写进成功 tab 缓存。
      if (curTab === 'fail') {
        items = items.filter((r) => rowStatus(r.status) === 'fail');
      } else if (curTab === 'soft') {
        items = items.filter(
          (r) => rowStatus(r.status) === 'done' && isPartialOk(r),
        );
      } else if (curTab === 'done') {
        items = items.filter(
          (r) => rowStatus(r.status) === 'done' && !isPartialOk(r),
        );
      } else if (curTab === 'pending' || curTab === 'running') {
        items = items.filter((r) => rowStatus(r.status) === curTab);
      }
      const pageN = Math.max(
        1,
        Math.floor(data.page || queuePageRef.current || 1),
      );
      // 只缓存第 1 页；列表必须同步 setState（startTransition 会被 status 流打断）
      if (pageN <= 1) {
        tabCacheRef.current[curTab] = items;
        if (curTab === 'done' || curTab === 'soft' || curTab === 'fail') {
          tabDbLoadedRef.current[curTab] = true;
        }
      }
      // 过期页响应丢弃，避免翻页后又被旧请求盖回第一页
      if (tabRef.current === curTab && pageN === queuePageRef.current) {
        setQueueItems(items);
      }
    }
    // 切 tab / 翻页只换列表。角标只由扫描进度、状态 SSE、重试结果更新。
  }

  async function loadQueueTab(status: LiveTab, page = queuePageRef.current) {
    if (logsCleared) return;
    const seq = ++loadSeqRef.current;
    const pageSafe = Math.max(1, Math.floor(page || 1));
    queueHydratingRef.current = true;
    try {
      const data = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        status,
        limit: QUEUE_PAGE_SIZE,
        offset: (pageSafe - 1) * QUEUE_PAGE_SIZE,
      });
      if (seq !== loadSeqRef.current) return;
      if (status === 'done' || status === 'soft' || status === 'fail') {
        tabDbLoadedRef.current[status] = true;
      }
      applyQueuePayload({
        ...data,
        cacheTab: status,
        updateCounts: false,
        page: pageSafe,
        pendingTotal: pendingTotalRef.current || readCachedPendingTotal(regionId),
      });
    } finally {
      if (seq === loadSeqRef.current) {
        queueHydratingRef.current = false;
      }
    }
  }

  function goQueuePage(next: number) {
    setTabTouched(true);
    const listed = Number(listTotals[tab] ?? queueCounts[tab] ?? 0);
    const total = Math.max(1, Math.ceil(listed / QUEUE_PAGE_SIZE));
    const p = Math.max(1, Math.min(total, Math.floor(next || 1)));
    if (p === queuePageRef.current) return;
    setQueuePage(p);
  }

  function clearCodeSearch() {
    setSearchCode('');
    setCodeQuery('');
    setSearchItems([]);
    setSearching(false);
    setSelectedKey(null);
    setDbDetail(null);
  }

  async function runCodeSearch(raw?: string) {
    const q = String(raw ?? codeQuery)
      .trim()
      .toUpperCase()
      .replace(/[\s　]+/g, '');
    if (!q) {
      clearCodeSearch();
      return;
    }
    setSearching(true);
    setSearchCode(q);
    setCodeQuery(q);
    setSelectedKey(null);
    setDbDetail(null);
    // 先用各 tab 缓存做即时预览（仍无视当前 tab）
    const localHits: ScrapLibraryEnrichQueueItem[] = [];
    const seen = new Set<string>();
    const pushLocal = (row: ScrapLibraryEnrichQueueItem) => {
      const code = String(row.code || '')
        .trim()
        .toUpperCase()
        .replace(/[\s　]+/g, '');
      if (!code) return;
      if (!(code === q || (q.length >= 2 && code.startsWith(q)))) return;
      const key = String(row.itemId || row.logId || code).trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      localHits.push(normalizeSoftSuccessRow(row));
    };
    for (const rows of Object.values(tabCacheRef.current)) {
      if (!Array.isArray(rows)) continue;
      for (const r of rows) pushLocal(r);
    }
    for (const r of queueItems) pushLocal(r);
    if (localHits.length) setSearchItems(localHits);
    try {
      // 故意不传 status：全局跨未处理/处理中/成功/软成功/失败
      const data = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        code: q,
        limit: 50,
      });
      setSearchItems(
        (data.items || []).map((r) => normalizeSoftSuccessRow(r)),
      );
    } catch (e) {
      if (!localHits.length) setSearchItems([]);
      setMsg(e instanceof Error ? e.message : '搜索失败');
    } finally {
      setSearching(false);
    }
  }

  async function runQueueScan() {
    setLogsCleared(false);
    setQueueScanning(true);
    queueScanActiveRef.current = true;
    setMsg('');
    tabCacheRef.current = {};
    tabDbLoadedRef.current = {};
    try {
      const scanned = await scanScrapLibraryEnrichQueue({ region: regionId });
      queueScanDoneRef.current = true;
      queueScanActiveRef.current = false;
      enrichLiveBootstrapped.add(regionId);
      applyQueuePayload({ ...scanned, cacheTab: 'pending' });
      const curTab = tabRef.current;
      if (curTab !== 'pending') {
        await loadQueueTab(curTab);
      }
      const n = Number(scanned.counts?.pending ?? 0);
      const done = Number(scanned.counts?.done || 0);
      const soft = Number(scanned.counts?.soft || 0);
      const fail = Number(scanned.counts?.fail || 0);
      setMsg(
        `已扫描本地 · 未处理 ${n.toLocaleString()} · 成功 ${done.toLocaleString()} · 软成功 ${soft.toLocaleString()} · 失败 ${fail.toLocaleString()}（此处的成功/软成功/失败是「本地扫描判定」，不是抓取产出；分类全量可翻页）`,
      );
      return true;
    } catch (e) {
      queueScanActiveRef.current = false;
      setMsg(e instanceof Error ? e.message : '队列扫描失败');
      throw e;
    } finally {
      setQueueScanning(false);
    }
  }


  return {
    applyQueuePayload,
    loadQueueTab,
    goQueuePage,
    clearCodeSearch,
    runCodeSearch,
    runQueueScan,
  };
}
