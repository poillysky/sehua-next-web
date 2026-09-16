'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Folder, FolderPlus, RefreshCw } from 'lucide-react';
import {
  browsePrefixCatalogStrmDirs,
  getPrefixCatalogHarvestStatus,
  getPrefixCatalogLocalIndexStatus,
  getPrefixCatalogPrefixDetail,
  getPrefixCatalogPrefixes,
  getPrefixCatalogStrmSyncSettings,
  getPrefixCatalogStrmSyncStatus,
  getPrefixCatalogSummary,
  getScrapLibraryEmbedSettings,
  getScrapLibraryEmbedStatus,
  getScrapActressOptimizeStatus,
  getScrapActressAvatarStatus,
  getScrapLibraryEnrichStatus,
  subscribeScrapLibraryEnrichStatus,
  pauseScrapLibraryEnrich,
  getScrapLibraryQuality,
  getScrapLibraryQualityGate,
  getScrapLibraryQualityItems,
  getScrapEnrichStrategy,
  putScrapEnrichStrategy,
  mkdirPrefixCatalogStrmDir,
  putPrefixCatalogStrmSyncSettings,
  putScrapLibraryEmbedSettings,
  startPrefixCatalogAvwikidbSync,
  startPrefixCatalogLocalIndex,
  startPrefixCatalogStrmSync,
  startScrapLibraryEmbed,
  startScrapActressOptimize,
  startScrapActressAvatar,
  startScrapLibraryEnrich,
  type PrefixCatalogLocalIndexProgress,
  type PrefixCatalogPrefixDetail,
  type PrefixCatalogPrefixRow,
  type PrefixCatalogStrmBrowse,
  type PrefixCatalogSummary,
  type ScrapLibraryEnrichCheckpoint,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryQualityStats,
  type ScrapActressOptimizeJobStatus,
  type ScrapActressAvatarJobStatus,
} from '@/lib/api';
import { MAKER_KIND_TABS } from '@/features/makers/makersUi';
import { AppPush } from '@/components/ui/AppPush';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { AutoscrollLogList } from './AutoscrollLogList';
import { AppMsg } from '@/components/ui/AppMsg';
import { Switch } from '@/components/ui/switch';
import { ScrapeSourcesSection } from '@/features/settings/ScrapeSourcesSection';
import { EnrichStrategyPanel } from '@/features/settings/EnrichStrategyPanel';
import { EnrichLivePanel } from '@/features/settings/EnrichLivePanel';
import { cn } from '@/lib/utils';

const CODES_PAGE_SIZE = 50;

type ScanLogModal =
  | 'local'
  | 'avwikidb'
  | 'strm'
  | 'scrap'
  | 'actress'
  | 'actressAvatar'
  | 'enrich'
  | { qualityRegion: string; label: string }
  | null;

type CatalogNav =
  | { level: 'regions' }
  | { level: 'region'; regionId: string; label: string }
  | {
      level: 'prefix';
      regionId: string;
      regionLabel: string;
      prefix: string;
    };

function normalizeEnrichFillMode(
  raw: string | undefined,
): 'incremental' | 'refresh_weak' | 'overwrite' {
  if (raw === 'overwrite') return 'overwrite';
  if (raw === 'refresh_weak') return 'refresh_weak';
  return 'incremental';
}

