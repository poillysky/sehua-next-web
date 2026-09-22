'use client';

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import {
  getScrapLibraryEnrichStatus,
  pauseScrapLibraryEnrich,
  getScrapEnrichStrategy,
  putScrapEnrichStrategy,
  startScrapLibraryEnrich,
  type PrefixCatalogLocalIndexProgress,
  type ScrapLibraryEnrichCheckpoint,
  type ScrapLibraryEnrichJobStatus,
} from '@/lib/api';
import { MAKER_KIND_TABS } from '@/features/makers/makersUi';
import { type EnrichRegionRow, type StatusReporter } from './types';
import {
  applyExclusiveRegion,
  exclusiveRegionsEnabled,
  normalizeEnrichFillMode,
} from './helpers';

export function useMakersEnrichOverview({
  onStatus,
  setMsg,
  catalogBusy,
  strmBusy,
  localIndexBusy,
  scrapBusy,
  setActressAvatarMode,
}: {
  onStatus: StatusReporter;
  setMsg: (text: string) => void;
  catalogBusy: boolean;
  strmBusy: boolean;
  localIndexBusy: boolean;
  scrapBusy: boolean;
  setActressAvatarMode: Dispatch<
    SetStateAction<'incremental' | 'overwrite'>
  >;
}) {
  const [enrichBusy, setEnrichBusy] = useState(false);
  const [enrichPhase, setEnrichPhase] = useState('');
  const [enrichProgress, setEnrichProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [enrichProgressByRegion, setEnrichProgressByRegion] = useState<
    Record<string, PrefixCatalogLocalIndexProgress | null>
  >({});
  const [enrichLog, setEnrichLog] = useState<string[]>([]);
  const [enrichRegionLogs, setEnrichRegionLogs] = useState<
    Record<string, string[]>
  >({});
  const [enrichCurrentRegion, setEnrichCurrentRegion] = useState('');
  const [enrichCheckpoints, setEnrichCheckpoints] = useState<
    Record<string, ScrapLibraryEnrichCheckpoint>
  >({});
  const [enrichQueueCounts, setEnrichQueueCounts] = useState<{
    pending: number;
    running: number;
    done: number;
    soft: number;
    fail: number;
  } | null>(null);
  const [enrichRegionQueueCounts, setEnrichRegionQueueCounts] = useState<
    Record<
      string,
      {
        pending: number;
        running: number;
        done: number;
        soft: number;
        fail: number;
      }
    >
  >({});
  const [enrichLibrary, setEnrichLibrary] = useState<
    Record<
      string,
      {
        total?: number;
        incomplete?: number;
        complete?: number;
        percent?: number;
      }
    >
  >({});
  const [enrichMode, setEnrichMode] = useState<
    'incremental' | 'refresh_weak' | 'overwrite'
  >('incremental');
  const [enrichRegions, setEnrichRegions] = useState<EnrichRegionRow[]>([]);
  const [enrichRegionBusy, setEnrichRegionBusy] = useState(false);
  const enrichPollRef = useRef<AbortController | null>(null);
  const enrichPollingRef = useRef(false);
  /** 用户点了停止：禁止轮询把开关又拨开 */
  const enrichStopRequestedRef = useRef(false);
  /** 本轮补齐速度：平滑显示，避免部/分与阶段文案来回闪 */
  const enrichSpeedRef = useRef<{
    regionId: string;
    t0: number;
    fin0: number;
    /** 已进入补齐后不再退回「筛选/排队」 */
    lockedEnrich: boolean;
    /** 平滑后的部/分 */
    rateEma: number | null;
    /** 上次展示的速率文案 */
    rateText: string;
    /** 近窗采样：算滑动部/分 */
    samples?: { t: number; fin: number }[];
  } | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const st = await getScrapLibraryEnrichStatus({ lite: true });
        setEnrichCheckpoints(
          st.checkpoints && typeof st.checkpoints === 'object'
            ? st.checkpoints
            : {},
        );
        if (st.queueCounts) {
          setEnrichQueueCounts({
            pending: Number(st.queueCounts.pending || 0),
            running: Number(st.queueCounts.running || 0),
            done: Number(st.queueCounts.done || 0),
            soft: Number(st.queueCounts.soft || 0),
            fail: Number(st.queueCounts.fail || 0),
          });
        }
        if (st.regionQueueCounts && typeof st.regionQueueCounts === 'object') {
          const next: Record<
            string,
            {
              pending: number;
              running: number;
              done: number;
              soft: number;
              fail: number;
            }
          > = {};
          for (const [rid, qc] of Object.entries(st.regionQueueCounts)) {
            if (!qc) continue;
            next[rid] = {
              pending: Number(qc.pending || 0),
              running: Number(qc.running || 0),
              done: Number(qc.done || 0),
              soft: Number(qc.soft || 0),
              fail: Number(qc.fail || 0),
            };
          }
          setEnrichRegionQueueCounts(next);
        }
        if (st.library && typeof st.library === 'object') {
          setEnrichLibrary(st.library);
        }
        if (!st.running && st.checkpoints) {
          const byRegion: Record<
            string,
            PrefixCatalogLocalIndexProgress | null
          > = {};
          for (const [rid, cp] of Object.entries(st.checkpoints)) {
            if (!cp) continue;
            const lib = st.library?.[rid];
            const done = Number(
              lib?.complete ?? cp.ok ?? cp.done ?? 0,
            );
            const failed = Number(cp.failed ?? 0);
            const total = Number(
              lib?.total ??
                cp.total ??
                done + failed + Number(cp.remaining ?? 0),
            );
            byRegion[rid] = {
              stage: 'done',
              label: '已暂停',
              done,
              total,
              ok: Number(cp.ok ?? 0),
              failed,
              percent:
                typeof lib?.percent === 'number'
                  ? Math.round(lib.percent)
                  : total > 0
                    ? Math.round((100 * done) / total)
                    : 0,
            };
          }
          if (Object.keys(byRegion).length) {
            setEnrichProgressByRegion(byRegion);
          }
        }
        const runningRegion = String(st.currentRegion || '').trim();
        if (st.running) {
          setEnrichBusy(true);
          setEnrichPhase(st.phase || '补齐中…');
          setEnrichProgress(st.progress || null);
          setEnrichCurrentRegion(runningRegion);
          setEnrichLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          setEnrichRegionLogs(
            st.regionLogs && typeof st.regionLogs === 'object'
              ? st.regionLogs
              : {},
          );
          if (runningRegion && st.progress) {
            setEnrichProgressByRegion((prev) => ({
              ...prev,
              [runningRegion]: st.progress || null,
            }));
          }
          void pollEnrichUntilDone();
        }
        try {
          const strat = await getScrapEnrichStrategy();
          setEnrichMode(normalizeEnrichFillMode(strat.fillMode));
          setActressAvatarMode(
            strat.actressAvatarMode === 'overwrite'
              ? 'overwrite'
              : 'incremental',
          );
          const rows =
            strat.regions ||
            MAKER_KIND_TABS.map((t) => ({ id: t.id, label: t.label, enabled: true }));
          // 开关 =「正在刮 / 即将开刮」，不是策略偏好。
          // 空闲时绝不能因 regionsEnabled 残留而显示为开（否则「开着却没在刮」）。
          setEnrichRegions(
            rows.map((r) => ({
              id: r.id,
              label: r.label,
              enabled: Boolean(st.running && runningRegion === r.id),
            })),
          );
          // 任务已停时把策略里互斥开关清干净，避免下次挂载再读到脏 true
          if (!st.running) {
            const enabledMap = strat.regionsEnabled || {};
            const dirty = Object.values(enabledMap).some(Boolean);
            if (dirty) {
              try {
                await putScrapEnrichStrategy({
                  ...strat,
                  regionsEnabled: exclusiveRegionsEnabled(enabledMap, null),
                });
              } catch {
                /* ignore */
              }
            }
          }
        } catch {
          setEnrichRegions(
            MAKER_KIND_TABS.map((t) => ({
              id: t.id,
              label: t.label,
              enabled: Boolean(st.running && runningRegion === t.id),
            })),
          );
        }
      } catch {
        try {
          const strat = await getScrapEnrichStrategy();
          setEnrichMode(normalizeEnrichFillMode(strat.fillMode));
          setActressAvatarMode(
            strat.actressAvatarMode === 'overwrite'
              ? 'overwrite'
              : 'incremental',
          );
          setEnrichRegions(
            (strat.regions || MAKER_KIND_TABS.map((t) => ({ id: t.id, label: t.label }))).map(
              (r) => ({
                id: r.id,
                label: r.label,
                enabled: false,
              }),
            ),
          );
        } catch {
          setEnrichRegions(
            MAKER_KIND_TABS.map((t) => ({
              id: t.id,
              label: t.label,
              enabled: false,
            })),
          );
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount resume only
  }, []);

  useEffect(() => {
    return () => {
      enrichPollRef.current?.abort();
    };
  }, []);

  async function pollEnrichUntilDone(opts?: { notify?: boolean }) {
    if (enrichPollingRef.current) return;
    enrichPollingRef.current = true;
    let seenRunning = Boolean(opts?.notify);
    const ac = new AbortController();
    enrichPollRef.current?.abort();
    enrichPollRef.current = ac;

    const applyTerminal = (st: ScrapLibraryEnrichJobStatus) => {
      if (st.halt === 'pause' || st.phase === 'paused') {
        setEnrichBusy(false);
        setEnrichPhase('paused');
        setEnrichRegions((prev) =>
          prev.map((r) => ({ ...r, enabled: false })),
        );
        const pausedRid =
          String(st.currentRegion || '').trim() ||
          Object.keys(st.checkpoints || {})[0] ||
          '';
        if (pausedRid && st.checkpoints?.[pausedRid]) {
          const cp = st.checkpoints[pausedRid];
          setEnrichProgressByRegion((prev) => ({
            ...prev,
            [pausedRid]: {
              stage: 'done',
              label: '已暂停',
              done: cp.done ?? 0,
              total: cp.total ?? 0,
              ok: cp.ok ?? 0,
              failed: cp.failed ?? 0,
              percent:
                cp.total && cp.total > 0
                  ? Math.round((100 * (cp.done ?? 0)) / cp.total)
                  : 0,
            },
          }));
        }
        enrichStopRequestedRef.current = false;
        return true;
      }
      if (!st.running) {
        if (seenRunning) {
          if (st.error) {
            setMsg(st.error);
            onStatus('刮削补齐失败', 'warn');
          } else if (st.result) {
            const ok = st.result.ok ?? 0;
            const failed = st.result.failed ?? 0;
            // ⚠️ 分母必须用 processed（本轮实际处理数）。queued 在增量模式下是
            // 「库内待处理预估」（可到十万级），会把提示写成「成功 30/123000」。
            const processed = st.result.processed ?? st.result.queued ?? 0;
            if (st.result.paused) {
              setMsg(
                `已暂停 · 成功 ${ok}/${processed}${failed ? ` · 失败 ${failed}` : ''} · 再开继续`,
              );
              onStatus('已暂停刮削（队列已保留）', 'ok');
              setEnrichRegions((prev) =>
                prev.map((r) => ({ ...r, enabled: false })),
              );
              const pausedRid =
                String(st.currentRegion || '').trim() ||
                Object.keys(st.checkpoints || {})[0] ||
                '';
              if (pausedRid && st.checkpoints?.[pausedRid]) {
                const cp = st.checkpoints[pausedRid];
                setEnrichProgressByRegion((prev) => ({
                  ...prev,
                  [pausedRid]: {
                    stage: 'done',
                    label: '已暂停',
                    done: cp.done ?? 0,
                    total: cp.total ?? 0,
                    ok: cp.ok ?? 0,
                    failed: cp.failed ?? 0,
                    percent:
                      cp.total && cp.total > 0
                        ? Math.round((100 * (cp.done ?? 0)) / cp.total)
                        : 0,
                  },
                }));
              }
            } else if (st.result.cancelled) {
              setMsg(
                `已停止 · 成功 ${ok}/${processed}${failed ? ` · 失败 ${failed}` : ''} · 队列已清除 · 历史日志保留`,
              );
              onStatus('已停止刮削（历史日志保留）', 'ok');
              setEnrichProgress(null);
              setEnrichProgressByRegion({});
              setEnrichCheckpoints({});
              setEnrichRegionLogs({});
              setEnrichLog([]);
              setEnrichQueueCounts(null);
              setEnrichRegionQueueCounts({});
              setEnrichRegions((prev) =>
                prev.map((r) => ({ ...r, enabled: false })),
              );
            } else {
              const prefix = st.result.dryRun ? '预览' : '补齐';
              setMsg(
                `${prefix}完成 · 成功 ${ok}/${processed}${failed ? ` · 失败 ${failed}` : ''}`,
              );
              onStatus(
                st.result.dryRun ? '刮削补齐预览完成' : '刮削补齐完成',
                'ok',
              );
              setEnrichProgress(null);
              setEnrichRegions((prev) =>
                prev.map((r) => ({ ...r, enabled: false })),
              );
            }
          }
        }
        setEnrichBusy(false);
        setEnrichPhase('');
        enrichStopRequestedRef.current = false;
        return true;
      }
      return false;
    };

    const OVERVIEW_POLL_MS = 1800;

    const flushOverviewUi = (st: ScrapLibraryEnrichJobStatus) => {
      if (st.running) seenRunning = true;
      setEnrichBusy(st.running);
      setEnrichPhase(st.phase || (st.running ? '补齐中…' : ''));
      setEnrichProgress(st.progress || null);
      // 总览用轻量 GET，不挂 SSE；详情页自有直播流
      setEnrichCurrentRegion(String(st.currentRegion || ''));
      if (!st.running) {
        setEnrichCheckpoints(
          st.checkpoints && typeof st.checkpoints === 'object'
            ? st.checkpoints
            : {},
        );
        if (Array.isArray(st.log) && st.log.length) {
          setEnrichLog(st.log.slice(-40));
        }
        if (st.regionLogs && typeof st.regionLogs === 'object') {
          setEnrichRegionLogs(st.regionLogs);
        }
      }
      setEnrichQueueCounts((prev) => {
        if (st.queueCounts) {
          return {
            pending: Number(st.queueCounts.pending || 0),
            running: Number(st.queueCounts.running || 0),
            done: Number(st.queueCounts.done || 0),
            soft: Number(st.queueCounts.soft || 0),
            fail: Number(st.queueCounts.fail || 0),
          };
        }
        if (st.running && prev) return prev;
        if (st.paused || st.phase === 'paused' || st.halt === 'pause') {
          return prev;
        }
        return null;
      });
      if (st.regionQueueCounts && typeof st.regionQueueCounts === 'object') {
        const next: Record<
          string,
          {
            pending: number;
            running: number;
            done: number;
            soft: number;
            fail: number;
          }
        > = {};
        for (const [rid, qc] of Object.entries(st.regionQueueCounts)) {
          if (!qc) continue;
          next[rid] = {
            pending: Number(qc.pending || 0),
            running: Number(qc.running || 0),
            done: Number(qc.done || 0),
            soft: Number(qc.soft || 0),
            fail: Number(qc.fail || 0),
          };
        }
        setEnrichRegionQueueCounts(next);
      }
      if (st.library && typeof st.library === 'object') {
        setEnrichLibrary(st.library);
      }
      if (st.running) {
        const speedRid = String(st.currentRegion || '').trim() || '_';
        const fin =
          Number(st.queueCounts?.done || 0) +
          Number(st.queueCounts?.soft || 0) +
          Number(st.queueCounts?.fail || 0);
        const prevSp = enrichSpeedRef.current;
        if (!prevSp || prevSp.regionId !== speedRid) {
          enrichSpeedRef.current = {
            regionId: speedRid,
            t0: Date.now(),
            fin0: fin,
            lockedEnrich: false,
            rateEma: null,
            rateText: '',
            samples: [{ t: Date.now(), fin }],
          };
        }
      } else {
        enrichSpeedRef.current = null;
      }
      const rid = String(st.currentRegion || '').trim();
      if (rid && st.progress) {
        setEnrichProgressByRegion((prev) => ({
          ...prev,
          [rid]: st.progress || null,
        }));
      }
      if (
        st.running &&
        rid &&
        !enrichStopRequestedRef.current &&
        st.halt !== 'stop' &&
        st.halt !== 'pause' &&
        st.phase !== 'paused'
      ) {
        setEnrichRegions((prev) =>
          prev.map((r) => ({
            ...r,
            enabled: r.id === rid,
          })),
        );
      }
    };

    const sleepPoll = (ms: number) =>
      new Promise<void>((resolve, reject) => {
        if (ac.signal.aborted) {
          reject(new DOMException('Aborted', 'AbortError'));
          return;
        }
        const t = setTimeout(() => {
          ac.signal.removeEventListener('abort', onAbort);
          resolve();
        }, ms);
        const onAbort = () => {
          clearTimeout(t);
          reject(new DOMException('Aborted', 'AbortError'));
        };
        ac.signal.addEventListener('abort', onAbort, { once: true });
      });

    try {
      // 总览改间隔 GET：SSE 在刮削通知风暴下仍会拖垮设置页主线程
      while (!ac.signal.aborted) {
        const st = await getScrapLibraryEnrichStatus({ lite: true });
        if (applyTerminal(st)) {
          if (seenRunning || st.running === false) {
            flushOverviewUi(st);
          }
          break;
        }
        flushOverviewUi(st);
        await sleepPoll(OVERVIEW_POLL_MS);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      if (e instanceof Error && e.name === 'AbortError') return;
      throw e;
    } finally {
      enrichPollingRef.current = false;
      if (enrichPollRef.current === ac) enrichPollRef.current = null;
    }
  }

  async function onScrapEnrich(
    dryRun: boolean,
    regionId?: string,
    opts?: { force?: boolean },
  ) {
    if (strmBusy || localIndexBusy || catalogBusy || scrapBusy || enrichBusy) return;
    const target = String(regionId || '').trim();
    const enabled = enrichRegions.filter((r) => r.enabled);
    if (target) {
      if (!opts?.force) {
        const row = enrichRegions.find((r) => r.id === target);
        if (!row?.enabled) {
          const text = '请先开启该刮削分区';
          setMsg(text);
          onStatus(text, 'warn');
          return;
        }
      }
    } else if (!enabled.length) {
      const text = '请先开启至少一个刮削分区';
      setMsg(text);
      onStatus(text, 'warn');
      return;
    }
    setMsg('');
    setEnrichBusy(true);
    enrichStopRequestedRef.current = false;
    const resuming = Boolean(target && enrichCheckpoints[target]);
    setEnrichPhase(resuming ? '继续' : 'starting');
    setEnrichProgress({
      stage: 'prepare',
      percent: 0,
      label: resuming ? '继续' : 'starting',
    });
    // 续跑保留日志/进度；全新开才清空，避免看起来像「队列被清了」
    if (!resuming) {
      setEnrichLog([]);
    }
    if (target) {
      setEnrichCurrentRegion(target);
      if (!resuming) {
        setEnrichRegionLogs((prev) => ({ ...prev, [target]: [] }));
        setEnrichProgressByRegion((prev) => ({ ...prev, [target]: null }));
      }
    }
    const modeLabel =
      enrichMode === 'overwrite'
        ? '覆盖'
        : enrichMode === 'refresh_weak'
          ? '弱项重刮'
          : '增量';
    const regionLabel =
      (target && enrichRegions.find((r) => r.id === target)?.label) || '';
    onStatus(
      dryRun
        ? `刮削补齐预览中（${modeLabel}${regionLabel ? ` · ${regionLabel}` : ''}）…`
        : resuming
          ? `继续刮削（${modeLabel}${regionLabel ? ` · ${regionLabel}` : ''} · 保留队列）…`
          : `刮削补齐中（${modeLabel}${regionLabel ? ` · ${regionLabel}` : ''}）…`,
      'mute',
    );
    try {
      await startScrapLibraryEnrich({
        regions: target ? [target] : [],
        kinds: [
          'no_local',
          'no_media',
          'no_actress',
          'no_studio',
          'no_plot',
          'thin_title',
        ],
        limit: dryRun ? 30 : 0,
        dryRun,
        mode: enrichMode,
      });
      await pollEnrichUntilDone({ notify: true });
    } catch (e) {
      setEnrichBusy(false);
      setEnrichPhase('');
      setEnrichProgress(null);
      const text = e instanceof Error ? e.message : '启动刮削补齐失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function toggleEnrichRegion(regionId: string, enabled: boolean) {
    if (enrichRegionBusy) return;
    if (enrichBusy) {
      // 六区互斥：任务运行中只允许「关当前区（= 暂停）」，不允许直接切到别的区，
      // 否则等于「暂停 A + 启动 B」两个动作被一次点击隐式合并。
      if (enabled) {
        if (regionId !== enrichCurrentRegion) {
          const text = '刮削进行中：先关闭当前分区暂停，再开启其它分区';
          setMsg(text);
          onStatus(text, 'warn');
        }
        return;
      }
      if (enrichCurrentRegion !== regionId) return;
      setEnrichRegions((prev) =>
        prev.map((r) => (r.id === regionId ? { ...r, enabled: false } : r)),
      );
      setEnrichRegionBusy(true);
      // 立刻关忙态：后端 pause 已写检查点并把进行中退回未处理
      setEnrichBusy(false);
      setEnrichPhase('paused');
      setEnrichCurrentRegion('');
      onStatus('正在暂停刮削…', 'mute');
      try {
        await pauseScrapLibraryEnrich();
        const st = await getScrapLibraryEnrichStatus({ lite: true });
        setEnrichPhase('paused');
        setEnrichBusy(false);
        setEnrichProgress(st.progress || null);
        setEnrichLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        setEnrichRegionLogs(
          st.regionLogs && typeof st.regionLogs === 'object' ? st.regionLogs : {},
        );
        setEnrichCheckpoints(
          st.checkpoints && typeof st.checkpoints === 'object'
            ? st.checkpoints
            : {},
        );
        const cp = st.checkpoints?.[regionId];
        if (cp || st.progress) {
          setEnrichProgressByRegion((prev) => ({
            ...prev,
            [regionId]: cp
              ? {
                  stage: 'done',
                  label: '已暂停',
                  done: cp.done ?? 0,
                  total: cp.total ?? 0,
                  ok: cp.ok ?? 0,
                  failed: cp.failed ?? 0,
                  percent:
                    cp.total && cp.total > 0
                      ? Math.round((100 * (cp.done ?? 0)) / cp.total)
                      : 0,
                }
              : {
                  ...(st.progress || {}),
                  stage: 'done',
                  label: '已暂停',
                },
          }));
        }
        onStatus('已暂停刮削（进行中已退回未处理）', 'ok');
        try {
          const cur = await getScrapEnrichStrategy();
          await putScrapEnrichStrategy({
            ...cur,
            regionsEnabled: exclusiveRegionsEnabled(cur.regionsEnabled, null),
          });
        } catch {
          /* ignore */
        }
      } catch (e) {
        const text = e instanceof Error ? e.message : '暂停失败';
        setMsg(text);
        onStatus(text, 'warn');
        setEnrichRegions((prev) =>
          prev.map((r) => (r.id === regionId ? { ...r, enabled: true } : r)),
        );
      } finally {
        setEnrichRegionBusy(false);
      }
      return;
    }

    const prev = enrichRegions;
    // 六区互斥：打开一个 → 其余五个立即关闭（并落库）；关闭一个 → 六个全关
    setEnrichRegions(applyExclusiveRegion(prev, enabled ? regionId : null));

    // 仅短暂占用 busy（写策略）；长跑期间必须放开开关以便暂停
    setEnrichRegionBusy(true);
    try {
      const cur = await getScrapEnrichStrategy();
      await putScrapEnrichStrategy({
        ...cur,
        regionsEnabled: exclusiveRegionsEnabled(
          cur.regionsEnabled,
          enabled ? regionId : null,
        ),
      });
    } catch (e) {
      setEnrichRegions(prev);
      const text = e instanceof Error ? e.message : '分区刮削失败';
      setMsg(text);
      onStatus(text, 'warn');
      setEnrichRegionBusy(false);
      return;
    }
    setEnrichRegionBusy(false);
    if (!enabled) return;

    try {
      await onScrapEnrich(false, regionId, { force: true });
      // 结束或暂停后六区全关；有检查点时下次打开即继续
      setEnrichRegions((rows) => applyExclusiveRegion(rows, null));
      try {
        const after = await getScrapEnrichStrategy();
        await putScrapEnrichStrategy({
          ...after,
          regionsEnabled: exclusiveRegionsEnabled(after.regionsEnabled, null),
        });
      } catch {
        /* ignore persist */
      }
    } catch (e) {
      setEnrichRegions(prev);
      const text = e instanceof Error ? e.message : '分区刮削失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  return {
    enrichBusy,
    enrichPhase,
    enrichProgress,
    enrichProgressByRegion,
    enrichLog,
    enrichRegionLogs,
    enrichCurrentRegion,
    enrichCheckpoints,
    enrichQueueCounts,
    enrichRegionQueueCounts,
    enrichLibrary,
    enrichMode,
    setEnrichMode,
    enrichRegions,
    enrichRegionBusy,
    enrichSpeedRef,
    onScrapEnrich,
    toggleEnrichRegion,
  };
}
