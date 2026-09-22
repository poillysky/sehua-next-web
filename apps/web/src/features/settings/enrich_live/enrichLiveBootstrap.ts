'use client';

import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import {
  getScrapLibraryEnrichQueueLog,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import {
  enrichLiveBootstrapped,
  pendingTotalStorageKey,
  QUEUE_PAGE_SIZE,
  readCachedPendingTotal,
  type LiveTab,
} from './queueFormat';

export type EnrichLiveRegionBootDeps = {
  regionId: string;
  applyQueuePayload: (data: any) => void;
  pendingTotalRef: MutableRefObject<number>;
  queueScanDoneRef: MutableRefObject<boolean>;
  tabRef: MutableRefObject<LiveTab>;
  setQueueScanning: Dispatch<SetStateAction<boolean>>;
  setMsg: Dispatch<SetStateAction<string>>;
  /** 引导结束（成功或失败）后置 true，供 tab/翻页 effect 再拉一次当前页 */
  setQueueReady: Dispatch<SetStateAction<boolean>>;
};

/** 进页：有队列只读表；空队列不自动全量扫描。Call inside useEffect; returns cleanup. */
export function attachEnrichLiveRegionBoot(d: EnrichLiveRegionBootDeps) {
  const {
    regionId,
    applyQueuePayload,
    pendingTotalRef,
    queueScanDoneRef,
    tabRef,
    setQueueScanning,
    setMsg,
    setQueueReady,
  } = d;
  let cancelled = false;
  void (async () => {
    const cachedPending = readCachedPendingTotal(regionId);
    if (cachedPending > 0) pendingTotalRef.current = cachedPending;

    try {
      // 固定引导时的 tab：await 期间用户可能已切走，绝不能拿「当前 tab」去过滤这次回包
      const bootTab = tabRef.current;
      const existing = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        status: bootTab,
        limit: QUEUE_PAGE_SIZE,
        offset: 0,
      });
      if (cancelled) return;
      const c = existing.counts || {
        pending: 0,
        running: 0,
        done: 0,
        soft: 0,
        fail: 0,
      };
      const hasRows =
        Number(c.pending || 0) +
          Number(c.running || 0) +
          Number(c.done || 0) +
          Number(c.soft || 0) +
          Number(c.fail || 0) >
        0;

      if (hasRows || enrichLiveBootstrapped.has(regionId)) {
        enrichLiveBootstrapped.add(regionId);
        queueScanDoneRef.current = true;
        const serverPending = Number(c.pending || 0);
        // 引导只信服队列表；丢掉 sessionStorage 虚高缓存
        if (cachedPending > 0 && cachedPending !== serverPending) {
          try {
            sessionStorage.removeItem(pendingTotalStorageKey(regionId));
          } catch {
            /* ignore */
          }
        }
        pendingTotalRef.current = serverPending;
        applyQueuePayload({
          ...existing,
          cacheTab: bootTab,
          page: 1,
          pendingTotal: serverPending,
        });
        setQueueScanning(false);
        setQueueReady(true);
        return;
      }

      // 空队列：不自动全量扫描（会卡在「扫描未处理…」）
      enrichLiveBootstrapped.add(regionId);
      queueScanDoneRef.current = true;
      if (cachedPending > 0) {
        try {
          sessionStorage.removeItem(pendingTotalStorageKey(regionId));
        } catch {
          /* ignore */
        }
        pendingTotalRef.current = 0;
      }
      applyQueuePayload({
        ...existing,
        cacheTab: bootTab,
        items: [] as ScrapLibraryEnrichQueueItem[],
        pendingTotal: 0,
      });
      setQueueScanning(false);
      setQueueReady(true);
      setMsg(
        '打开分区开关即可边扫边刮；或点「清空·扫描」按向量骨架生成未处理队列',
      );
    } catch (e) {
      if (cancelled) return;
      setQueueScanning(false);
      queueScanDoneRef.current = true;
      setQueueReady(true);
      setMsg(e instanceof Error ? e.message : '队列加载失败');
    }
  })();
  return () => {
    cancelled = true;
  };
}
