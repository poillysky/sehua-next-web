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
  pauseScrapLibraryEnrich,
  stopScrapLibraryEnrich,
  getScrapLibraryQuality,
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
    fail: number;
  } | null>(null);
  const [enrichMode, setEnrichMode] = useState<'incremental' | 'overwrite'>(
    'incremental',
  );
  const [enrichRegions, setEnrichRegions] = useState<
    Array<{ id: string; label: string; enabled: boolean }>
  >([]);
  const [enrichRegionBusy, setEnrichRegionBusy] = useState(false);
  const enrichPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const enrichPollingRef = useRef(false);
  /** 用户点了停止：禁止轮询把开关又拨开 */
  const enrichStopRequestedRef = useRef(false);
  /** 本轮补齐速度：按 (成功+失败) 增量 / 分钟 */
  const enrichSpeedRef = useRef<{
    regionId: string;
    t0: number;
    fin0: number;
  } | null>(null);
  const [scanLogModal, setScanLogModal] = useState<ScanLogModal>(null);

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
        } else if (st.result && !st.error) {
          // 刚完成：保留结果文案，进度条可空
          const written = st.result.written ?? 0;
          const total = st.result.total ?? 0;
          setScrapLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          setMsg(`刮削库已写入元库 · ${written}/${total}`);
        }
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
          setEnrichMode(
            strat.fillMode === 'overwrite' ? 'overwrite' : 'incremental',
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
          setEnrichMode(
            strat.fillMode === 'overwrite' ? 'overwrite' : 'incremental',
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
      if (enrichPollRef.current) clearTimeout(enrichPollRef.current);
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

  async function pollScrapEmbedUntilDone() {
    if (scrapPollingRef.current) return;
    scrapPollingRef.current = true;
    try {
      for (;;) {
        const st = await getScrapLibraryEmbedStatus();
        setScrapBusy(st.running);
        setScrapPhase(st.phase || (st.running ? '同步中…' : ''));
        setScrapProgress(st.progress || null);
        setScrapLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('刮削库向量同步失败', 'warn');
            setScrapBusy(false);
            return;
          }
          if (st.result) {
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

  async function onScrapEmbedSync() {
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
    setScrapPhase('starting');
    setScrapProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setScrapLog([]);
    onStatus('刮削库向量同步中…', 'mute');
    try {
      await startScrapLibraryEmbed({ root });
      await pollScrapEmbedUntilDone();
    } catch (e) {
      setScrapBusy(false);
      setScrapPhase('');
      setScrapProgress(null);
      const text = e instanceof Error ? e.message : '启动刮削库同步失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollActressOptUntilDone() {
    if (actressOptPollingRef.current) return;
    actressOptPollingRef.current = true;
    try {
      for (;;) {
        const st = await getScrapActressOptimizeStatus();
        setActressOptBusy(st.running);
        setActressOptPhase(st.phase || (st.running ? '优化中…' : ''));
        setActressOptProgress(st.progress || null);
        setActressOptLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('女优元数据优化失败', 'warn');
            setActressOptBusy(false);
            return;
          }
          if (st.result) {
            const updated = st.result.updated ?? 0;
            const total = st.result.total ?? 0;
            const maps = st.result.maps?.count ?? 0;
            setMsg(
              `女优元数据已优化 · 更新 ${updated}/${total} · 映射表 ${maps} 条`,
            );
            onStatus('女优元数据已优化', 'ok');
          }
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

  async function onActressOptimize() {
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
    setActressOptPhase('starting');
    setActressOptProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setActressOptLog([]);
    onStatus('女优元数据优化中…', 'mute');
    try {
      await startScrapActressOptimize({ reembed: true });
      await pollActressOptUntilDone();
    } catch (e) {
      setActressOptBusy(false);
      setActressOptPhase('');
      setActressOptProgress(null);
      const text = e instanceof Error ? e.message : '启动女优优化失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollActressAvatarUntilDone() {
    if (actressAvatarPollingRef.current) return;
    actressAvatarPollingRef.current = true;
    try {
      for (;;) {
        const st: ScrapActressAvatarJobStatus =
          await getScrapActressAvatarStatus();
        setActressAvatarBusy(st.running);
        setActressAvatarPhase(st.phase || (st.running ? '刮削中…' : ''));
        setActressAvatarProgress(st.progress || null);
        setActressAvatarLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('女优头像刮削失败', 'warn');
            setActressAvatarBusy(false);
            return;
          }
          if (st.result) {
            const downloaded = st.result.downloaded ?? 0;
            const skipped = st.result.skipped ?? 0;
            const missed = st.result.missed ?? 0;
            const total = st.result.total ?? 0;
            const gf = st.result.downloadedGfriends ?? 0;
            const jb = st.result.downloadedJavbus ?? 0;
            const srcHint =
              gf || jb ? `（GFriends ${gf} · JavBus ${jb}）` : '';
            setMsg(
              `女优头像已刮削 · 新下 ${downloaded}${srcHint} · 跳过 ${skipped} · 未命中 ${missed} / 共 ${total}`,
            );
            onStatus('女优头像已刮削', 'ok');
          }
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

  async function onActressAvatarScrape() {
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
    setActressAvatarPhase('starting');
    setActressAvatarProgress({
      stage: 'prepare',
      percent: 0,
      label: 'starting',
    });
    setActressAvatarLog([]);
    onStatus(
      actressAvatarMode === 'overwrite'
        ? '女优头像覆盖刮削中…'
        : '女优头像增量刮削中…',
      'mute',
    );
    try {
      await startScrapActressAvatar({
        force: actressAvatarMode === 'overwrite',
      });
      await pollActressAvatarUntilDone();
    } catch (e) {
      setActressAvatarBusy(false);
      setActressAvatarPhase('');
      setActressAvatarProgress(null);
      const text = e instanceof Error ? e.message : '启动女优头像刮削失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function pollEnrichUntilDone() {
    if (enrichPollingRef.current) return;
    enrichPollingRef.current = true;
    try {
      for (;;) {
        const st = await getScrapLibraryEnrichStatus();
        setEnrichBusy(st.running);
        setEnrichPhase(st.phase || (st.running ? '补齐中…' : ''));
        setEnrichProgress(st.progress || null);
        setEnrichLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        setEnrichRegionLogs(
          st.regionLogs && typeof st.regionLogs === 'object' ? st.regionLogs : {},
        );
        setEnrichCurrentRegion(String(st.currentRegion || ''));
        setEnrichCheckpoints(
          st.checkpoints && typeof st.checkpoints === 'object'
            ? st.checkpoints
            : {},
        );
        setEnrichQueueCounts((prev) => {
          if (st.running && st.queueCounts) {
            return {
              pending: Number(st.queueCounts.pending || 0),
              running: Number(st.queueCounts.running || 0),
              done: Number(st.queueCounts.done || 0),
              fail: Number(st.queueCounts.fail || 0),
            };
          }
          // 运行中偶发缺字段时保留上次计数，避免进度条闪跳
          if (st.running && prev) return prev;
          return null;
        });
        if (st.running) {
          const speedRid = String(st.currentRegion || '').trim() || '_';
          const fin =
            Number(st.queueCounts?.done || 0) +
            Number(st.queueCounts?.fail || 0);
          const prevSp = enrichSpeedRef.current;
          if (!prevSp || prevSp.regionId !== speedRid) {
            enrichSpeedRef.current = {
              regionId: speedRid,
              t0: Date.now(),
              fin0: fin,
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
        // 运行中对应分区开关保持开（停止请求后不再拨开）
        if (
          st.running &&
          rid &&
          !enrichStopRequestedRef.current &&
          st.halt !== 'stop'
        ) {
          setEnrichRegions((prev) =>
            prev.map((r) => ({
              ...r,
              enabled: r.id === rid,
            })),
          );
        }
        if (!st.running) {
          if (st.error) {
            setMsg(st.error);
            onStatus('刮削补齐失败', 'warn');
            setEnrichBusy(false);
            enrichStopRequestedRef.current = false;
            return;
          }
          if (st.result) {
            const ok = st.result.ok ?? 0;
            const failed = st.result.failed ?? 0;
            const queued = st.result.queued ?? 0;
            if (st.result.paused) {
              setMsg(
                `已暂停 · 成功 ${ok}/${queued}${failed ? ` · 失败 ${failed}` : ''} · 再开继续`,
              );
              onStatus('已暂停刮削（队列已保留）', 'ok');
              // 暂停：保留分区进度，不清队列展示；开关保持关
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
                `已停止 · 成功 ${ok}/${queued}${failed ? ` · 失败 ${failed}` : ''} · 队列与日志已清除`,
              );
              onStatus('已停止刮削', 'ok');
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
                `${prefix}完成 · 成功 ${ok}/${queued}${failed ? ` · 失败 ${failed}` : ''}`,
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
          setEnrichPhase('');
          enrichStopRequestedRef.current = false;
          return;
        }
        await new Promise<void>((resolve) => {
          enrichPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      enrichPollingRef.current = false;
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
    setEnrichPhase('starting');
    setEnrichProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setEnrichLog([]);
    if (target) {
      setEnrichCurrentRegion(target);
      setEnrichRegionLogs((prev) => ({ ...prev, [target]: [] }));
      setEnrichProgressByRegion((prev) => ({ ...prev, [target]: null }));
    }
    const modeLabel = enrichMode === 'overwrite' ? '覆盖' : '增量';
    const regionLabel =
      (target && enrichRegions.find((r) => r.id === target)?.label) || '';
    onStatus(
      dryRun
        ? `刮削补齐预览中（${modeLabel}${regionLabel ? ` · ${regionLabel}` : ''}）…`
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
      await pollEnrichUntilDone();
    } catch (e) {
      setEnrichBusy(false);
      setEnrichPhase('');
      setEnrichProgress(null);
      const text = e instanceof Error ? e.message : '启动刮削补齐失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  async function setEnrichFillMode(next: 'incremental' | 'overwrite') {
    if (enrichBusy || next === enrichMode) return;
    const prev = enrichMode;
    setEnrichMode(next);
    try {
      const cur = await getScrapEnrichStrategy();
      const saved = await putScrapEnrichStrategy({
        ...cur,
        fillMode: next,
      });
      setEnrichMode(
        saved.fillMode === 'overwrite' ? 'overwrite' : 'incremental',
      );
    } catch (e) {
      setEnrichMode(prev);
      const text = e instanceof Error ? e.message : '保存补齐模式失败';
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
      try {
        await pauseScrapLibraryEnrich();
        onStatus('正在暂停刮削…', 'mute');
        let last: Awaited<ReturnType<typeof getScrapLibraryEnrichStatus>> | null =
          null;
        for (let i = 0; i < 40; i++) {
          const st = await getScrapLibraryEnrichStatus();
          last = st;
          setEnrichBusy(st.running);
          setEnrichPhase(st.phase || '');
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
          // 暂停：保留分区进度条与队列信息
          if (st.progress || st.checkpoints?.[regionId]) {
            const cp = st.checkpoints?.[regionId];
            setEnrichProgressByRegion((prev) => ({
              ...prev,
              [regionId]:
                st.progress ||
                (cp
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
                  : prev[regionId] || null),
            }));
          }
          if (!st.running) break;
          await new Promise<void>((r) => setTimeout(r, 400));
        }
        setEnrichBusy(false);
        setEnrichCurrentRegion('');
        setEnrichPhase(last?.phase === 'paused' ? 'paused' : '');
        // 最终再刷一次检查点，确保「已暂停」进度还在
        if (last?.checkpoints && typeof last.checkpoints === 'object') {
          setEnrichCheckpoints(last.checkpoints);
          const cp = last.checkpoints[regionId];
          if (cp) {
            setEnrichProgressByRegion((prev) => ({
              ...prev,
              [regionId]: {
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
        }
        onStatus('已暂停刮削（队列已保留）', 'ok');
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

  async function stopEnrichRegion(regionId: string) {
    if (enrichRegionBusy) return;
    const hasCp = Boolean(enrichCheckpoints[regionId]);
    const isRunningHere =
      enrichBusy && enrichCurrentRegion === regionId;
    if (!hasCp && !isRunningHere) return;

    // 立刻 UI 反馈：关开关、清进度/队列/日志
    enrichStopRequestedRef.current = true;
    setEnrichRegions((prev) =>
      prev.map((r) => (r.id === regionId ? { ...r, enabled: false } : r)),
    );
    setEnrichBusy(false);
    setEnrichCurrentRegion('');
    setEnrichPhase('');
    setEnrichProgress(null);
    setEnrichCheckpoints((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
    setEnrichProgressByRegion((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
    setEnrichRegionLogs((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
    setMsg('已停止 · 队列与日志已清除 · 下次从头开始');
    onStatus('已停止刮削（队列与日志已清除）', 'ok');

    setEnrichRegionBusy(true);
    try {
      await stopScrapLibraryEnrich({ region: regionId });
      // 后台等任务收尾，不再挡 UI
      for (let i = 0; i < 20; i++) {
        const st = await getScrapLibraryEnrichStatus();
        if (!st.running) {
          setEnrichCheckpoints(
            st.checkpoints && typeof st.checkpoints === 'object'
              ? st.checkpoints
              : {},
          );
          break;
        }
        await new Promise<void>((r) => setTimeout(r, 300));
      }
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
        /* ignore */
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : '停止失败';
      setMsg(text);
      onStatus(text, 'warn');
    } finally {
      setEnrichRegionBusy(false);
    }
  }

  function applyEnrichStoppedUi(regionId: string) {
    enrichStopRequestedRef.current = true;
    setEnrichRegions((prev) =>
      prev.map((r) => (r.id === regionId ? { ...r, enabled: false } : r)),
    );
    setEnrichBusy(false);
    setEnrichCurrentRegion('');
    setEnrichPhase('');
    setEnrichProgress(null);
    setEnrichCheckpoints((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
    setEnrichProgressByRegion((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
    setEnrichRegionLogs((prev) => {
      const next = { ...prev };
      delete next[regionId];
      return next;
    });
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
        onStopped={() => applyEnrichStoppedUi(enrichLive.regionId)}
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
  const enrichModeHint =
    enrichMode === 'overwrite'
      ? '全部重跑覆盖；队列先空壳再其余'
      : '先刮空壳（仅骨架），再补缺数据';
  const actressAvatarModeHint =
    actressAvatarMode === 'overwrite'
      ? '已有头像也重新下载覆盖'
      : '跳过已有头像，只补缺';
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
                    调度模式 · 并发参数 · 七区数据源
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
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削补齐</span>
                  <span className="settings-nav__desc">
                    {enrichModeHint}
                  </span>
                </span>
                <div
                  className="app-seg makers-manage__enrich-mode"
                  role="radiogroup"
                  aria-label="刮削补齐模式"
                >
                  <button
                    type="button"
                    className={cn(
                      'app-seg__btn',
                      enrichMode === 'incremental' && 'app-seg__btn--active',
                    )}
                    disabled={enrichBusy}
                    role="radio"
                    aria-checked={enrichMode === 'incremental'}
                    onClick={() => void setEnrichFillMode('incremental')}
                  >
                    增量
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'app-seg__btn',
                      enrichMode === 'overwrite' && 'app-seg__btn--active',
                    )}
                    disabled={enrichBusy}
                    role="radio"
                    aria-checked={enrichMode === 'overwrite'}
                    onClick={() => void setEnrichFillMode('overwrite')}
                  >
                    覆盖
                  </button>
                </div>
              </div>
            </li>
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">女优头像刮削</span>
                  <span className="settings-nav__desc">
                    {actressAvatarBusy
                      ? actressAvatarPhase || '刮削中…'
                      : actressAvatarModeHint}
                  </span>
                </span>
                <span className="makers-manage__status-actions">
                  <div
                    className="app-seg makers-manage__enrich-mode"
                    role="radiogroup"
                    aria-label="女优头像刮削模式"
                  >
                    <button
                      type="button"
                      className={cn(
                        'app-seg__btn',
                        actressAvatarMode === 'incremental' &&
                          'app-seg__btn--active',
                      )}
                      disabled={actressAvatarBusy}
                      role="radio"
                      aria-checked={actressAvatarMode === 'incremental'}
                      onClick={() => setActressAvatarMode('incremental')}
                    >
                      增量
                    </button>
                    <button
                      type="button"
                      className={cn(
                        'app-seg__btn',
                        actressAvatarMode === 'overwrite' &&
                          'app-seg__btn--active',
                      )}
                      disabled={actressAvatarBusy}
                      role="radio"
                      aria-checked={actressAvatarMode === 'overwrite'}
                      onClick={() => setActressAvatarMode('overwrite')}
                    >
                      覆盖
                    </button>
                  </div>
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
                    onClick={() => void onActressAvatarScrape()}
                  >
                    {actressAvatarBusy
                      ? typeof actressAvatarProgress?.percent === 'number'
                        ? `${Math.round(actressAvatarProgress.percent)}%`
                        : '刮削中…'
                      : actressAvatarMode === 'overwrite'
                        ? '覆盖刮削'
                        : '开始刮削'}
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
                            ? '下载'
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
                      aria-label="女优头像刮削进度"
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
              const qc = active ? enrichQueueCounts : null;
              const okN = (() => {
                if (qc) return Number(qc.done || 0);
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
                if (qc) {
                  return Number(qc.pending || 0) + Number(qc.running || 0);
                }
                if (!active && typeof cp?.remaining === 'number') {
                  return cp.remaining;
                }
                const tot =
                  typeof prog?.total === 'number' && prog.total > 0
                    ? prog.total
                    : typeof cp?.total === 'number' && cp.total > 0
                      ? cp.total
                      : null;
                const fin =
                  okN != null || failN != null
                    ? Number(okN || 0) + Number(failN || 0)
                    : typeof prog?.done === 'number'
                      ? prog.done
                      : null;
                if (tot != null && fin != null) return Math.max(0, tot - fin);
                return null;
              })();
              // 进度%与文案同一套数字：已完成/(已完成+未处理)，禁止再用可能脱节的 progress.percent
              const pct = (() => {
                const fin =
                  okN != null || failN != null
                    ? Number(okN || 0) + Number(failN || 0)
                    : null;
                const rem = remainingN;
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
                enrichMode === 'incremental'
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
              const stageLabel = active
                ? queueStage
                  ? enrichMode === 'overwrite'
                    ? '排队'
                    : '筛选'
                  : prog?.stage === 'done'
                    ? '完成'
                    : '补齐中'
                : cp
                  ? '已暂停'
                  : prog?.stage === 'done'
                    ? '已完成'
                    : '进度';
              const rateLabel = (() => {
                if (!active || queueStage || stageLabel !== '补齐中') return '';
                const sp = enrichSpeedRef.current;
                if (!sp || sp.regionId !== region.id) return '';
                const fin = Number(okN || 0) + Number(failN || 0);
                const mins = (Date.now() - sp.t0) / 60000;
                if (mins < 0.05) return '';
                const perMin = Math.max(0, fin - sp.fin0) / mins;
                if (perMin < 0.05 && mins < 0.5) return '';
                return perMin >= 10
                  ? `${Math.round(perMin)} 部/分`
                  : `${perMin.toFixed(1).replace(/\.0$/, '')} 部/分`;
              })();
              const statsParts: string[] = [];
              if (!queueStage && okN != null) {
                statsParts.push(`成功 ${okN.toLocaleString()}`);
              }
              if (!queueStage && failN != null) {
                statsParts.push(`失败 ${failN.toLocaleString()}`);
              }
              if (remainLabel) statsParts.push(remainLabel);
              const statsLabel = statsParts.join(' · ');

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
                    <button
                      type="button"
                      className="makers-manage__probe-btn makers-manage__probe-btn--danger"
                      disabled={(() => {
                        const activeHere =
                          enrichBusy && enrichCurrentRegion === region.id;
                        // 跑着时可随时停止；不要被 enrichRegionBusy 卡住
                        if (activeHere) return false;
                        return (
                          enrichRegionBusy || !enrichCheckpoints[region.id]
                        );
                      })()}
                      onClick={() => void stopEnrichRegion(region.id)}
                    >
                      停止
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
                        {statsLabel ? (
                          <span className="makers-manage__scan-stats">
                            {statsLabel}
                          </span>
                        ) : null}
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
                      : '少补多删 · NFO→向量 + HNSW（磁盘无则删库）'}
                  </span>
                </span>
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
                  onClick={() => void onScrapEmbedSync()}
                >
                  {scrapBusy
                    ? scrapPct != null
                      ? `${Math.round(scrapPct)}%`
                      : '同步中…'
                    : '开始同步'}
                </button>
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
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">优化女优元数据</span>
                  <span className="settings-nav__desc">
                    {actressOptBusy
                      ? actressOptPhase || '优化中…'
                      : '补优化库内已有条目（刮削/同步时已自动优化）'}
                  </span>
                </span>
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
                  onClick={() => void onActressOptimize()}
                >
                  {actressOptBusy
                    ? actressOptPct != null
                      ? `${Math.round(actressOptPct)}%`
                      : '优化中…'
                    : '开始优化'}
                </button>
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
                      aria-label="女优元数据优化进度"
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
                        ? actressOptProgress?.stage === 'embed' ||
                          actressOptProgress?.stage === 'patch'
                          ? '写入'
                          : actressOptProgress?.stage === 'diff'
                            ? '比对'
                            : actressOptProgress?.stage === 'scan'
                              ? '扫描'
                              : actressOptProgress?.stage === 'done'
                                ? '完成'
                                : '准备'
                        : '已完成'}
                      {actressOptCountLabel
                        ? ` · ${actressOptCountLabel}`
                        : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {actressOptPct != null &&
                      (actressOptBusy || actressOptProgress) ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(actressOptPct)}%`}
                        </span>
                      ) : null}
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
                          ? actressAvatarPhase || '女优头像刮削中…'
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
                  ? '女优元数据优化日志'
                  : scanLogModal === 'actressAvatar'
                    ? '女优头像刮削日志'
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
