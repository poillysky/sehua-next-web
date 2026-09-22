'use client';

import { useEffect, useRef, useState } from 'react';
import {
  getScrapLibraryQuality,
  type ScrapLibraryEnrichJobStatus,
  type ScrapLibraryQualityStats,
} from '@/lib/api';
import { MAKER_KIND_TABS } from '@/features/makers/makersUi';
import { type ScanLogModal, type StatusReporter } from './types';
import { formatCatalogRegionDesc, formatQualityDetail } from './helpers';
import { useMakersCatalog } from './useMakersCatalog';
import { useMakersJobs } from './useMakersJobs';
import { useMakersEnrichOverview } from './useMakersEnrichOverview';

export type { StatusReporter } from './types';
export type MakersManagePanelState = ReturnType<typeof useMakersManagePanel>;

export function useMakersManagePanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
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
  const [scrapQualityByRegion, setScrapQualityByRegion] = useState<
    Record<string, ScrapLibraryQualityStats>
  >({});
  const [scanLogModal, setScanLogModal] = useState<ScanLogModal>(null);
  const [gateBusy, setGateBusy] = useState(false);
  const [gateSummary, setGateSummary] = useState('');
  const enrichBusyRef = useRef(false);

  useEffect(() => {
    // 热重载会保留旧 msg，避免进页再弹一次完成 Toast
    setMsg('');
  }, []);

  const catalog = useMakersCatalog({ setMsg });

  const jobs = useMakersJobs({
    onStatus,
    setMsg,
    catalogBusy: catalog.catalogBusy,
    enrichBusyRef,
    refreshCatalogSummary: catalog.refreshCatalogSummary,
    catalogNavLevel: catalog.catalogNav?.level,
    scrapHubOpen,
  });

  const enrich = useMakersEnrichOverview({
    onStatus,
    setMsg,
    catalogBusy: catalog.catalogBusy,
    strmBusy: jobs.strmBusy,
    localIndexBusy: jobs.localIndexBusy,
    scrapBusy: jobs.scrapBusy,
    setActressAvatarMode: jobs.setActressAvatarMode,
  });
  enrichBusyRef.current = enrich.enrichBusy;

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

  const catalogPushTitle =
    scrapHubOpen
      ? '刮削库'
      : catalog.catalogNav?.level === 'prefix'
      ? catalog.catalogNav.prefix
      : catalog.catalogNav?.level === 'region'
        ? catalog.catalogNav.label
        : catalog.catalogNav?.level === 'regions'
          ? '六区目录'
          : '片商管理';
  const catalogPushBack = scrapHubOpen
    ? () => {
        setScrapHubOpen(false);
        setMsg('');
      }
    : catalog.catalogNav?.level === 'prefix'
      ? catalog.catalogPrefixBack
      : catalog.catalogNav?.level === 'region'
        ? catalog.catalogRegionBack
        : catalog.catalogNav?.level === 'regions'
          ? catalog.catalogRegionsBack
          : onBack;

  const actressAvatarModeHint =
    jobs.actressAvatarMode === 'overwrite'
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
    : catalog.catalogNav?.level === 'prefix'
      ? `mm-prefix-${catalog.catalogNav.regionId}-${catalog.catalogNav.prefix}`
      : catalog.catalogNav?.level === 'region'
        ? `mm-region-${catalog.catalogNav.regionId}`
        : catalog.catalogNav?.level === 'regions'
          ? 'mm-regions'
          : 'mm-hub';

  return {
    onBack,
    onStatus,
    catalogNav: catalog.catalogNav,
    catalogSummary: catalog.catalogSummary,
    catalogPrefixes: catalog.catalogPrefixes,
    catalogDetail: catalog.catalogDetail,
    catalogCodePage: catalog.catalogCodePage,
    catalogBusy: catalog.catalogBusy,
    msg,
    setMsg,
    sourcesOpen,
    setSourcesOpen,
    enrichStrategyOpen,
    setEnrichStrategyOpen,
    enrichLive,
    setEnrichLive,
    scrapHubOpen,
    setScrapHubOpen,
    localIndexBusy: jobs.localIndexBusy,
    localIndexPhase: jobs.localIndexPhase,
    localIndexProgress: jobs.localIndexProgress,
    localIndexLog: jobs.localIndexLog,
    strmRoot: jobs.strmRoot,
    setStrmRoot: jobs.setStrmRoot,
    strmBusy: jobs.strmBusy,
    strmPhase: jobs.strmPhase,
    strmProgress: jobs.strmProgress,
    strmLog: jobs.strmLog,
    strmBrowseOpen: jobs.strmBrowseOpen,
    setStrmBrowseOpen: jobs.setStrmBrowseOpen,
    strmBrowseKind: jobs.strmBrowseKind,
    strmBrowse: jobs.strmBrowse,
    strmBrowseLoading: jobs.strmBrowseLoading,
    strmNewFolder: jobs.strmNewFolder,
    setStrmNewFolder: jobs.setStrmNewFolder,
    strmBrowseMsg: jobs.strmBrowseMsg,
    setStrmBrowseMsg: jobs.setStrmBrowseMsg,
    scrapRoot: jobs.scrapRoot,
    setScrapRoot: jobs.setScrapRoot,
    scrapBusy: jobs.scrapBusy,
    scrapPhase: jobs.scrapPhase,
    scrapJobMode: jobs.scrapJobMode,
    scrapProgress: jobs.scrapProgress,
    scrapLog: jobs.scrapLog,
    actressOptBusy: jobs.actressOptBusy,
    actressOptPhase: jobs.actressOptPhase,
    actressOptProgress: jobs.actressOptProgress,
    actressOptLog: jobs.actressOptLog,
    nfoOptBusy: jobs.nfoOptBusy,
    nfoOptPhase: jobs.nfoOptPhase,
    nfoOptProgress: jobs.nfoOptProgress,
    nfoOptLog: jobs.nfoOptLog,
    actressAvatarBusy: jobs.actressAvatarBusy,
    actressAvatarPhase: jobs.actressAvatarPhase,
    actressAvatarProgress: jobs.actressAvatarProgress,
    actressAvatarLog: jobs.actressAvatarLog,
    actressAvatarMode: jobs.actressAvatarMode,
    setActressAvatarMode: jobs.setActressAvatarMode,
    setEnrichMode: enrich.setEnrichMode,
    scrapQualityByRegion,
    setScrapQualityByRegion,
    enrichBusy: enrich.enrichBusy,
    enrichPhase: enrich.enrichPhase,
    enrichProgress: enrich.enrichProgress,
    enrichProgressByRegion: enrich.enrichProgressByRegion,
    enrichLog: enrich.enrichLog,
    enrichRegionLogs: enrich.enrichRegionLogs,
    enrichCurrentRegion: enrich.enrichCurrentRegion,
    enrichCheckpoints: enrich.enrichCheckpoints,
    enrichQueueCounts: enrich.enrichQueueCounts,
    enrichRegionQueueCounts: enrich.enrichRegionQueueCounts,
    enrichLibrary: enrich.enrichLibrary,
    enrichMode: enrich.enrichMode,
    enrichRegions: enrich.enrichRegions,
    enrichRegionBusy: enrich.enrichRegionBusy,
    enrichSpeedRef: enrich.enrichSpeedRef,
    scanLogModal,
    setScanLogModal,
    gateBusy,
    setGateBusy,
    gateSummary,
    setGateSummary,
    refreshScrapQuality,
    onLocalIndexScan: jobs.onLocalIndexScan,
    loadStrmBrowse: jobs.loadStrmBrowse,
    openStrmBrowse: jobs.openStrmBrowse,
    openScrapBrowse: jobs.openScrapBrowse,
    onPickStrmDir: jobs.onPickStrmDir,
    onCreateStrmFolder: jobs.onCreateStrmFolder,
    onStrmSync: jobs.onStrmSync,
    onScrapEmbedSync: jobs.onScrapEmbedSync,
    onActressOptimize: jobs.onActressOptimize,
    onNfoOptimize: jobs.onNfoOptimize,
    onActressAvatarScrape: jobs.onActressAvatarScrape,
    toggleEnrichRegion: enrich.toggleEnrichRegion,
    openCatalogRegion: catalog.openCatalogRegion,
    loadCatalogCodes: catalog.loadCatalogCodes,
    openCatalogPrefix: catalog.openCatalogPrefix,
    openCatalogRegions: catalog.openCatalogRegions,
    catalogRegionsBack: catalog.catalogRegionsBack,
    catalogRegionBack: catalog.catalogRegionBack,
    catalogPrefixBack: catalog.catalogPrefixBack,
    codeTotal: catalog.codeTotal,
    codePages: catalog.codePages,
    catalogPushTitle,
    catalogPushBack,
    catalogRegionRows: catalog.catalogRegionRows,
    formatCatalogRegionDesc,
    localIndexPct: jobs.localIndexPct,
    localIndexCountLabel: jobs.localIndexCountLabel,
    strmPct: jobs.strmPct,
    strmCountLabel: jobs.strmCountLabel,
    scrapPct: jobs.scrapPct,
    scrapCountLabel: jobs.scrapCountLabel,
    actressOptPct: jobs.actressOptPct,
    actressOptCountLabel: jobs.actressOptCountLabel,
    nfoOptPct: jobs.nfoOptPct,
    nfoOptCountLabel: jobs.nfoOptCountLabel,
    actressAvatarModeHint,
    qualityDetailModal,
    qualityDetail,
    catalogScrollKey,
  };
}
