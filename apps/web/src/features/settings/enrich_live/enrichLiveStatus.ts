'use client';

import { startTransition } from 'react';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import {
  subscribeScrapLibraryEnrichStatus,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import {
  isPartialOk,
  LOG_CAP,
  mergeLogLines,
  normalizeSoftSuccessRow,
  pendingTotalStorageKey,
  QUEUE_PAGE_SIZE,
  readCachedPendingTotal,
  rowKey,
  rowStatus,
  type LiveTab,
  writeCachedPendingTotal,
} from './queueFormat';

export type EnrichLiveStatusDeps = {
  regionId: string;
  logsCleared: boolean;
  setSt: Dispatch<SetStateAction<ScrapLibraryEnrichJobStatus | null>>;
  setHydrated: Dispatch<SetStateAction<boolean>>;
  setPersistedLogs: Dispatch<SetStateAction<string[]>>;
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
  setMsg: Dispatch<SetStateAction<string>>;
  sessionLiveRef: MutableRefObject<boolean>;
  queueScanActiveRef: MutableRefObject<boolean>;
  queueHydratingRef: MutableRefObject<boolean>;
  searchActiveRef: MutableRefObject<boolean>;
  failCeilRef: MutableRefObject<{ v: number; until: number } | null>;
  softCeilRef: MutableRefObject<{ v: number; until: number } | null>;
  resultTabReloadTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  resultTabCountRef: MutableRefObject<{ soft: number; done: number; fail: number }>;
  queueCountsRef: MutableRefObject<{
    pending: number;
    running: number;
    done: number;
    soft: number;
    fail: number;
  }>;
  pendingTotalRef: MutableRefObject<number>;
  tabCacheRef: MutableRefObject<Partial<Record<LiveTab, ScrapLibraryEnrichQueueItem[]>>>;
  tabDbLoadedRef: MutableRefObject<Partial<Record<LiveTab, boolean>>>;
  tabRef: MutableRefObject<LiveTab>;
  queuePageRef: MutableRefObject<number>;
  loadQueueTab: (status: LiveTab, page?: number) => Promise<void>;
};

/** SSE status apply + subscribe. Call `attach` inside useEffect; it returns cleanup. */
export function buildEnrichLiveStatusHandlers(d: EnrichLiveStatusDeps) {
  const {
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
  } = d;

  function attach() {
    let alive = true;
    const ac = new AbortController();
    let lastUiAt = 0;
    let pendingData: ScrapLibraryEnrichJobStatus | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const LIVE_UI_GAP_MS = 750;
    let lastLogTail = '';

    function applyStatusCore(data: ScrapLibraryEnrichJobStatus) {
      if (!alive) return;
      setSt(data);
      setHydrated(true);
      const qs = data.queueScan;
      const qsHere =
        Boolean(qs?.active) &&
        (!qs?.region || qs.region === regionId);
      queueScanActiveRef.current = qsHere;
      if (qsHere) {
        failCeilRef.current = null;
        softCeilRef.current = null;
        // 扫描进度只更新进度条/样例；角标仍跟队列表 COUNT（下方 qc 路径）。
        // 边扫边看：仅在尚未从库表拉过该 tab 时用样例占位。
        // 点过成功/失败等 tab 后必须以库表为准，否则扫序样例（常为 AARM*）会几秒盖掉真列表。
        const want = tabRef.current;
        if (
          (want === 'done' || want === 'soft' || want === 'fail') &&
          !tabDbLoadedRef.current[want] &&
          !queueHydratingRef.current &&
          !searchActiveRef.current
        ) {
          const rawSamples =
            want === 'done'
              ? qs?.samplesDone
              : want === 'soft'
                ? qs?.samplesSoft
                : qs?.samplesFail;
          if (Array.isArray(rawSamples) && rawSamples.length > 0) {
            const items = rawSamples.map((r) => normalizeSoftSuccessRow(r));
            tabCacheRef.current[want] = items;
            if (tabRef.current === want) {
              // 扫描预览勿 startTransition：会被密集 status 流打断，列表会一直空
              setQueueItems(items);
            }
          }
        }
      }
      const live = data.regionLogs?.[regionId] || [];
      const liveHere =
        Boolean(data.running) &&
        (!data.currentRegion || data.currentRegion === regionId);
      if (liveHere) {
        if (!sessionLiveRef.current) {
          // 本轮开始：只用内存日志，丢掉历史 200
          sessionLiveRef.current = true;
          const boot = Array.isArray(live) ? live.slice(-LOG_CAP) : [];
          lastLogTail = boot.length ? boot[boot.length - 1]! : '';
          setPersistedLogs(boot);
        } else if (!logsCleared && Array.isArray(live) && live.length) {
          const tip = live[live.length - 1] || '';
          if (tip !== lastLogTail) {
            lastLogTail = tip;
            setPersistedLogs((prev) => mergeLogLines(prev, live));
          }
        }
      } else {
        sessionLiveRef.current = false;
        if (!logsCleared) {
          if (Array.isArray(live) && live.length) {
            const tip = live[live.length - 1] || '';
            if (tip !== lastLogTail) {
              lastLogTail = tip;
              setPersistedLogs((prev) => mergeLogLines(prev, live));
            }
          }
        } else if (!data.running) {
          if (!live.length) {
            lastLogTail = '';
            setPersistedLogs([]);
          }
        }
      }

      // 运行中对齐本区计数；暂停/结束后「处理中」必须为 0（退回未处理）
      // 全局 queueCounts 只属于 currentRegion / queueCountsRegion，禁止 FC2 吃有码数字
      const byRegion = data.regionQueueCounts;
      const qcRegion = String(
        data.queueCountsRegion || data.currentRegion || '',
      ).trim();
      const regionQc =
        byRegion && typeof byRegion === 'object'
          ? byRegion[regionId] ||
            byRegion[
              Object.keys(byRegion).find(
                (k) => k === regionId || k.toLowerCase() === regionId.toLowerCase(),
              ) || ''
            ]
          : null;
      const qc =
        regionQc ||
        (qcRegion && qcRegion === regionId ? data.queueCounts : null);
      const halted =
        data.halt === 'pause' ||
        data.halt === 'stop' ||
        data.phase === 'paused' ||
        data.phase === 'stopping' ||
        data.phase === 'stopped' ||
        !data.running;
      // 用本区 library.total 纠正串区缓存（曾把有码 12 万写进 FC2 sessionStorage）
      const libRow =
        data.library && typeof data.library === 'object'
          ? data.library[regionId] ||
            data.library[
              Object.keys(data.library).find(
                (k) => k === regionId || k.toLowerCase() === regionId.toLowerCase(),
              ) || ''
            ]
          : null;
      const libTotal = Number(
        (libRow as { vectorTotal?: number; total?: number } | null)
          ?.vectorTotal ??
          (libRow as { total?: number } | null)?.total ??
          0,
      );
      if (libTotal > 0) {
        const cached = readCachedPendingTotal(regionId);
        if (cached > libTotal) {
          pendingTotalRef.current = 0;
          try {
            sessionStorage.removeItem(pendingTotalStorageKey(regionId));
          } catch {
            /* ignore */
          }
        }
      }
      if (
        qc &&
        (liveHere ||
          qsHere ||
          (halted && (regionQc || qcRegion === regionId)))
      ) {
        const runN = halted || qsHere ? 0 : Number(qc.running || 0);
        const statusPending =
          Number(qc.pending || 0) +
          (halted || qsHere ? Number(qc.running || 0) : 0);
        // 以服务端队列表为准；勿 Math.max 旧缓存
        const pendingN =
          libTotal > 0 ? Math.min(statusPending, libTotal) : statusPending;
        if (halted || qsHere) {
          pendingTotalRef.current = pendingN;
          writeCachedPendingTotal(regionId, pendingN);
        }
        // queueCountsOk=false：读库失败，保留上一帧；否则一律信服服务端。
        const countsOk = data.queueCountsOk !== false;
        const prevCounts = queueCountsRef.current;
        const preferBadge = (server: number, prev: number) =>
          !countsOk && prev > server ? prev : server;
        let failN = preferBadge(
          Number(qc.fail || 0),
          Number(prevCounts.fail || 0),
        );
        let softN = preferBadge(
          Number(qc.soft || 0),
          Number(prevCounts.soft || 0),
        );
        let doneN = preferBadge(
          Number(qc.done || 0),
          Number(prevCounts.done || 0),
        );
        // 上限只压住「重试瞬间服务端还在报旧值」这几十毫秒，过期即失效
        const ceilNow = Date.now();
        if (failCeilRef.current) {
          if (failCeilRef.current.until <= ceilNow) failCeilRef.current = null;
          else if (failN <= failCeilRef.current.v) failCeilRef.current = null;
          else failN = failCeilRef.current.v;
        }
        if (softCeilRef.current) {
          if (softCeilRef.current.until <= ceilNow) softCeilRef.current = null;
          else if (softN <= softCeilRef.current.v) softCeilRef.current = null;
          else softN = softCeilRef.current.v;
        }
        setQueueCounts({
          pending: pendingN,
          running: runN,
          done: doneN,
          soft: softN,
          fail: failN,
        });
      }
      if (halted) {
        tabCacheRef.current.running = [];
        if (tabRef.current === 'running') {
          startTransition(() => setQueueItems([]));
        }
        delete tabCacheRef.current.pending;
      } else if (liveHere && tabRef.current === 'running') {
        const liveRunning = (data.queue || []).filter(
          (r) => rowStatus(r.status) === 'running',
        );
        tabCacheRef.current.running = liveRunning;
        // 有 monitor.inflight 时列表走监控行，勿每帧 setQueueItems 打断滚动
        const monN = Array.isArray(data.monitor?.inflight)
          ? data.monitor.inflight.length
          : 0;
        if (monN <= 0) {
          startTransition(() => setQueueItems(liveRunning));
        }
      } else if (
        liveHere &&
        !searchActiveRef.current &&
        !queueHydratingRef.current &&
        queuePageRef.current === 1 &&
        (tabRef.current === 'done' ||
          tabRef.current === 'soft' ||
          tabRef.current === 'fail')
      ) {
        // 成功类 tab：只跟库表 updated_at（最新在上）。
        // 勿用 data.queue 抽样插顶——工作队列里残留的旧 AARM 会被当成「新项」顶上来。
        const want = tabRef.current;
        const curRaw = data.current;
        let shouldReload = false;
        if (curRaw && typeof curRaw === 'object') {
          const cur = normalizeSoftSuccessRow(
            curRaw as ScrapLibraryEnrichQueueItem,
          );
          const st = rowStatus(cur.status);
          const match =
            (want === 'fail' && st === 'fail') ||
            (want === 'soft' && st === 'done' && isPartialOk(cur)) ||
            (want === 'done' && st === 'done' && !isPartialOk(cur));
          if (match && (cur.code || cur.itemId)) {
            shouldReload = true;
            setQueueItems((prev) => {
              const base = prev.map(normalizeSoftSuccessRow);
              const key = rowKey(cur);
              const code = String(cur.code || '')
                .trim()
                .toUpperCase();
              const without = base.filter((r) => {
                if (rowKey(r) === key) return false;
                if (
                  code &&
                  String(r.code || '')
                    .trim()
                    .toUpperCase() === code
                ) {
                  return false;
                }
                return true;
              });
              const next = [cur, ...without].slice(0, QUEUE_PAGE_SIZE);
              tabCacheRef.current[want] = next;
              return next;
            });
          }
        }
        // 角标上涨也回读（current 有时已被下一号清掉）
        const badgeDone = Number(qc?.done || 0);
        const badgeFail = Number(qc?.fail || 0);
        const badgeSoft = Number(
          (qc as { soft?: number } | null)?.soft ||
            resultTabCountRef.current.soft,
        );
        const prevBadge = resultTabCountRef.current;
        if (want === 'soft' && badgeSoft > prevBadge.soft) shouldReload = true;
        if (want === 'done' && badgeDone > prevBadge.done) shouldReload = true;
        if (want === 'fail' && badgeFail > prevBadge.fail) shouldReload = true;
        resultTabCountRef.current = {
          soft: Math.max(prevBadge.soft, badgeSoft),
          done: Math.max(prevBadge.done, badgeDone),
          fail: Math.max(prevBadge.fail, badgeFail),
        };
        if (shouldReload) {
          delete tabCacheRef.current[want];
          if (resultTabReloadTimerRef.current) {
            clearTimeout(resultTabReloadTimerRef.current);
          }
          const reloadWant = want;
          resultTabReloadTimerRef.current = setTimeout(() => {
            resultTabReloadTimerRef.current = null;
            if (
              tabRef.current !== reloadWant ||
              queuePageRef.current !== 1 ||
              searchActiveRef.current
            ) {
              return;
            }
            void loadQueueTab(reloadWant, 1);
          }, 900);
        }
      }
    }

    function applyStatus(data: ScrapLibraryEnrichJobStatus) {
      if (!alive) return;
      // 暂停/结束立刻刷；运行中合并到 750ms，避免 monitor 时钟把主线程打满
      const terminal =
        !data.running ||
        data.halt === 'pause' ||
        data.halt === 'stop' ||
        data.phase === 'paused' ||
        data.phase === 'stopping' ||
        data.phase === 'stopped';
      if (terminal) {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        pendingData = null;
        lastUiAt = Date.now();
        applyStatusCore(data);
        return;
      }
      const now = Date.now();
      pendingData = data;
      if (now - lastUiAt >= LIVE_UI_GAP_MS) {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        lastUiAt = now;
        pendingData = null;
        applyStatusCore(data);
        return;
      }
      if (!flushTimer) {
        flushTimer = setTimeout(() => {
          flushTimer = null;
          if (!alive || !pendingData) return;
          lastUiAt = Date.now();
          const next = pendingData;
          pendingData = null;
          applyStatusCore(next);
        }, Math.max(80, LIVE_UI_GAP_MS - (now - lastUiAt)));
      }
    }

    void (async () => {
      try {
        await subscribeScrapLibraryEnrichStatus(applyStatus, {
          signal: ac.signal,
          onError: (message) => {
            if (!alive) return;
            setHydrated(true);
            setMsg(message);
          },
        });
      } catch (e) {
        if (!alive) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (e instanceof Error && e.name === 'AbortError') return;
        setHydrated(true);
        setMsg(e instanceof Error ? e.message : '状态推送失败');
      }
    })();

    return () => {
      alive = false;
      ac.abort();
      if (flushTimer) clearTimeout(flushTimer);
    };
  }

  return { attach };
}