export function MakersManagePanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [catalogNav, setCatalogNav] = useState<CatalogNav | null>(null);
  const [catalogSummary, setCatalogSummary] = useState<PrefixCatalogSummary | null>(
    null,
  );
  const [catalogPrefixes, setCatalogPrefixes] = useState<PrefixCatalogPrefixRow[]>(
    [],
  );
  const [catalogDetail, setCatalogDetail] =
    useState<PrefixCatalogPrefixDetail | null>(null);
  const [catalogCodePage, setCatalogCodePage] = useState(1);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [enrichStrategyOpen, setEnrichStrategyOpen] = useState(false);
  const [enrichLive, setEnrichLive] = useState<{
    regionId: string;
    label: string;
    initialStatus?: ScrapLibraryEnrichJobStatus | null;
    initialLogs?: string[];
  } | null>(null);
  const [scrapHubOpen, setScrapHubOpen] = useState(false);
  const [localIndexBusy, setLocalIndexBusy] = useState(false);
  const [localIndexPhase, setLocalIndexPhase] = useState('');
  const [localIndexProgress, setLocalIndexProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [localIndexLog, setLocalIndexLog] = useState<string[]>([]);
  const localIndexPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const localIndexPollingRef = useRef(false);
  const [avwikiBusy, setAvwikiBusy] = useState(false);
  const [avwikiPhase, setAvwikiPhase] = useState('');
  const [avwikiLog, setAvwikiLog] = useState<string[]>([]);
  const avwikiPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const avwikiPollingRef = useRef(false);
  const [strmRoot, setStrmRoot] = useState('');
  const [strmBusy, setStrmBusy] = useState(false);
  const [strmPhase, setStrmPhase] = useState('');
  const [strmProgress, setStrmProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [strmLog, setStrmLog] = useState<string[]>([]);
  const strmPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const strmPollingRef = useRef(false);
  const [strmBrowseOpen, setStrmBrowseOpen] = useState(false);
  const [strmBrowseKind, setStrmBrowseKind] = useState<'strm' | 'scrap'>('strm');
  const [strmBrowse, setStrmBrowse] = useState<PrefixCatalogStrmBrowse | null>(
    null,
  );
  const [strmBrowseLoading, setStrmBrowseLoading] = useState(false);
  const [strmNewFolder, setStrmNewFolder] = useState('');
  const [strmBrowseMsg, setStrmBrowseMsg] = useState('');
  const [scrapRoot, setScrapRoot] = useState('scrap-library');
  const [scrapBusy, setScrapBusy] = useState(false);
  const [scrapPhase, setScrapPhase] = useState('');
  const [scrapProgress, setScrapProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [scrapLog, setScrapLog] = useState<string[]>([]);
  const scrapPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrapPollingRef = useRef(false);
  const [actressOptBusy, setActressOptBusy] = useState(false);
  const [actressOptPhase, setActressOptPhase] = useState('');
  const [actressOptProgress, setActressOptProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [actressOptLog, setActressOptLog] = useState<string[]>([]);
  const actressOptPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const actressOptPollingRef = useRef(false);

  const [actressAvatarBusy, setActressAvatarBusy] = useState(false);
  const [actressAvatarPhase, setActressAvatarPhase] = useState('');
  const [actressAvatarProgress, setActressAvatarProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [actressAvatarLog, setActressAvatarLog] = useState<string[]>([]);
  const [actressAvatarMode, setActressAvatarMode] = useState<
    'incremental' | 'overwrite'
  >('incremental');
  const actressAvatarPollRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const actressAvatarPollingRef = useRef(false);
  const [scrapQualityByRegion, setScrapQualityByRegion] = useState<
    Record<string, ScrapLibraryQualityStats>
  >({});
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
  const [enrichRegions, setEnrichRegions] = useState<
    Array<{ id: string; label: string; enabled: boolean }>
  >([]);
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
  } | null>(null);
  const [scanLogModal, setScanLogModal] = useState<ScanLogModal>(null);
  const [gateBusy, setGateBusy] = useState(false);
  const [gateSummary, setGateSummary] = useState('');

  async function refreshScrapQuality(regionIds?: string[]) {
    const ids =
      regionIds && regionIds.length
        ? regionIds
        : MAKER_KIND_TABS.map((t) => t.id);
    const entries = await Promise.all(
      ids.map(async (id) => {
        try {
          const stats = await getScrapLibraryQuality(id);
          return [id, stats] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    );
    const next: Record<string, ScrapLibraryQualityStats> = {};
    for (const [id, stats] of entries) {
      if (stats) next[id] = stats;
    }
    setScrapQualityByRegion((prev) => ({ ...prev, ...next }));
    return next;
  }

  useEffect(() => {
    // 热重载会保留旧 msg，避免进页再弹一次完成 Toast
    setMsg('');
    void (async () => {
      try {
        setCatalogSummary(await getPrefixCatalogSummary());
      } catch {
        setCatalogSummary(null);
      }
      try {
        const s = await getPrefixCatalogStrmSyncSettings();
        setStrmRoot(s.root || 'strm-library');
      } catch {
        setStrmRoot('strm-library');
      }
      try {
        const s = await getScrapLibraryEmbedSettings();
        setScrapRoot(s.root || 'scrap-library');
      } catch {
        setScrapRoot('scrap-library');
      }
      try {
        const st = await getScrapLibraryEmbedStatus();
        if (st.running) {
          setScrapBusy(true);
          setScrapPhase(st.phase || '同步中…');
          setScrapProgress(st.progress || null);
          setScrapLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          void pollScrapEmbedUntilDone();
        }
        // 已完成的结果不在每次打开时再弹提示（完成时已提示过）
      } catch {
        /* ignore */
      }
      try {
        const st = await getScrapActressOptimizeStatus();
        if (st.running) {
          setActressOptBusy(true);
          setActressOptPhase(st.phase || '优化中…');
          setActressOptProgress(st.progress || null);
          setActressOptLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          void pollActressOptUntilDone();
        }
      } catch {
        /* ignore */
      }
      try {
        const st = await getScrapLibraryEnrichStatus();
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
        if (st.library && typeof st.library === 'object') {
          setEnrichLibrary(st.library);
        }
        // 暂停检查点：用库回填后的 ok/failed/remaining 画分区进度
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
          // 开关 = 开始/暂停：仅当前正在跑的分区保持开
          setEnrichRegions(
            (strat.regions || MAKER_KIND_TABS.map((t) => ({ id: t.id, label: t.label }))).map(
              (r) => ({
                id: r.id,
                label: r.label,
                enabled: Boolean(st.running && runningRegion === r.id),
              }),
            ),
          );
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
  }, []);

  useEffect(() => {
    return () => {
      if (localIndexPollRef.current) clearTimeout(localIndexPollRef.current);
      if (avwikiPollRef.current) clearTimeout(avwikiPollRef.current);
      if (strmPollRef.current) clearTimeout(strmPollRef.current);
      if (scrapPollRef.current) clearTimeout(scrapPollRef.current);
      if (actressOptPollRef.current) clearTimeout(actressOptPollRef.current);
      if (actressAvatarPollRef.current)
        clearTimeout(actressAvatarPollRef.current);
      enrichPollRef.current?.abort();
    };
  }, []);

  async function refreshCatalogSummary() {
    try {
      setCatalogSummary(await getPrefixCatalogSummary());
    } catch {
      /* keep previous */
    }
  }

  async function pollLocalIndexUntilDone() {
    if (localIndexPollingRef.current) return;
    localIndexPollingRef.current = true;
    try {
      for (;;) {
        const st = await getPrefixCatalogLocalIndexStatus();
        setLocalIndexBusy(st.running);
        setLocalIndexPhase(st.phase || (st.running ? '扫描中…' : ''));
        setLocalIndexProgress(st.progress || null);
        setLocalIndexLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('双库扫描失败', 'warn');
          } else if (st.result) {
            const updated = st.result.updated ?? 0;
            const codes = st.result.summary?.code_total;
            const skIns = st.result.skeleton?.inserted ?? 0;
            const skSkip = st.result.skeleton?.skipped_existing ?? 0;
            const skCodes = st.result.skeleton?.purged_codes ?? 0;
            const skBits: string[] = [];
            if (st.result.skeleton?.ok) {
              skBits.push(`骨架 +${skIns} / 已有 ${skSkip}`);
              if (skCodes > 0) skBits.push(`清目录外向量 ${skCodes}`);
            }
            const skPart = skBits.length ? ` · ${skBits.join(' · ')}` : '';
            setMsg(
              codes != null
                ? `扫描完成 · 更新 ${updated} 前缀 · ${codes} 番号${skPart}`
                : `扫描完成 · 更新 ${updated} 前缀${skPart}`,
            );
            onStatus('双库扫描完成', 'ok');
            await refreshCatalogSummary();
          }
          setLocalIndexPhase('');
          setLocalIndexProgress(null);
          // 保留日志供弹窗回看
          return;
        }
        await new Promise<void>((resolve) => {
          localIndexPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      localIndexPollingRef.current = false;
    }
  }

  async function onLocalIndexScan() {
    if (localIndexBusy || avwikiBusy || catalogBusy || strmBusy) return;
    setMsg('');
    setLocalIndexBusy(true);
    setLocalIndexPhase('starting');
    setLocalIndexProgress({
      stage: 'prepare',
      percent: 0,
      label: 'starting',
    });
    setLocalIndexLog([]);
    onStatus('双库扫描中…', 'mute');
    try {
      await startPrefixCatalogLocalIndex();
      await pollLocalIndexUntilDone();
    } catch (e) {
      setLocalIndexBusy(false);
      setLocalIndexPhase('');
      setLocalIndexProgress(null);
      const text = e instanceof Error ? e.message : '启动双库扫描失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollAvwikiUntilDone() {
    if (avwikiPollingRef.current) return;
    avwikiPollingRef.current = true;
    try {
      for (;;) {
        const st = await getPrefixCatalogHarvestStatus();
        setAvwikiBusy(st.running);
        setAvwikiPhase(st.phase || (st.running ? '同步中…' : ''));
        setAvwikiLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('AVWikiDB 同步失败', 'warn');
          } else if (st.result) {
            const added = st.result.added ?? 0;
            const refreshed = st.result.refreshed ?? st.result.checked ?? 0;
            const prefixes = st.result.summary?.prefix_total;
            setMsg(
              prefixes != null
                ? `厂牌映射完成 · 核对 ${refreshed} · 新增前缀 ${added} · 合计 ${prefixes}`
                : `厂牌映射完成 · 核对 ${refreshed} · 新增前缀 ${added}`,
            );
            onStatus('AVWikiDB 厂牌映射完成', 'ok');
            await refreshCatalogSummary();
          }
          setAvwikiPhase('');
          return;
        }
        await new Promise<void>((resolve) => {
          avwikiPollRef.current = setTimeout(resolve, 600);
        });
      }
    } finally {
      avwikiPollingRef.current = false;
    }
  }

  async function onAvwikiSync() {
    if (avwikiBusy || localIndexBusy || catalogBusy || strmBusy) return;
    setMsg('');
    setAvwikiBusy(true);
    setAvwikiPhase('starting');
    setAvwikiLog([]);
    onStatus('AVWikiDB 厂牌映射中…', 'mute');
    try {
      await startPrefixCatalogAvwikidbSync({
        region: 'japan_censored',
        expand: true,
        minMovieCount: 5,
      });
      await pollAvwikiUntilDone();
    } catch (e) {
      setAvwikiBusy(false);
      setAvwikiPhase('');
      const text = e instanceof Error ? e.message : '启动 AVWikiDB 同步失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollStrmSyncUntilDone() {
    if (strmPollingRef.current) return;
    strmPollingRef.current = true;
    try {
      for (;;) {
        const st = await getPrefixCatalogStrmSyncStatus();
        setStrmBusy(st.running);
        setStrmPhase(st.phase || (st.running ? '同步中…' : ''));
        setStrmProgress(st.progress || null);
        setStrmLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('STRM 同步失败', 'warn');
          } else if (st.result) {
            const written = st.result.written ?? 0;
            const deleted = st.result.deleted ?? 0;
            const total = st.result.total ?? 0;
            const skIns = st.result.skeleton?.inserted ?? 0;
            const skSkip = st.result.skeleton?.skipped_existing ?? 0;
            const skCodes = st.result.skeleton?.purged_codes ?? 0;
            const bits = [`写入 ${written}`, `合计 ${total}`];
            if (deleted > 0) bits.push(`删多余 ${deleted}`);
            if (st.result.skeleton?.ok) {
              bits.push(`骨架 +${skIns} / 已有 ${skSkip}`);
              if (skCodes > 0) bits.push(`清目录外向量 ${skCodes}`);
            }
            setMsg(`STRM 同步完成 · ${bits.join(' · ')}`);
            onStatus('STRM 同步完成', 'ok');
          }
          setStrmPhase('');
          setStrmProgress(null);
          // 保留日志，方便点「日志」回看
          return;
        }
        await new Promise<void>((resolve) => {
          strmPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      strmPollingRef.current = false;
    }
  }

  async function loadStrmBrowse(path = '') {
    setStrmBrowseLoading(true);
    setStrmBrowseMsg('');
    try {
      setStrmBrowse(await browsePrefixCatalogStrmDirs(path));
    } catch (e) {
      setStrmBrowseMsg(e instanceof Error ? e.message : '浏览失败');
    } finally {
      setStrmBrowseLoading(false);
    }
  }

  async function openStrmBrowse() {
    if (strmBusy || localIndexBusy || scrapBusy) return;
    setStrmBrowseKind('strm');
    setStrmBrowseOpen(true);
    setStrmNewFolder('');
    // 从已选目录的父层打开更顺手：已选 strm-library 则停在 media 根看到它
    const start =
      strmRoot.includes('/') || strmRoot.includes('\\')
        ? strmRoot.replace(/\\/g, '/').split('/').slice(0, -1).join('/')
        : '';
    await loadStrmBrowse(start);
  }

  async function openScrapBrowse() {
    if (strmBusy || localIndexBusy || scrapBusy) return;
    setStrmBrowseKind('scrap');
    setStrmBrowseOpen(true);
    setStrmNewFolder('');
    const start =
      scrapRoot.includes('/') || scrapRoot.includes('\\')
        ? scrapRoot.replace(/\\/g, '/').split('/').slice(0, -1).join('/')
        : '';
    await loadStrmBrowse(start);
  }

  async function onPickStrmDir() {
    const path = strmBrowse?.path || '';
    const fallback = strmBrowseKind === 'scrap' ? 'scrap-library' : 'strm-library';
    const picked = path || fallback;
    try {
      if (strmBrowseKind === 'scrap') {
        const s = await putScrapLibraryEmbedSettings(picked);
        setScrapRoot(s.root || picked);
        setMsg(`已选择刮削库 · media/${s.root}`);
      } else {
        const s = await putPrefixCatalogStrmSyncSettings(picked);
        setStrmRoot(s.root || picked);
        setMsg(`已选择 · media/${s.root}`);
      }
      setStrmBrowseOpen(false);
      onStatus('目录已保存', 'ok');
    } catch (e) {
      setStrmBrowseMsg(e instanceof Error ? e.message : '保存失败');
    }
  }

  async function onCreateStrmFolder() {
    const name = strmNewFolder.trim();
    if (!name) {
      setStrmBrowseMsg('请输入文件夹名');
      return;
    }
    setStrmBrowseLoading(true);
    setStrmBrowseMsg('');
    try {
      const parent = strmBrowse?.path || '';
      await mkdirPrefixCatalogStrmDir(parent, name);
      setStrmNewFolder('');
      await loadStrmBrowse(parent);
    } catch (e) {
      setStrmBrowseMsg(e instanceof Error ? e.message : '创建失败');
    } finally {
      setStrmBrowseLoading(false);
    }
  }

  async function onStrmSync() {
    if (strmBusy || localIndexBusy || catalogBusy || scrapBusy || enrichBusy) return;
    const root = strmRoot.trim() || 'strm-library';
    setMsg('');
    setStrmBusy(true);
    setStrmPhase('starting');
    setStrmProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setStrmLog([]);
    onStatus('STRM 同步中…', 'mute');
    try {
      await startPrefixCatalogStrmSync(root);
      await pollStrmSyncUntilDone();
    } catch (e) {
      setStrmBusy(false);
      setStrmPhase('');
      setStrmProgress(null);
      const text = e instanceof Error ? e.message : '启动 STRM 同步失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollScrapEmbedUntilDone(opts?: { notify?: boolean }) {
    if (scrapPollingRef.current) return;
    scrapPollingRef.current = true;
    // 用户刚点的同步：即使首轮已结束也要提示；挂载续跑则必须亲眼见过 running
    let seenRunning = Boolean(opts?.notify);
    try {
      for (;;) {
        const st = await getScrapLibraryEmbedStatus();
        if (st.running) seenRunning = true;
        setScrapBusy(st.running);
        setScrapPhase(st.phase || (st.running ? '同步中…' : ''));
        setScrapProgress(st.progress || null);
        setScrapLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (seenRunning) {
            if (st.error) {
              setMsg(st.error);
              onStatus('刮削库向量同步失败', 'warn');
            } else if (st.result) {
              const written = st.result.written ?? 0;
              const total = st.result.total ?? 0;
              const deleted = st.result.deleted ?? 0;
              setMsg(
                deleted > 0
                  ? `刮削库已写入元库 · ${written}/${total} · 删多余 ${deleted}`
                  : `刮削库已写入元库 · ${written}/${total}`,
              );
              onStatus('刮削库向量已同步', 'ok');
            }
          }
          setScrapBusy(false);
          setScrapPhase('');
          setScrapProgress(null);
          // 保留日志供弹窗回看
          return;
        }
        await new Promise<void>((resolve) => {
          scrapPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      scrapPollingRef.current = false;
    }
  }

  async function onScrapEmbedSync(force = false) {
    if (
      strmBusy ||
      localIndexBusy ||
      catalogBusy ||
      scrapBusy ||
      enrichBusy ||
      actressOptBusy ||
      actressAvatarBusy
    )
      return;
    const root = scrapRoot.trim() || 'scrap-library';
    setMsg('');
    setScrapBusy(true);
    setScrapPhase(force ? '全量同步…' : '增量同步…');
    setScrapProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setScrapLog([]);
    onStatus(
      force ? '刮削库全量向量同步中…' : '刮削库增量向量同步中（跳过已有）…',
      'mute',
    );
    try {
      await startScrapLibraryEmbed({ root, force });
      await pollScrapEmbedUntilDone({ notify: true });
    } catch (e) {
      setScrapBusy(false);
      setScrapPhase('');
      setScrapProgress(null);
      const text = e instanceof Error ? e.message : '启动刮削库同步失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollActressOptUntilDone(opts?: { notify?: boolean }) {
    if (actressOptPollingRef.current) return;
    actressOptPollingRef.current = true;
    let seenRunning = Boolean(opts?.notify);
    try {
      for (;;) {
        const st = await getScrapActressOptimizeStatus();
        if (st.running) seenRunning = true;
        setActressOptBusy(st.running);
        setActressOptPhase(st.phase || (st.running ? '优化中…' : ''));
        setActressOptProgress(st.progress || null);
        setActressOptLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (seenRunning) {
            if (st.error) {
              setMsg(st.error);
              onStatus('对齐向量库女优名失败', 'warn');
            } else if (st.result) {
              const updated = st.result.updated ?? 0;
              const total = st.result.total ?? 0;
              const reemb = st.result.reembedded ?? 0;
              const maps = st.result.maps?.count ?? 0;
              setMsg(
                `女优名已对齐 · 更新 ${updated}/${total} · 重嵌 ${reemb} · 映射表 ${maps} 条`,
              );
              onStatus('女优名已对齐', 'ok');
            }
          }
          setActressOptBusy(false);
          setActressOptPhase('');
          setActressOptProgress(null);
          return;
        }
        await new Promise<void>((resolve) => {
          actressOptPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      actressOptPollingRef.current = false;
    }
  }

  async function onActressOptimize(force = false) {
    if (
      strmBusy ||
      localIndexBusy ||
      catalogBusy ||
      scrapBusy ||
      enrichBusy ||
      actressOptBusy ||
      actressAvatarBusy
    )
      return;
    setMsg('');
    setActressOptBusy(true);
    setActressOptPhase(force ? '全量重嵌…' : '增量对齐…');
    setActressOptProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setActressOptLog([]);
    onStatus(
      force
        ? '全量重嵌标题向量女优名…'
        : '增量对齐标题向量女优名（跳过已对齐）…',
      'mute',
    );
    try {
      await startScrapActressOptimize({ reembed: true, force });
      await pollActressOptUntilDone({ notify: true });
    } catch (e) {
      setActressOptBusy(false);
      setActressOptPhase('');
      setActressOptProgress(null);
      const text = e instanceof Error ? e.message : '启动女优优化失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollActressAvatarUntilDone(opts?: { notify?: boolean }) {
    if (actressAvatarPollingRef.current) return;
    actressAvatarPollingRef.current = true;
    let seenRunning = Boolean(opts?.notify);
    try {
      for (;;) {
        const st: ScrapActressAvatarJobStatus =
          await getScrapActressAvatarStatus();
        if (st.running) seenRunning = true;
        setActressAvatarBusy(st.running);
        setActressAvatarPhase(st.phase || (st.running ? '刮削中…' : ''));
        setActressAvatarProgress(st.progress || null);
        setActressAvatarLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (seenRunning) {
            if (st.error) {
              setMsg(st.error);
              onStatus('女优刮削失败', 'warn');
            } else if (st.result) {
              const downloaded = st.result.downloaded ?? 0;
              const skipped = st.result.skipped ?? 0;
              const missed = st.result.missed ?? 0;
              const total = st.result.total ?? 0;
              const gf = st.result.downloadedGfriends ?? 0;
              const jb = st.result.downloadedJavbus ?? 0;
              const srcHint =
                gf || jb ? `（GFriends ${gf} · JavBus ${jb}）` : '';
              const polish = st.result.polish;
              const polishHint =
                polish && typeof polish.updated === 'number'
                  ? ` · 元数据更新 ${polish.updated}/${polish.total ?? '?'}`
                  : '';
              const bio = (
                st.result as {
                  bio?: { n?: number; bioOk?: number };
                  gaps?: {
                    missingAvatarN?: number;
                    missingBioN?: number;
                  };
                }
              ).bio;
              const gaps = (
                st.result as {
                  gaps?: { missingAvatarN?: number; missingBioN?: number };
                }
              ).gaps;
              const bioHint =
                bio && typeof bio.bioOk === 'number'
                  ? ` · 资料齐 ${bio.bioOk}/${bio.n ?? '?'}`
                  : '';
              const gapHint =
                gaps &&
                ((gaps.missingAvatarN ?? 0) > 0 || (gaps.missingBioN ?? 0) > 0)
                  ? ` · 仍缺头像 ${gaps.missingAvatarN ?? 0} / 资料 ${gaps.missingBioN ?? 0}`
                  : '';
              setMsg(
                `女优刮削完成${polishHint} · 头像新下 ${downloaded}${srcHint} · 跳过 ${skipped} · 未命中 ${missed} / 共 ${total}${bioHint}${gapHint}`,
              );
              onStatus('女优刮削完成', 'ok');
            }
          }
          setActressAvatarBusy(false);
          setActressAvatarPhase('');
          setActressAvatarProgress(null);
          return;
        }
        await new Promise<void>((resolve) => {
          actressAvatarPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      actressAvatarPollingRef.current = false;
    }
  }

  async function onActressAvatarScrape(force = false) {
    if (
      strmBusy ||
      localIndexBusy ||
      catalogBusy ||
      scrapBusy ||
      enrichBusy ||
      actressOptBusy ||
      actressAvatarBusy
    )
      return;
    setMsg('');
    setActressAvatarBusy(true);
    setActressAvatarPhase(force ? '全量覆盖刮削…' : '增量刮削…');
    setActressAvatarProgress({
      stage: 'prepare',
      percent: 0,
      label: 'starting',
    });
    setActressAvatarLog([]);
    onStatus(
      force
        ? '女优全量覆盖刮削中（仅本地）…'
        : '女优增量刮削中（跳过已有头像·仅本地）…',
      'mute',
    );
    try {
      await startScrapActressAvatar({
        force,
        // 只落本地 + Meta；标题向量女优名对齐用下方「对齐向量库女优名」
        polishMeta: false,
      });
      await pollActressAvatarUntilDone({ notify: true });
    } catch (e) {
      setActressAvatarBusy(false);
      setActressAvatarPhase('');
      setActressAvatarProgress(null);
      const text = e instanceof Error ? e.message : '启动女优刮削失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

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

    try {
      await subscribeScrapLibraryEnrichStatus(
        (st) => {
          if (st.running) seenRunning = true;
          setEnrichBusy(st.running);
          setEnrichPhase(st.phase || (st.running ? '补齐中…' : ''));
          setEnrichProgress(st.progress || null);
          setEnrichLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          setEnrichRegionLogs(
            st.regionLogs && typeof st.regionLogs === 'object'
              ? st.regionLogs
              : {},
          );
          setEnrichCurrentRegion(String(st.currentRegion || ''));
          setEnrichCheckpoints(
            st.checkpoints && typeof st.checkpoints === 'object'
              ? st.checkpoints
              : {},
          );
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
            // 运行中偶发缺字段时保留上次计数，避免进度条闪跳
            if (st.running && prev) return prev;
            if (st.paused || st.phase === 'paused' || st.halt === 'pause') {
              return prev;
            }
            return null;
          });
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
          if (applyTerminal(st)) {
            ac.abort();
          }
        },
        { signal: ac.signal },
      );
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
      // 关掉开关 = 暂停：保留队列/检查点，下次打开继续
      if (enabled) return;
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
        const st = await getScrapLibraryEnrichStatus();
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
    const next = prev.map((r) =>
      r.id === regionId ? { ...r, enabled } : r,
    );
    setEnrichRegions(next);
    if (!enabled) return;

    // 仅短暂占用 busy（写策略）；长跑期间必须放开开关以便暂停
    setEnrichRegionBusy(true);
    try {
      const cur = await getScrapEnrichStrategy();
      const regionsEnabled: Record<string, boolean> = {
        ...(cur.regionsEnabled || {}),
        [regionId]: true,
      };
      await putScrapEnrichStrategy({
        ...cur,
        regionsEnabled,
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

    try {
      await onScrapEnrich(false, regionId, { force: true });
      // 结束或暂停后关掉开关；有检查点时下次打开即继续
      setEnrichRegions((rows) =>
        rows.map((r) => (r.id === regionId ? { ...r, enabled: false } : r)),
      );
      try {
        const after = await getScrapEnrichStrategy();
        await putScrapEnrichStrategy({
          ...after,
          regionsEnabled: {
            ...(after.regionsEnabled || {}),
            [regionId]: false,
          },
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

  useEffect(() => {
    if (catalogNav?.level !== 'regions' && !scrapHubOpen) return;
    void (async () => {
      if (catalogNav?.level === 'regions') {
      try {
        const st = await getPrefixCatalogLocalIndexStatus();
        if (st.running) {
          setLocalIndexBusy(true);
          setLocalIndexPhase(st.phase || '扫描中…');
          await pollLocalIndexUntilDone();
        }
      } catch {
        /* ignore */
      }
      try {
        const st = await getPrefixCatalogStrmSyncStatus();
        if (st.running) {
          setStrmBusy(true);
          setStrmPhase(st.phase || '同步中…');
          await pollStrmSyncUntilDone();
        }
      } catch {
        /* ignore */
        }
      }
      try {
        const st = await getScrapLibraryEmbedStatus();
        if (st.running) {
          setScrapBusy(true);
          setScrapPhase(st.phase || '同步中…');
          setScrapProgress(st.progress || null);
          setScrapLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          await pollScrapEmbedUntilDone();
        }
      } catch {
        /* ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resume poll when opening regions / scrap hub
  }, [catalogNav?.level, scrapHubOpen]);

  async function openCatalogRegion(regionId: string, label: string) {
    setMsg('');
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setCatalogPrefixes([]);
    setCatalogNav({ level: 'region', regionId, label });
    setCatalogBusy(true);
    try {
      setCatalogPrefixes(await getPrefixCatalogPrefixes(regionId));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取前缀失败');
    } finally {
      setCatalogBusy(false);
    }
  }

  async function loadCatalogCodes(
    regionId: string,
    prefix: string,
    page: number,
  ) {
    setCatalogBusy(true);
    try {
      const offset = Math.max(0, (page - 1) * CODES_PAGE_SIZE);
      setCatalogDetail(
        await getPrefixCatalogPrefixDetail(regionId, prefix, {
          offset,
          limit: CODES_PAGE_SIZE,
        }),
      );
      setCatalogCodePage(page);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取番号失败');
    } finally {
      setCatalogBusy(false);
    }
  }

  async function openCatalogPrefix(
    regionId: string,
    regionLabel: string,
    prefix: string,
  ) {
    setMsg('');
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setCatalogNav({ level: 'prefix', regionId, regionLabel, prefix });
    await loadCatalogCodes(regionId, prefix, 1);
  }

  function openCatalogRegions() {
    setMsg('');
    setCatalogNav({ level: 'regions' });
  }

  function catalogRegionsBack() {
    setCatalogNav(null);
    setMsg('');
  }

  function catalogRegionBack() {
    setCatalogNav({ level: 'regions' });
    setCatalogPrefixes([]);
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setMsg('');
  }

  function catalogPrefixBack() {
    if (!catalogNav || catalogNav.level !== 'prefix') return;
    // 不要重新拉取前缀列表，否则会清空 DOM、冲掉已记住的滚动位置
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setMsg('');
    setCatalogNav({
      level: 'region',
      regionId: catalogNav.regionId,
      label: catalogNav.regionLabel,
    });
  }

  const codeTotal = catalogDetail?.code_count ?? 0;
  const codePages = Math.max(1, Math.ceil(codeTotal / CODES_PAGE_SIZE));

  if (sourcesOpen) {
    return (
      <ScrapeSourcesSection
        onBack={() => setSourcesOpen(false)}
        onStatus={onStatus}
      />
    );
  }

  if (enrichStrategyOpen) {
    return (
      <EnrichStrategyPanel
        onBack={() => setEnrichStrategyOpen(false)}
        onStatus={onStatus}
        onSaved={(saved) => {
          setEnrichMode(normalizeEnrichFillMode(saved.fillMode));
          setActressAvatarMode(
            saved.actressAvatarMode === 'overwrite'
              ? 'overwrite'
              : 'incremental',
          );
        }}
      />
    );
  }

  if (enrichLive) {
    return (
      <EnrichLivePanel
        regionId={enrichLive.regionId}
        label={enrichLive.label}
        initialStatus={enrichLive.initialStatus}
        initialLogs={enrichLive.initialLogs}
        onBack={() => setEnrichLive(null)}
        onStatus={onStatus}
      />
    );
  }

  if (strmBrowseOpen) {
    const crumbs = strmBrowse?.crumbs || [];
    const folders = strmBrowse?.folders || [];
    const herePath = strmBrowse?.path || '';
    const hereName = crumbs.length
      ? crumbs[crumbs.length - 1]!.name
      : '';
    const activeRoot =
      strmBrowseKind === 'scrap'
        ? scrapRoot || 'scrap-library'
        : strmRoot || 'strm-library';
    const hereIsCurrent = !!herePath && activeRoot === herePath;
    const parentPath = herePath.includes('/')
      ? herePath.split('/').slice(0, -1).join('/')
      : '';
    const defaultName =
      strmBrowseKind === 'scrap' ? 'scrap-library' : 'strm-library';

    async function pickFolder(path: string) {
      try {
        if (strmBrowseKind === 'scrap') {
          const s = await putScrapLibraryEmbedSettings(path);
          setScrapRoot(s.root || path);
          setMsg(`已选择刮削库 · media/${s.root}`);
        } else {
          const s = await putPrefixCatalogStrmSyncSettings(path);
          setStrmRoot(s.root || path);
          setMsg(`已选择 · media/${s.root}`);
        }
        setStrmBrowseOpen(false);
        onStatus('目录已保存', 'ok');
      } catch (e) {
        setStrmBrowseMsg(e instanceof Error ? e.message : '保存失败');
      }
    }

    return (
      <AppPush
        title={
          hereName ||
          (strmBrowseKind === 'scrap' ? '选择刮削库目录' : '选择输出目录')
        }
        onBack={() => {
          if (herePath) {
            void loadStrmBrowse(parentPath);
            return;
          }
          setStrmBrowseOpen(false);
        }}
        scrollKey={
          strmBrowseKind === 'scrap' ? 'scrap-browse' : 'strm-browse'
        }
        right={
          <div className="strm-pick__nav-right">
            <button
              type="button"
              className="strm-pick__icon-btn"
              disabled={strmBrowseLoading}
              aria-label="刷新"
              onClick={() => void loadStrmBrowse(herePath)}
            >
              <RefreshCw
                size={15}
                strokeWidth={2.2}
                className={strmBrowseLoading ? 'strm-pick__spin' : undefined}
              />
            </button>
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={strmBrowseLoading}
              onClick={() => void onPickStrmDir()}
            >
              选用此层
            </button>
          </div>
        }
      >
        <div className="makers-manage makers-manage--detail makers-manage--strm-pick">
          <div className="strm-pick">
            <p className="settings-group-label">文件夹</p>
            <ul className="settings-group makers-manage__rise strm-pick__list">
              {strmBrowseLoading && folders.length === 0 ? (
                <li>
                  <div className="strm-pick__empty">加载中…</div>
                </li>
              ) : folders.length === 0 ? (
                <li>
                  <div className="strm-pick__empty">
                    没有子文件夹 · 可点右上角「选用此层」
                  </div>
                </li>
              ) : (
                folders.map((f) => {
                  const selected = activeRoot === f.path;
                  const isDefault = f.name === defaultName;
                  return (
                    <li key={f.path}>
                      <div
                        className={
                          selected
                            ? 'strm-pick__row is-selected'
                            : 'strm-pick__row'
                        }
                      >
                        <button
                          type="button"
                          className="strm-pick__open"
                          disabled={strmBrowseLoading}
                          onClick={() => void loadStrmBrowse(f.path)}
                        >
                          <span
                            className={
                              isDefault
                                ? 'settings-nav__icon settings-nav__icon--blue'
                                : 'settings-nav__icon settings-nav__icon--orange'
                            }
                            aria-hidden
                          >
                            <Folder size={17} strokeWidth={2.2} />
                          </span>
                          <span className="strm-pick__meta">
                            <span className="strm-pick__name">{f.name}</span>
                            {selected ? (
                              <span className="strm-pick__badge">当前</span>
                            ) : isDefault ? (
                              <span className="strm-pick__badge strm-pick__badge--soft">
                                推荐
                              </span>
                            ) : null}
                          </span>
                          <ChevronRight
                            className="strm-pick__chev"
                            size={16}
                            strokeWidth={2.2}
                            aria-hidden
                          />
                        </button>
                        <button
                          type="button"
                          className="strm-pick__use"
                          disabled={strmBrowseLoading}
                          onClick={() => void pickFolder(f.path)}
                        >
                          选用
                        </button>
                      </div>
                    </li>
                  );
                })
              )}
            </ul>

            <p className="settings-group-label">新建</p>
            <ul className="settings-group makers-manage__rise">
              <li>
                <div className="strm-pick__mkdir">
                  <span
                    className="settings-nav__icon settings-nav__icon--green"
                    aria-hidden
                  >
                    <FolderPlus size={17} strokeWidth={2.2} />
                  </span>
                  <input
                    className="strm-pick__mkdir-input"
                    value={strmNewFolder}
                    disabled={strmBrowseLoading}
                    placeholder="文件夹名称"
                    onChange={(e) => setStrmNewFolder(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void onCreateStrmFolder();
                    }}
                  />
                  <button
                    type="button"
                    className="strm-pick__use"
                    disabled={strmBrowseLoading || !strmNewFolder.trim()}
                    onClick={() => void onCreateStrmFolder()}
                  >
                    创建
                  </button>
                </div>
              </li>
            </ul>

            {hereIsCurrent ? (
              <p className="strm-pick__foot">当前输出目录即此层</p>
            ) : (
              <p className="strm-pick__foot">
                点文件夹进入下级 · 或点「选用」设为输出目录
              </p>
            )}
            <AppMsg allowSelect onDismiss={() => setStrmBrowseMsg('')}>
              {strmBrowseMsg}
            </AppMsg>
          </div>
        </div>
      </AppPush>
    );
  }

  const catalogPushTitle =
    scrapHubOpen
      ? '刮削库'
      : catalogNav?.level === 'prefix'
      ? catalogNav.prefix
      : catalogNav?.level === 'region'
        ? catalogNav.label
        : catalogNav?.level === 'regions'
          ? '七区目录'
          : '片商管理';
  const catalogPushBack = scrapHubOpen
    ? () => {
        setScrapHubOpen(false);
        setMsg('');
      }
    : catalogNav?.level === 'prefix'
      ? catalogPrefixBack
      : catalogNav?.level === 'region'
        ? catalogRegionBack
        : catalogNav?.level === 'regions'
          ? catalogRegionsBack
          : onBack;

  const catalogRegionRows =
    catalogSummary?.regions ||
    MAKER_KIND_TABS.map((t) => ({
      id: t.id,
      label: t.label,
      prefix_count: 0,
      code_count: 0,
    }));

  const localIndexPct =
    typeof localIndexProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, localIndexProgress.percent))
      : localIndexBusy
        ? 0
        : null;
  const localIndexCountLabel =
    typeof localIndexProgress?.done === 'number' &&
    typeof localIndexProgress?.total === 'number' &&
    localIndexProgress.total > 0
      ? `${localIndexProgress.done.toLocaleString()} / ${localIndexProgress.total.toLocaleString()}`
      : '';
  const strmPct =
    typeof strmProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, strmProgress.percent))
      : strmBusy
        ? 0
        : null;
  const strmCountLabel =
    typeof strmProgress?.done === 'number' &&
    typeof strmProgress?.total === 'number' &&
    strmProgress.total > 0
      ? `${strmProgress.done.toLocaleString()} / ${strmProgress.total.toLocaleString()}`
      : '';
  const scrapPct =
    typeof scrapProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, scrapProgress.percent))
      : scrapBusy
        ? 0
        : null;
  const scrapCountLabel =
    typeof scrapProgress?.done === 'number' &&
    typeof scrapProgress?.total === 'number' &&
    scrapProgress.total > 0
      ? `${scrapProgress.done.toLocaleString()} / ${scrapProgress.total.toLocaleString()}`
      : typeof scrapProgress?.done === 'number' && scrapProgress.done > 0
        ? scrapProgress.done.toLocaleString()
        : '';
  const actressOptPct =
    typeof actressOptProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, actressOptProgress.percent))
      : actressOptBusy
        ? 0
        : null;
  const actressOptCountLabel =
    typeof actressOptProgress?.done === 'number' &&
    typeof actressOptProgress?.total === 'number' &&
    actressOptProgress.total > 0
      ? `${actressOptProgress.done.toLocaleString()} / ${actressOptProgress.total.toLocaleString()}`
      : typeof actressOptProgress?.done === 'number' &&
          actressOptProgress.done > 0
        ? actressOptProgress.done.toLocaleString()
        : '';
  const formatQualityDetail = (stats?: ScrapLibraryQualityStats | null) => {
    if (!stats) {
      return {
        total: 0,
        done: 0,
        remain: 0,
        embedTotal: 0,
        shells: 0,
        rows: [] as Array<{ label: string; value: number }>,
      };
    }
    const total = Math.max(0, stats.total ?? 0);
    const remain = Math.max(0, stats.incomplete ?? 0);
    const done = Math.max(0, total - remain);
    const embedTotal = Math.max(0, stats.embedTotal ?? total);
    const shells = Math.max(0, stats.shells ?? 0);
    const c = stats.counts || {};
    const rows: Array<{ label: string; value: number }> = [
      { label: '空壳（仅骨架、待刮削）', value: shells },
      { label: '缺封面', value: c.no_local ?? 0 },
      { label: '缺外链', value: c.no_media ?? 0 },
      { label: '缺女优', value: c.no_actress ?? 0 },
      { label: '缺片商', value: c.no_studio ?? 0 },
      { label: '缺剧情', value: c.no_plot ?? 0 },
      { label: '标题过薄', value: c.thin_title ?? 0 },
    ];
    return { total, done, remain, embedTotal, shells, rows };
  };
  const actressAvatarModeHint =
    actressAvatarMode === 'overwrite'
      ? '覆盖头像 + 回填资料（别名穷举）'
      : '补缺头像 + 回填资料 · 已有头像跳过';
  const qualityDetailModal =
    typeof scanLogModal === 'object' &&
    scanLogModal &&
    'qualityRegion' in scanLogModal
      ? scanLogModal
      : null;
  const qualityDetailStats = qualityDetailModal
    ? scrapQualityByRegion[qualityDetailModal.qualityRegion]
    : undefined;
  const qualityDetail = qualityDetailStats
    ? formatQualityDetail(qualityDetailStats)
    : null;

  const catalogScrollKey = scrapHubOpen
    ? 'mm-scrap-hub'
    : catalogNav?.level === 'prefix'
      ? `mm-prefix-${catalogNav.regionId}-${catalogNav.prefix}`
      : catalogNav?.level === 'region'
        ? `mm-region-${catalogNav.regionId}`
        : catalogNav?.level === 'regions'
          ? 'mm-regions'
          : 'mm-hub';

  return (
    <AppPush
      title={catalogPushTitle}
      onBack={catalogPushBack}
      skipEnterAnimation={Boolean(catalogNav) || scrapHubOpen}
      scrollKey={catalogScrollKey}
    >
      {scrapHubOpen ? (
        <div className="makers-manage makers-manage--detail">
          <p className="settings-group-label">调度</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={() => setEnrichStrategyOpen(true)}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削策略</span>
                  <span className="settings-nav__desc">
                    增量/覆盖 · 头像模式 · 调度 · 七区数据源
                  </span>
                </span>
                <ChevronRight
                  className="settings-nav__chev"
                  size={17}
                  strokeWidth={2.4}
                  aria-hidden
                />
              </button>
            </li>
          </ul>

          <p className="settings-group-label">刮削产物</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削目录</span>
                  <span className="settings-nav__desc allow-select">
                    {scrapRoot
                      ? `media/${scrapRoot} · NFO / 封面`
                      : 'media/scrap-library · NFO / 封面'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={strmBusy || localIndexBusy || scrapBusy || enrichBusy}
                  onClick={() => void openScrapBrowse()}
                >
                  选择
                </button>
              </div>
            </li>
          </ul>

          <p className="settings-group-label">刮削分区</p>
          <ul className="settings-group makers-manage__rise" aria-label="七区刮削开关">
            {(enrichRegions.length
              ? enrichRegions
              : MAKER_KIND_TABS.map((t) => ({
                  id: t.id,
                  label: t.label,
                  enabled: false,
                }))
            ).map((region) => {
              const active =
                enrichBusy && enrichCurrentRegion === region.id;
              const cp = enrichCheckpoints[region.id];
              const prog = active
                ? enrichProgress
                : enrichProgressByRegion[region.id] || null;
              // 暂停态也用队列表角标（成功/失败），勿只信本轮 checkpoint.ok=15
              const qc =
                (active || Boolean(cp)) && enrichQueueCounts
                  ? enrichQueueCounts
                  : null;
              const okN = (() => {
                if (qc)
                  return Number(qc.done || 0) + Number(qc.soft || 0);
                if (typeof prog?.ok === 'number') return prog.ok;
                if (typeof cp?.ok === 'number') return cp.ok;
                return null;
              })();
              const failN = (() => {
                if (qc) return Number(qc.fail || 0);
                if (typeof prog?.failed === 'number') return prog.failed;
                if (typeof cp?.failed === 'number') return cp.failed;
                return null;
              })();
              const remainingN = (() => {
                const libInc = Number(
                  enrichLibrary[region.id]?.incomplete || 0,
                );
                if (qc) {
                  return Math.max(
                    Number(qc.pending || 0) + Number(qc.running || 0),
                    libInc,
                  );
                }
                if (!active && typeof cp?.remaining === 'number') {
                  return Math.max(cp.remaining, libInc);
                }
                const tot =
                  typeof prog?.total === 'number' && prog.total > 0
                    ? prog.total
                    : typeof cp?.total === 'number' && cp.total > 0
                      ? cp.total
                      : Number(enrichLibrary[region.id]?.total || 0) || null;
                const fin =
                  okN != null || failN != null
                    ? Number(okN || 0) + Number(failN || 0)
                    : typeof prog?.done === 'number'
                      ? prog.done
                      : null;
                if (tot != null && fin != null) {
                  return Math.max(0, tot - fin, libInc);
                }
                return libInc > 0 ? libInc : null;
              })();
              // 进度%：优先库内已齐比例；避免队列表样例把进度撑到 50%+
              const pct = (() => {
                const lib = enrichLibrary[region.id];
                if (
                  lib &&
                  typeof lib.percent === 'number' &&
                  Number(lib.total || 0) > 0
                ) {
                  return Math.max(0, Math.min(100, Math.round(lib.percent)));
                }
                const rem = remainingN;
                const complete = Number(lib?.complete || 0);
                if (rem != null && (complete > 0 || rem > 0)) {
                  const tot = complete + rem;
                  if (tot > 0) {
                    return Math.max(
                      0,
                      Math.min(100, Math.round((100 * complete) / tot)),
                    );
                  }
                }
                const fin =
                  okN != null || failN != null
                    ? Number(okN || 0) + Number(failN || 0)
                    : null;
                if (fin != null && rem != null) {
                  const tot = fin + rem;
                  if (tot > 0) {
                    return Math.max(
                      0,
                      Math.min(100, Math.round((100 * fin) / tot)),
                    );
                  }
                  return 0;
                }
                if (
                  typeof prog?.total === 'number' &&
                  prog.total > 0 &&
                  typeof prog?.done === 'number'
                ) {
                  return Math.max(
                    0,
                    Math.min(
                      100,
                      Math.round((100 * prog.done) / prog.total),
                    ),
                  );
                }
                return active ? 0 : null;
              })();
              const totalN =
                okN != null || failN != null || remainingN != null
                  ? Number(okN || 0) +
                    Number(failN || 0) +
                    Number(remainingN || 0)
                  : null;
              const queueStage = prog?.stage === 'queue';
              const remainLabel =
                enrichMode === 'incremental' || enrichMode === 'refresh_weak'
                  ? remainingN != null && !queueStage
                    ? `未处理 ${remainingN.toLocaleString()}`
                    : ''
                  : totalN != null
                    ? `总数 ${totalN.toLocaleString()}`
                    : '';
              const showProgress =
                active ||
                Boolean(cp) ||
                (prog != null &&
                  (remainLabel || okN != null || failN != null));
              const finN = Number(okN || 0) + Number(failN || 0);
              const speedState =
                enrichSpeedRef.current?.regionId === region.id
                  ? enrichSpeedRef.current
                  : null;
              // 一旦真正开始补齐（有完成数，或 stage=enrich），锁住「补齐中」，避免 queue 心跳闪回筛选
              if (
                active &&
                speedState &&
                (finN > 0 ||
                  prog?.stage === 'enrich' ||
                  prog?.stage === 'disk' ||
                  prog?.stage === 'write')
              ) {
                speedState.lockedEnrich = true;
              }
              const stickEnrich = Boolean(active && speedState?.lockedEnrich);
              let stageLabel = active
                ? queueStage && !stickEnrich
                  ? String(prog?.label || '').trim() ||
                    (enrichMode === 'overwrite' ? '排队' : '筛选')
                  : prog?.stage === 'done'
                    ? '完成'
                    : '补齐中'
                : cp
                  ? '已暂停'
                  : prog?.stage === 'done'
                    ? '已完成'
                    : '进度';
              const rateLabel = (() => {
                if (!active) return '';
                if (stageLabel !== '补齐中') {
                  // 短暂非补齐阶段仍保留已显示的速率，避免「· 25部/分」闪没
                  return stickEnrich && speedState?.rateText
                    ? speedState.rateText
                    : '';
                }
                const sp = speedState;
                if (!sp) return '';
                const mins = (Date.now() - sp.t0) / 60000;
                if (mins < 0.08) return sp.rateText || '';
                const instant = Math.max(0, finN - sp.fin0) / mins;
                if (instant < 0.05 && mins < 0.6 && sp.rateEma == null) {
                  return sp.rateText || '';
                }
                // EMA 平滑，避免部/分来回跳
                const next =
                  sp.rateEma == null
                    ? instant
                    : sp.rateEma * 0.72 + instant * 0.28;
                sp.rateEma = next;
                // 整数档位滞后：变化不足 1 不改展示数字
                const prevShown = Number.parseFloat(sp.rateText) || 0;
                let show = next;
                if (sp.rateText) {
                  if (Math.abs(next - prevShown) < 1.0) show = prevShown;
                  else show = Math.round(next);
                } else {
                  show = next >= 10 ? Math.round(next) : next;
                }
                const text =
                  show >= 10 || Number.isInteger(show)
                    ? `${Math.round(show)} 部/分`
                    : `${show.toFixed(1).replace(/\.0$/, '')} 部/分`;
                sp.rateText = text;
                return text;
              })();

              return (
              <li key={region.id}>
                <div className="settings-nav makers-manage__status">
                  <span className="makers-manage__status-lead">
                    <Switch
                      checked={region.enabled}
                      disabled={(() => {
                        // 当前正在跑的分区必须可关（暂停）；其它忙态才锁死
                        const activeHere =
                          enrichBusy && enrichCurrentRegion === region.id;
                        if (activeHere) return false;
                        return (
                          enrichRegionBusy ||
                          strmBusy ||
                          localIndexBusy ||
                          catalogBusy ||
                          scrapBusy ||
                          enrichBusy
                        );
                      })()}
                      onCheckedChange={(v) =>
                        void toggleEnrichRegion(region.id, Boolean(v))
                      }
                    />
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{region.label}</span>
                    </span>
                  </span>
                  <span className="makers-manage__status-actions">
                    <button
                      type="button"
                      className="makers-manage__probe-btn"
                      onClick={() => {
                        setScrapQualityByRegion((prev) => {
                          const next = { ...prev };
                          delete next[region.id];
                          return next;
                        });
                        setScanLogModal({
                          qualityRegion: region.id,
                          label: region.label,
                        });
                        setGateSummary('');
                        void refreshScrapQuality([region.id]);
                      }}
                    >
                      详情
                    </button>
                    <button
                      type="button"
                      className="makers-manage__probe-btn"
                      onClick={() => {
                        const activeHere =
                          enrichBusy && enrichCurrentRegion === region.id;
                        const prog = activeHere
                          ? enrichProgress
                          : enrichProgressByRegion[region.id] || null;
                        const regionLog =
                          enrichRegionLogs[region.id] || [];
                        const seed: ScrapLibraryEnrichJobStatus = {
                          running: Boolean(activeHere),
                          phase: activeHere
                            ? enrichPhase || prog?.label || '补齐中…'
                            : enrichCheckpoints[region.id]
                              ? 'paused'
                              : '',
                          progress: prog,
                          log: regionLog.length
                            ? regionLog.slice(-40)
                            : enrichLog.slice(-40),
                          regionLogs: enrichRegionLogs,
                          currentRegion: enrichCurrentRegion,
                          checkpoints: enrichCheckpoints,
                          paused: Boolean(enrichCheckpoints[region.id]),
                          queue: [],
                          current: null,
                          result: null,
                        };
                        setEnrichLive({
                          regionId: region.id,
                          label: region.label,
                          initialStatus: seed,
                          initialLogs: regionLog.slice(-200),
                        });
                      }}
                    >
                      日志
                    </button>
                  </span>
                </div>
                {showProgress ? (
                  <div
                    className="makers-manage__scan-progress"
                    aria-live="polite"
                  >
                    {active || pct != null ? (
                      <div
                        className="makers-manage__scan-bar"
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={pct != null ? Math.round(pct) : 0}
                        aria-label={`${region.label}刮削进度`}
                      >
                        <span
                          style={{
                            width: `${pct != null ? pct : 0}%`,
                          }}
                        />
                      </div>
                    ) : null}
                    <div className="makers-manage__scan-meta">
                      <span className="makers-manage__scan-meta-main">
                        <span>
                          {stageLabel}
                          {rateLabel ? ` · ${rateLabel}` : ''}
                        </span>
                      </span>
                      {pct != null ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(pct)}%`}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </li>
              );
            })}
          </ul>

          <p className="settings-group-label">向量入库</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">同步向量数据库</span>
                  <span className="settings-nav__desc">
                    {scrapBusy
                      ? scrapPhase || '同步中…'
                      : '本地 NFO→向量 · 增量跳过已有 · 全量重写（磁盘无则删库）'}
                  </span>
                </span>
                <span className="makers-manage__status-actions">
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onScrapEmbedSync(false)}
                  >
                    {scrapBusy
                      ? scrapPct != null
                        ? `${Math.round(scrapPct)}%`
                        : '同步中…'
                      : '增量同步'}
                  </button>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onScrapEmbedSync(true)}
                  >
                    {scrapBusy ? '…' : '全量同步'}
                  </button>
                </span>
              </div>
              {scrapBusy || scrapProgress || scrapLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {scrapBusy || scrapProgress ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={scrapPct != null ? Math.round(scrapPct) : 0}
                      aria-label="刮削库向量同步进度"
                    >
                      <span
                        style={{
                          width: `${scrapPct != null ? scrapPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {scrapBusy || scrapProgress
                        ? scrapProgress?.stage === 'embed'
                          ? '写入'
                          : scrapProgress?.stage === 'scan'
                            ? '扫描'
                            : scrapProgress?.stage === 'diff'
                              ? '比对'
                              : scrapProgress?.stage === 'covers'
                                ? '封面'
                                : scrapProgress?.stage === 'done'
                                  ? '完成'
                                  : '准备'
                        : '已完成'}
                      {scrapCountLabel ? ` · ${scrapCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {scrapPct != null && (scrapBusy || scrapProgress) ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(scrapPct)}%`}
                        </span>
                      ) : null}
                      {scrapLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('scrap')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              ) : null}
            </li>
          </ul>

          <p className="settings-group-label">女优</p>
          <ul className="settings-group makers-manage__rise" aria-label="女优元数据与头像">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">
                    刮削女优元数据和头像
                  </span>
                  <span className="settings-nav__desc">
                    {actressAvatarBusy
                      ? actressAvatarPhase || '刮削中…'
                      : '从向量库取女优名 · 头像/资料落本地与 Meta · 增量跳过已有 · 全量覆盖'}
                  </span>
                </span>
                <span className="makers-manage__status-actions">
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onActressAvatarScrape(false)}
                  >
                    {actressAvatarBusy
                      ? typeof actressAvatarProgress?.percent === 'number'
                        ? `${Math.round(actressAvatarProgress.percent)}%`
                        : '刮削中…'
                      : '增量刮削'}
                  </button>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onActressAvatarScrape(true)}
                  >
                    {actressAvatarBusy ? '…' : '全量覆盖'}
                  </button>
                </span>
              </div>
              {actressAvatarBusy ||
              actressAvatarProgress ||
              actressAvatarLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress makers-manage__scan-progress--meta-first"
                  aria-live="polite"
                >
                  <div className="makers-manage__scan-meta">
                    <span>
                      {actressAvatarBusy || actressAvatarProgress
                        ? actressAvatarProgress?.stage === 'done'
                          ? '完成'
                          : actressAvatarProgress?.stage === 'download'
                            ? '下载头像'
                            : actressAvatarProgress?.stage === 'bio'
                              ? '补资料'
                              : actressAvatarProgress?.stage === 'embed'
                                ? '写向量'
                                : actressAvatarProgress?.stage === 'scan'
                                  ? '索引'
                                  : '准备'
                        : '已完成'}
                      {typeof actressAvatarProgress?.done === 'number' &&
                      typeof actressAvatarProgress?.total === 'number' &&
                      actressAvatarProgress.total > 0
                        ? ` · ${actressAvatarProgress.done.toLocaleString()} / ${actressAvatarProgress.total.toLocaleString()}`
                        : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {actressAvatarLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('actressAvatar')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                  {actressAvatarBusy || actressAvatarProgress ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={
                        typeof actressAvatarProgress?.percent === 'number'
                          ? Math.round(actressAvatarProgress.percent)
                          : 0
                      }
                      aria-label="女优刮削进度"
                    >
                      <span
                        style={{
                          width: `${
                            typeof actressAvatarProgress?.percent === 'number'
                              ? actressAvatarProgress.percent
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">
                    对齐向量库女优名
                  </span>
                  <span className="settings-nav__desc">
                    {actressOptBusy
                      ? actressOptPhase || '对齐中…'
                      : '只改标题「女优：」标准名并重嵌 · 不含头像/资料 · 增量跳过已对齐'}
                  </span>
                </span>
                <span className="makers-manage__status-actions">
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onActressOptimize(false)}
                  >
                    {actressOptBusy
                      ? actressOptPct != null
                        ? `${Math.round(actressOptPct)}%`
                        : '对齐中…'
                      : '增量对齐'}
                  </button>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                      strmBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      scrapBusy ||
                      enrichBusy ||
                      actressOptBusy ||
                      actressAvatarBusy
                    }
                    onClick={() => void onActressOptimize(true)}
                  >
                    {actressOptBusy ? '…' : '全量重嵌'}
                  </button>
                </span>
              </div>
              {actressOptBusy ||
              actressOptProgress ||
              actressOptLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {actressOptBusy || actressOptProgress ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={
                        actressOptPct != null ? Math.round(actressOptPct) : 0
                      }
                      aria-label="女优向量同步进度"
                    >
                      <span
                        style={{
                          width: `${actressOptPct != null ? actressOptPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {actressOptBusy || actressOptProgress
                        ? actressOptProgress?.stage === 'done'
                          ? '完成'
                          : actressOptProgress?.stage === 'embed'
                            ? '重嵌'
                            : actressOptProgress?.stage === 'diff'
                              ? '比对'
                              : actressOptProgress?.stage === 'scan'
                                ? '扫描'
                                : '准备'
                        : '已完成'}
                      {actressOptCountLabel ? ` · ${actressOptCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {actressOptLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('actress')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              ) : null}
            </li>
          </ul>

          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      ) : catalogNav?.level === 'prefix' ? (
        <div className="makers-manage makers-manage--detail">
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">厂牌</span>
                <span className="settings-kv__val allow-select">
                  {(catalogDetail?.maker || '')
                    .split('/')
                    .map((s) => s.trim())
                    .filter(Boolean)
                    .slice(0, 2)
                    .join(' / ') || (catalogBusy ? '…' : '—')}
                </span>
              </div>
            </li>
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">番号</span>
                <span className="settings-kv__val">
                  {catalogBusy
                    ? '…'
                    : `${catalogDetail?.code_count ?? 0} 条`}
                </span>
              </div>
            </li>
          </ul>
          <p className="settings-group-label">真实番号</p>
          {(catalogDetail?.codes || []).length ? (
            <>
              <ul className="settings-group makers-manage__codes">
                {(catalogDetail?.codes || []).map((code) => (
                  <li key={code}>
                    <div className="settings-kv">
                      <span className="settings-kv__key allow-select makers-manage__code">
                        {code}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {codePages > 1 ? (
                <div className="media-chart__pager">
                  <button
                    type="button"
                    className="media-chart__page-btn"
                    disabled={catalogBusy || catalogCodePage <= 1}
                    onClick={() => {
                      if (!catalogNav || catalogNav.level !== 'prefix') return;
                      void loadCatalogCodes(
                        catalogNav.regionId,
                        catalogNav.prefix,
                        catalogCodePage - 1,
                      );
                    }}
                  >
                    上一页
                  </button>
                  <span className="media-chart__page-meta">
                    {catalogCodePage} / {codePages}
                  </span>
                  <button
                    type="button"
                    className="media-chart__page-btn"
                    disabled={catalogBusy || catalogCodePage >= codePages}
                    onClick={() => {
                      if (!catalogNav || catalogNav.level !== 'prefix') return;
                      void loadCatalogCodes(
                        catalogNav.regionId,
                        catalogNav.prefix,
                        catalogCodePage + 1,
                      );
                    }}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <p className="makers-manage__sites-empty">
              {catalogBusy ? '加载中…' : '暂无已验证番号'}
            </p>
          )}
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      ) : catalogNav?.level === 'region' ? (
        <div className="makers-manage makers-manage--detail">
          <p className="settings-group-label">前缀</p>
          {catalogPrefixes.length ? (
            <ul className="settings-group">
              {catalogPrefixes.map((row) => (
                <li key={row.prefix}>
                  <button
                    type="button"
                    className="settings-nav makers-manage__catalog-row"
                    disabled={catalogBusy}
                    onClick={() =>
                      void openCatalogPrefix(
                        catalogNav.regionId,
                        catalogNav.label,
                        row.prefix,
                      )
                    }
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title allow-select">
                        {row.prefix}
                      </span>
                      <span className="settings-nav__desc">
                        {row.maker
                          ? `${row.maker.split('/').map((s) => s.trim()).filter(Boolean).slice(0, 2).join(' / ')} · ${row.code_count} 番号`
                          : `${row.code_count} 番号`}
                      </span>
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
          ) : (
            <p className="makers-manage__sites-empty">
              {catalogBusy ? '加载中…' : '暂无前缀'}
            </p>
          )}
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      ) : catalogNav?.level === 'regions' ? (
        <div className="makers-manage makers-manage--detail">
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">双库扫描</span>
                  <span className="settings-nav__desc">
                    {localIndexBusy
                      ? localIndexPhase || '扫描中…'
                      : 'Sehua · Bitmagnet 少补多删 · 同步番号骨架进向量供刮削'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={localIndexBusy || avwikiBusy || catalogBusy || strmBusy || scrapBusy}
                  onClick={() => void onLocalIndexScan()}
                >
                  {localIndexBusy
                    ? localIndexPct != null
                      ? `${Math.round(localIndexPct)}%`
                      : '扫描中…'
                    : '开始扫描'}
                </button>
              </div>
              {localIndexBusy || localIndexLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {localIndexBusy || localIndexProgress ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={
                        localIndexPct != null ? Math.round(localIndexPct) : 0
                      }
                      aria-label="双库扫描进度"
                    >
                      <span
                        style={{
                          width: `${localIndexPct != null ? localIndexPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {localIndexBusy || localIndexProgress
                        ? localIndexProgress?.stage === 'sehua'
                          ? '色花堂'
                          : localIndexProgress?.stage === 'bitmagnet'
                            ? 'Bitmagnet'
                            : localIndexProgress?.stage === 'write'
                              ? '写回'
                              : localIndexProgress?.stage === 'skeleton'
                                ? '番号骨架'
                              : localIndexProgress?.stage === 'done'
                                ? '完成'
                                : '准备'
                        : '已完成'}
                      {localIndexCountLabel ? ` · ${localIndexCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {localIndexPct != null &&
                      (localIndexBusy || localIndexProgress) ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(localIndexPct)}%`}
                        </span>
                      ) : null}
                      {localIndexLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('local')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              ) : null}
            </li>
          </ul>

          <p className="settings-group-label">本地 STRM</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">输出目录</span>
                  <span className="settings-nav__desc allow-select">
                    {strmRoot
                      ? `media/${strmRoot}`
                      : 'media/strm-library（默认）'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={strmBusy || localIndexBusy || scrapBusy}
                  onClick={() => void openStrmBrowse()}
                >
                  选择
                </button>
              </div>
            </li>
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">同步本地文件夹</span>
                  <span className="settings-nav__desc">
                    {strmBusy
                      ? strmPhase || '同步中…'
                      : '按七区少补多删 .strm · 同步番号骨架进向量供刮削'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={strmBusy || localIndexBusy || catalogBusy || scrapBusy}
                  onClick={() => void onStrmSync()}
                >
                  {strmBusy
                    ? strmPct != null
                      ? `${Math.round(strmPct)}%`
                      : '同步中…'
                    : '开始同步'}
                </button>
              </div>
              {strmBusy || strmLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {strmBusy ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={strmPct != null ? Math.round(strmPct) : 0}
                      aria-label="STRM 同步进度"
                    >
                      <span
                        style={{
                          width: `${strmPct != null ? strmPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {strmBusy
                        ? strmProgress?.stage === 'write'
                          ? '写入'
                          : strmProgress?.stage === 'skeleton'
                            ? '番号骨架'
                          : strmProgress?.stage === 'done'
                            ? '完成'
                            : '准备'
                        : '已完成'}
                      {strmCountLabel ? ` · ${strmCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {strmPct != null && strmBusy ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(strmPct)}%`}
                        </span>
                      ) : null}
                      {strmLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('strm')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              ) : null}
            </li>
          </ul>

          <ul className="settings-group" aria-label="七区前缀番号">
            {catalogRegionRows.map((reg) => (
              <li key={reg.id}>
                <button
                  type="button"
                  className="settings-nav makers-manage__catalog-row"
                  disabled={catalogBusy || localIndexBusy || strmBusy}
                  onClick={() => void openCatalogRegion(reg.id, reg.label)}
                >
                <span className="settings-nav__main">
                    <span className="settings-nav__title">{reg.label}</span>
                  <span className="settings-nav__desc">
                      {`${reg.prefix_count} 前缀 · ${reg.code_count} 番号`}
                  </span>
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

          <p className="settings-group-label">维护</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">AVWikiDB 厂牌映射</span>
                  <span className="settings-nav__desc">
                    {avwikiBusy
                      ? avwikiPhase || '同步中…'
                      : '回填日文厂牌 · 按已有厂牌补缺前缀（日本有码）'}
                  </span>
                </span>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={
                    avwikiBusy ||
                      localIndexBusy ||
                      catalogBusy ||
                      strmBusy ||
                    scrapBusy
                  }
                  onClick={() => void onAvwikiSync()}
                >
                  {avwikiBusy ? '同步中…' : '开始同步'}
                  </button>
              </div>
              {avwikiBusy || avwikiLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  <div className="makers-manage__scan-meta">
                    <span className="allow-select">
                      {avwikiBusy
                        ? avwikiPhase || '同步中…'
                        : '已完成'}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {avwikiLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => setScanLogModal('avwikidb')}
                        >
                          日志
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              ) : null}
            </li>
          </ul>
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      ) : (
        <div className="makers-manage">
          <p className="settings-group-label">前缀目录</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={openCatalogRegions}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">七区目录</span>
                  <span className="settings-nav__desc">
                    {catalogSummary
                      ? `${catalogSummary.prefix_total} 前缀 · ${catalogSummary.code_total} 番号`
                      : '前缀与真实番号'}
                  </span>
                </span>
                <ChevronRight
                  className="settings-nav__chev"
                  size={17}
                  strokeWidth={2.4}
                  aria-hidden
                />
              </button>
            </li>
          </ul>

          <p className="settings-group-label">采集</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={() => setSourcesOpen(true)}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">数据源</span>
                  <span className="settings-nav__desc">
                    MDCS 全站目录 · 启用 / 地址 / 测链
                  </span>
                </span>
                <ChevronRight
                  className="settings-nav__chev"
                  size={17}
                  strokeWidth={2.4}
                  aria-hidden
                />
              </button>
            </li>
          </ul>

          <p className="settings-group-label">刮削</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={() => {
                  setMsg('');
                  setScrapHubOpen(true);
                }}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削库</span>
                  <span className="settings-nav__desc">
                    {scrapBusy
                      ? scrapPhase || '向量同步中…'
                      : enrichBusy
                        ? enrichPhase || '刮削补齐中…'
                        : actressAvatarBusy
                          ? actressAvatarPhase || '女优刮削中…'
                          : '产物目录 · 刮削补齐 · 向量入库'}
                  </span>
                </span>
                <ChevronRight
                  className="settings-nav__chev"
                  size={17}
                  strokeWidth={2.4}
                  aria-hidden
                />
              </button>
            </li>
          </ul>

          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      )}

      <AppCenterModal
        open={scanLogModal != null}
        title={
          qualityDetailModal
            ? `${qualityDetailModal.label} · 缺口详情`
            : scanLogModal === 'strm'
            ? 'STRM 同步日志'
            : scanLogModal === 'scrap'
              ? '刮削库同步日志'
                : scanLogModal === 'actress'
                  ? '女优同步向量日志'
                  : scanLogModal === 'actressAvatar'
                    ? '女优刮削日志'
              : scanLogModal === 'enrich'
                    ? '刮削补齐日志'
                : scanLogModal === 'avwikidb'
                  ? 'AVWikiDB 厂牌映射日志'
                  : '双库扫描日志'
        }
        onClose={() => setScanLogModal(null)}
        cardClassName="makers-manage__log-modal"
      >
        {qualityDetailModal ? (
          qualityDetail ? (
          <div className="makers-manage__quality-detail allow-select">
            <ul className="settings-group">
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">条目总数</span>
                  <span className="settings-kv__val">
                    {qualityDetail.total.toLocaleString()}
                  </span>
                </div>
                <div className="settings-kv">
                  <span className="settings-kv__key">向量库 / 空壳</span>
                  <span className="settings-kv__val">
                    {qualityDetail.embedTotal.toLocaleString()} /{' '}
                    {qualityDetail.shells.toLocaleString()}
                  </span>
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">已齐</span>
                  <span className="settings-kv__val">
                    {qualityDetail.done.toLocaleString()}
                  </span>
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">还剩（任一缺口）</span>
                  <span className="settings-kv__val">
                    {qualityDetail.remain.toLocaleString()}
                  </span>
                </div>
              </li>
            </ul>
            <p className="settings-group-label">分项缺口</p>
            <ul className="settings-group">
              {qualityDetail.rows.map((row) => (
                <li key={row.label}>
                  <div className="settings-kv">
                    <span className="settings-kv__key">{row.label}</span>
                    <span className="settings-kv__val">
                      {row.value.toLocaleString()}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <p className="settings-group-label settings-group-label--spaced">
              质量门禁抽检
            </p>
            <ul className="settings-group">
              <li>
                <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
                  <span className="settings-nav__main">
                    <span className="settings-kv__key">抽样检查</span>
                    <span className="settings-nav__desc">
                      {gateSummary ||
                        '从缺口队列抽 12 条跑 G34 门禁（标题/海报/剧情）'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={gateBusy}
                    onClick={() => {
                      void (async () => {
                        if (!qualityDetailModal) return;
                        setGateBusy(true);
                        setGateSummary('抽检中…');
                        try {
                          const page = await getScrapLibraryQualityItems({
                            region: qualityDetailModal.qualityRegion,
                            kind: 'thin_title',
                            limit: 12,
                          });
                          const items = page.items || [];
                          if (!items.length) {
                            setGateSummary('缺口队列为空，跳过抽检');
                            return;
                          }
                          let pass = 0;
                          let fail = 0;
                          const samples: string[] = [];
                          for (const it of items) {
                            try {
                              const g = await getScrapLibraryQualityGate({
                                itemId: String(it.itemId || ''),
                                code: String(it.code || ''),
                                relPath: String(it.relPath || ''),
                              });
                              if (g.ok) pass += 1;
                              else {
                                fail += 1;
                                const reason = (g.hardFail || g.soft || [])
                                  .slice(0, 2)
                                  .join('/');
                                if (samples.length < 3 && it.code) {
                                  samples.push(
                                    `${it.code}${reason ? ` (${reason})` : ''}`,
                                  );
                                }
                              }
                            } catch {
                              fail += 1;
                            }
                          }
                          setGateSummary(
                            `抽检 ${items.length}：通过 ${pass} · 未过 ${fail}` +
                              (samples.length
                                ? ` · 例 ${samples.join('、')}`
                                : ''),
                          );
                        } catch (e) {
                          setGateSummary(
                            e instanceof Error ? e.message : '抽检失败',
                          );
                        } finally {
                          setGateBusy(false);
                        }
                      })();
                    }}
                  >
                    {gateBusy ? '…' : '抽检'}
                  </button>
                </div>
              </li>
            </ul>
          </div>
          ) : (
            <p className="makers-manage__log-empty">统计加载中…</p>
          )
        ) : (
        <AutoscrollLogList
          className="makers-manage__scan-log-modal allow-select"
          active={scanLogModal != null && !qualityDetailModal}
          lines={
            scanLogModal === 'strm'
              ? strmLog
              : scanLogModal === 'scrap'
                ? scrapLog
                : scanLogModal === 'actress'
                  ? actressOptLog
                  : scanLogModal === 'actressAvatar'
                    ? actressAvatarLog
                    : scanLogModal === 'enrich'
                      ? enrichLog
                      : scanLogModal === 'avwikidb'
                        ? avwikiLog
                        : localIndexLog
          }
        />
        )}
      </AppCenterModal>
    </AppPush>
  );
}
