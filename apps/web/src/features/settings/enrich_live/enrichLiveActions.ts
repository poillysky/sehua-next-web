'use client';

import {
  pauseScrapLibraryEnrich,
  clearScrapLibraryEnrichLogs,
  retryScrapLibraryEnrichFails,
  retryScrapLibraryEnrichSofts,
  enrichScrapLibraryItem,
  listScrapLibraryEmbedItems,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichFieldRow,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import { startTransition } from 'react';
import { fieldsFromSourceText } from './cover';
import type { LiveTab } from './queueFormat';
import {
  enrichLiveBootstrapped,
  isPartialOk,
  pendingTotalStorageKey,
  rowKey,
  rowStatus,
  writeCachedPendingTotal,
} from './queueFormat';

export type EnrichLiveActionDeps = {
  regionId: string;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  st: ScrapLibraryEnrichJobStatus | null;
  setSt: Dispatch<SetStateAction<ScrapLibraryEnrichJobStatus | null>>;
  stopping: boolean;
  clearing: boolean;
  rescraping: boolean;
  retryingFails: boolean;
  retryingSofts: boolean;
  queueScanning: boolean;
  queueCounts: {
    pending: number;
    running: number;
    done: number;
    soft: number;
    fail: number;
  };
  setStopping: Dispatch<SetStateAction<boolean>>;
  setClearing: Dispatch<SetStateAction<boolean>>;
  setRescraping: Dispatch<SetStateAction<boolean>>;
  setRetryingFails: Dispatch<SetStateAction<boolean>>;
  setRetryingSofts: Dispatch<SetStateAction<boolean>>;
  setQueueScanning: Dispatch<SetStateAction<boolean>>;
  setMsg: Dispatch<SetStateAction<string>>;
  setLogsCleared: Dispatch<SetStateAction<boolean>>;
  setPersistedLogs: Dispatch<SetStateAction<string[]>>;
  setTab: Dispatch<SetStateAction<LiveTab>>;
  setTabTouched: Dispatch<SetStateAction<boolean>>;
  setQueuePage: Dispatch<SetStateAction<number>>;
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
  setSelectedKey: Dispatch<SetStateAction<string | null>>;
  setDbDetail: Dispatch<SetStateAction<ScrapLibraryEnrichCurrent | null>>;
  selectedRow: ScrapLibraryEnrichQueueItem | ScrapLibraryEnrichCurrent | null;
  queueScanDoneRef: MutableRefObject<boolean>;
  queueScanActiveRef: MutableRefObject<boolean>;
  failCeilRef: MutableRefObject<{ v: number; until: number } | null>;
  softCeilRef: MutableRefObject<{ v: number; until: number } | null>;
  tabCacheRef: MutableRefObject<Partial<Record<LiveTab, ScrapLibraryEnrichQueueItem[]>>>;
  tabDbLoadedRef: MutableRefObject<Partial<Record<LiveTab, boolean>>>;
  tabRef: MutableRefObject<LiveTab>;
  loadSeqRef: MutableRefObject<number>;
  pendingTotalRef: MutableRefObject<number>;
  CEIL_TTL_MS: number;
  applyQueuePayload: (data: any) => void;
  loadQueueTab: (status: LiveTab, page?: number) => Promise<void>;
  runQueueScan: () => Promise<boolean | void>;
};

/** Build pause/retry/clear/rescrape handlers (not a hook — call after selectedRow is derived). */
export function buildEnrichLiveActions(d: EnrichLiveActionDeps) {
  const {
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
  } = d;

  async function onPause() {
    if (stopping || !st?.running) return;
    setStopping(true);
    try {
      await pauseScrapLibraryEnrich();
      // 立刻清掉「处理中」中间态，等 SSE 再对齐角标
      setQueueCounts((prev) => ({
        ...prev,
        running: 0,
        pending: Math.max(
          Number(prev.pending || 0) + Number(prev.running || 0),
          pendingTotalRef.current || 0,
        ),
      }));
      tabCacheRef.current.running = [];
      delete tabCacheRef.current.pending;
      if (tabRef.current === 'running') {
        startTransition(() => setQueueItems([]));
      }
      onStatus('正在暂停刮削…', 'mute');
      setMsg('已暂停 · 进行中已退回未处理');
    } catch (e) {
      const text = e instanceof Error ? e.message : '暂停失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setStopping(false);
    }
  }

  async function onRetryFails() {
    if (retryingFails || retryingSofts || clearing) return;
    const failN = Number(queueCounts.fail || 0);
    if (failN <= 0) {
      setMsg('没有失败任务');
      return;
    }
    setRetryingFails(true);
    setMsg('');
    try {
      const data = await retryScrapLibraryEnrichFails({ region: regionId });
      const n = Number(data.reopened || 0);
      const counts = data.counts || {};
      const nextPending = Number(counts.pending || 0);
      const nextFail = Number(counts.fail || 0);
      const nextDone = Number(counts.done || 0);
      const nextSoft = Number(counts.soft || 0);
      failCeilRef.current = { v: nextFail, until: Date.now() + CEIL_TTL_MS };
      setQueueCounts({
        pending: nextPending,
        running: Number(counts.running || 0),
        done: nextDone,
        soft: nextSoft,
        fail: nextFail,
      });
      setListTotals((prev) => ({
        ...prev,
        pending: Math.max(nextPending, Number(prev.pending || 0)),
        fail: nextFail,
        done: nextDone || prev.done,
        soft: nextSoft || prev.soft,
      }));
      pendingTotalRef.current = Math.max(pendingTotalRef.current, nextPending);
      if (nextPending > 0) {
        writeCachedPendingTotal(regionId, nextPending);
      }
      // 失败列表已迁走，清缓存避免回看仍显示旧失败
      delete tabCacheRef.current.fail;
      delete tabCacheRef.current.pending;
      setTabTouched(true);
      setQueuePage(1);
      setTab('pending');
      await loadQueueTab('pending', 1);
      if (n <= 0) {
        setMsg('没有可重试的失败（可能已在未处理中）');
        onStatus('无失败可重试', 'mute');
      } else {
        const tip = data.injected
          ? `已重试 ${n.toLocaleString()} 条 · 插入当前任务优先处理`
          : `已重试 ${n.toLocaleString()} 条 · 已转入未处理（优先）`;
        setMsg(tip);
        onStatus(tip, 'ok');
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '重试失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRetryingFails(false);
    }
  }

  async function onRetrySofts() {
    if (retryingSofts || retryingFails || clearing) return;
    const softN = Number(queueCounts.soft || 0);
    if (softN <= 0) {
      setMsg('没有软成功任务');
      return;
    }
    setRetryingSofts(true);
    setMsg('');
    try {
      const data = await retryScrapLibraryEnrichSofts({ region: regionId });
      const n = Number(data.reopened || 0);
      const counts = data.counts || {};
      const nextPending = Number(counts.pending || 0);
      const nextFail = Number(counts.fail || 0);
      const nextDone = Number(counts.done || 0);
      const nextSoft = Number(counts.soft || 0);
      softCeilRef.current = { v: nextSoft, until: Date.now() + CEIL_TTL_MS };
      setQueueCounts({
        pending: nextPending,
        running: Number(counts.running || 0),
        done: nextDone,
        soft: nextSoft,
        fail: nextFail,
      });
      setListTotals((prev) => ({
        ...prev,
        pending: Math.max(nextPending, Number(prev.pending || 0)),
        soft: nextSoft,
        done: nextDone,
        fail: nextFail || prev.fail,
      }));
      pendingTotalRef.current = Math.max(pendingTotalRef.current, nextPending);
      if (nextPending > 0) {
        writeCachedPendingTotal(regionId, nextPending);
      }
      delete tabCacheRef.current.soft;
      delete tabCacheRef.current.pending;
      setTabTouched(true);
      setQueuePage(1);
      setTab('pending');
      await loadQueueTab('pending', 1);
      if (n <= 0) {
        setMsg('没有可重试的软成功（可能已在未处理中）');
        onStatus('无软成功可重试', 'mute');
      } else {
        const tip = data.injected
          ? `已重试 ${n.toLocaleString()} 条软成功 · 插入当前任务优先处理`
          : `已重试 ${n.toLocaleString()} 条软成功 · 已转入未处理（优先）`;
        setMsg(tip);
        onStatus(tip, 'ok');
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '软成功重试失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRetryingSofts(false);
    }
  }

  async function onClearAndScan() {
    if (clearing || queueScanning || retryingFails || retryingSofts) return;
    setClearing(true);
    queueScanActiveRef.current = true;
    setLogsCleared(true);
    setPersistedLogs([]);
    setQueueItems([]);
    setQueueCounts({ pending: 0, running: 0, done: 0, soft: 0, fail: 0 });
    setListTotals({});
    pendingTotalRef.current = 0;
    tabCacheRef.current = {};
    tabDbLoadedRef.current = {};
    loadSeqRef.current += 1;
    enrichLiveBootstrapped.delete(regionId);
    try {
      sessionStorage.removeItem(pendingTotalStorageKey(regionId));
    } catch {
      /* ignore */
    }
    setSt((prev) =>
      prev
        ? {
            ...prev,
            log: [],
            regionLogs: {
              ...(prev.regionLogs || {}),
              [regionId]: [],
            },
            regionLogCounts: {
              ...(prev.regionLogCounts || {}),
              [regionId]: 0,
            },
            queue: [],
            queueCounts: {
              pending: 0,
              running: 0,
              done: 0,
              soft: 0,
              fail: 0,
            },
            // 丢掉旧检查点，避免「已暂停 · 历史 fail=622」残留
            checkpoints: Object.fromEntries(
              Object.entries(prev.checkpoints || {}).filter(
                ([rid]) => rid !== regionId,
              ),
            ),
            progress: prev.running
              ? prev.progress
              : {
                  stage: 'idle',
                  label: '已清空',
                  done: 0,
                  total: 0,
                  ok: 0,
                  failed: 0,
                  percent: 0,
                },
            paused: false,
            halt: prev.running ? prev.halt : null,
          }
        : prev,
    );
    setMsg('');
    onStatus('清空扫描…', 'mute');
    try {
      // 刮削中禁止硬清：先暂停，避免与入队死锁/卡死「清空中…」
      if (st?.running) {
        try {
          await pauseScrapLibraryEnrich();
        } catch {
          /* 仍尝试清空；后端忙会返回明确错误 */
        }
      }
      await clearScrapLibraryEnrichLogs({ region: regionId });
      await runQueueScan();
      onStatus('已清空并重新扫描', 'ok');
    } catch (e) {
      const text = e instanceof Error ? e.message : '清空扫描失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setClearing(false);
    }
  }

  async function resolveItemIdForRow(
    row: ScrapLibraryEnrichQueueItem,
  ): Promise<string> {
    const iid = String(row.itemId || '').trim();
    if (iid) return iid;
    const code = String(row.code || '').trim();
    if (!code) return '';
    const page = await listScrapLibraryEmbedItems({ q: code, limit: 8 });
    const hit =
      (page.items || []).find(
        (it) =>
          String(it.code || '').toUpperCase() === code.toUpperCase(),
      ) || (page.items || [])[0];
    return String(hit?.itemId || '').trim();
  }

  async function onRescrapeSelected() {
    if (rescraping || !selectedRow) return;
    if (st?.running) {
      setMsg('分区刮削进行中，请先暂停再重刮');
      onStatus('请先暂停刮削', 'warn');
      return;
    }
    setRescraping(true);
    setMsg('');
    const code = String(selectedRow.code || '').trim().toUpperCase();
    try {
      const itemId = await resolveItemIdForRow(selectedRow);
      if (!itemId) throw new Error('找不到该番号的向量条目');
      onStatus(`重刮 ${code || itemId}…`, 'mute');
      const data = await enrichScrapLibraryItem({
        itemId,
        overwrite: true,
        // 与分区批量一致：只写本地；元库/向量交给「同步数据库」「数据库向量化」
        syncVector: false,
      });
      const result = data.result || {};
      const softOk =
        Boolean(result.partialOk) ||
        String(result.error || '').startsWith('软成功') ||
        String(result.error || '').startsWith('次成功');
      const ok = Boolean(
        data.ok &&
          result.ok !== false &&
          (!result.error || softOk),
      );
      const resultFields = Array.isArray(result.fields)
        ? (result.fields as ScrapLibraryEnrichFieldRow[])
        : [];
      const nextRow: ScrapLibraryEnrichQueueItem = {
        ...selectedRow,
        itemId,
        status: ok ? 'done' : 'fail',
        partialOk: ok ? Boolean(result.partialOk) : false,
        error: String(result.error || (ok ? '' : '重刮失败')),
        source: String(result.source || selectedRow.source || ''),
        fetchMs:
          typeof result.fetchMs === 'number'
            ? result.fetchMs
            : selectedRow.fetchMs,
        coverMs:
          typeof result.coverMs === 'number'
            ? result.coverMs
            : selectedRow.coverMs,
        actressMs:
          typeof result.actressMs === 'number'
            ? result.actressMs
            : selectedRow.actressMs,
        vectorMs:
          typeof result.vectorMs === 'number'
            ? result.vectorMs
            : selectedRow.vectorMs,
        totalMs:
          typeof result.totalMs === 'number'
            ? result.totalMs
            : selectedRow.totalMs,
        detailTitle:
          String(data.item?.title || selectedRow.detailTitle || ''),
        nfoChanged:
          typeof result.nfoChanged === 'boolean'
            ? result.nfoChanged
            : selectedRow.nfoChanged,
        posterDownloaded:
          typeof result.posterDownloaded === 'boolean'
            ? result.posterDownloaded
            : selectedRow.posterDownloaded,
        sourceTimings: Array.isArray(result.sourceTimings)
          ? result.sourceTimings
          : selectedRow.sourceTimings,
        fields: resultFields.length ? resultFields : selectedRow.fields,
        gapsAfter: Array.isArray(result.gapsAfter)
          ? result.gapsAfter
          : Array.isArray(
                (selectedRow as ScrapLibraryEnrichQueueItem).gapsAfter,
              )
            ? (selectedRow as ScrapLibraryEnrichQueueItem).gapsAfter
            : undefined,
        vectorSynced: Boolean(data.item) && !Boolean(result.vectorSkipped),
        vectorSkipped: Boolean(result.vectorSkipped),
      };
      const selKey = rowKey(selectedRow as ScrapLibraryEnrichQueueItem);
      const wasSt = rowStatus(selectedRow.status);
      const was: LiveTab =
        wasSt === 'done'
          ? isPartialOk(selectedRow)
            ? 'soft'
            : 'done'
          : wasSt;
      const now: LiveTab = ok
        ? isPartialOk(nextRow)
          ? 'soft'
          : 'done'
        : 'fail';
      setQueueCounts((prev) => {
        if (was === now) return prev;
        const next = { ...prev };
        if (was in next) next[was] = Math.max(0, Number(next[was] || 0) - 1);
        next[now] = Number(next[now] || 0) + 1;
        return next;
      });
      // 清掉相关 tab 缓存，避免旧失败/未处理残留
      delete tabCacheRef.current[was];
      delete tabCacheRef.current[now];
      if (ok) {
        // 立即从当前列表拿掉，切到成功/软成功队列
        if (tabRef.current !== now) {
          setQueueItems((prev) =>
            prev.filter((r) => rowKey(r) !== selKey),
          );
        } else {
          setQueueItems((prev) =>
            prev.map((r) => (rowKey(r) === selKey ? nextRow : r)),
          );
        }
        setTabTouched(true);
        setQueuePage(1);
        setTab(now);
        await loadQueueTab(now, 1);
        // 若库回填稍慢，确保成功列表里立刻能看到本条
        setQueueItems((prev) => {
          const key = selKey;
          const hit = prev.some(
            (r) =>
              rowKey(r) === key ||
              String(r.code || '').toUpperCase() === code,
          );
          if (hit) {
            return prev.map((r) =>
              rowKey(r) === key ||
              String(r.code || '').toUpperCase() === code
                ? { ...r, ...nextRow, status: 'done' }
                : r,
            );
          }
          return [{ ...nextRow, status: 'done' }, ...prev];
        });
        tabCacheRef.current.done = undefined;
      } else {
        setQueueItems((prev) =>
          prev.map((r) => (rowKey(r) === selKey ? nextRow : r)),
        );
        if (tabRef.current !== 'fail') {
          setTabTouched(true);
          setQueuePage(1);
          setTab('fail');
          await loadQueueTab('fail', 1);
        }
      }
      if (data.item || resultFields.length) {
        setDbDetail({
          code: data.item?.code || code,
          itemId,
          detailTitle: data.item?.title || nextRow.detailTitle || '',
          status: nextRow.status,
          fields: resultFields.length
            ? resultFields
            : fieldsFromSourceText(String(data.item?.sourceText || '')),
          vectorSynced: nextRow.vectorSynced,
          vectorSkipped: nextRow.vectorSkipped,
          posterDownloaded:
            typeof nextRow.posterDownloaded === 'boolean'
              ? nextRow.posterDownloaded
              : Boolean(data.item?.posterApi || data.item?.thumbApi),
          source: nextRow.source,
          fetchMs: nextRow.fetchMs,
          coverMs: nextRow.coverMs,
          actressMs: nextRow.actressMs,
          vectorMs: nextRow.vectorMs,
          totalMs: nextRow.totalMs,
          sourceTimings: nextRow.sourceTimings,
          nfoChanged: nextRow.nfoChanged,
        });
      }
      const text = ok
        ? `${code || itemId} · 重刮完成 · 已转入成功`
        : `${code || itemId} · 重刮失败${result.error ? ` · ${result.error}` : ''}`;
      setMsg(text);
      onStatus(ok ? '重刮完成 · 已转入成功' : '重刮失败', ok ? 'ok' : 'warn');
    } catch (e) {
      const text = e instanceof Error ? e.message : '重刮失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setRescraping(false);
    }
  }


  return {
    onPause,
    onRetryFails,
    onRetrySofts,
    onClearAndScan,
    onRescrapeSelected,
  };
}
