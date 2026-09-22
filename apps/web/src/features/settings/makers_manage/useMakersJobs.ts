'use client';

import { useRef, type MutableRefObject } from 'react';
import type { StatusReporter } from './types';
import { useMakersLocalStrm } from './useMakersLocalStrm';
import { useMakersScrapOptJobs } from './useMakersScrapOptJobs';

export function useMakersJobs({
  onStatus,
  setMsg,
  catalogBusy,
  enrichBusyRef,
  refreshCatalogSummary,
  catalogNavLevel,
  scrapHubOpen,
}: {
  onStatus: StatusReporter;
  setMsg: (text: string) => void;
  catalogBusy: boolean;
  enrichBusyRef: MutableRefObject<boolean>;
  refreshCatalogSummary: () => Promise<void>;
  catalogNavLevel: string | undefined;
  scrapHubOpen: boolean;
}) {
  const localIndexBusyRef = useRef(false);
  const strmBusyRef = useRef(false);
  const scrapBusyRef = useRef(false);

  const scrap = useMakersScrapOptJobs({
    onStatus,
    setMsg,
    catalogBusy,
    enrichBusyRef,
    localIndexBusyRef,
    strmBusyRef,
    catalogNavLevel,
    scrapHubOpen,
  });
  scrapBusyRef.current = scrap.scrapBusy;

  const local = useMakersLocalStrm({
    onStatus,
    setMsg,
    catalogBusy,
    enrichBusyRef,
    refreshCatalogSummary,
    catalogNavLevel,
    scrapBusyRef,
    scrapRoot: scrap.scrapRoot,
    setScrapRoot: scrap.setScrapRoot,
  });
  localIndexBusyRef.current = local.localIndexBusy;
  strmBusyRef.current = local.strmBusy;

  return {
    localIndexBusy: local.localIndexBusy,
    localIndexPhase: local.localIndexPhase,
    localIndexProgress: local.localIndexProgress,
    localIndexLog: local.localIndexLog,
    strmRoot: local.strmRoot,
    setStrmRoot: local.setStrmRoot,
    strmBusy: local.strmBusy,
    strmPhase: local.strmPhase,
    strmProgress: local.strmProgress,
    strmLog: local.strmLog,
    strmBrowseOpen: local.strmBrowseOpen,
    setStrmBrowseOpen: local.setStrmBrowseOpen,
    strmBrowseKind: local.strmBrowseKind,
    strmBrowse: local.strmBrowse,
    strmBrowseLoading: local.strmBrowseLoading,
    strmNewFolder: local.strmNewFolder,
    setStrmNewFolder: local.setStrmNewFolder,
    strmBrowseMsg: local.strmBrowseMsg,
    setStrmBrowseMsg: local.setStrmBrowseMsg,
    scrapRoot: scrap.scrapRoot,
    setScrapRoot: scrap.setScrapRoot,
    scrapBusy: scrap.scrapBusy,
    scrapPhase: scrap.scrapPhase,
    scrapJobMode: scrap.scrapJobMode,
    scrapProgress: scrap.scrapProgress,
    scrapLog: scrap.scrapLog,
    actressOptBusy: scrap.actressOptBusy,
    actressOptPhase: scrap.actressOptPhase,
    actressOptProgress: scrap.actressOptProgress,
    actressOptLog: scrap.actressOptLog,
    nfoOptBusy: scrap.nfoOptBusy,
    nfoOptPhase: scrap.nfoOptPhase,
    nfoOptProgress: scrap.nfoOptProgress,
    nfoOptLog: scrap.nfoOptLog,
    actressAvatarBusy: scrap.actressAvatarBusy,
    actressAvatarPhase: scrap.actressAvatarPhase,
    actressAvatarProgress: scrap.actressAvatarProgress,
    actressAvatarLog: scrap.actressAvatarLog,
    actressAvatarMode: scrap.actressAvatarMode,
    setActressAvatarMode: scrap.setActressAvatarMode,
    onLocalIndexScan: local.onLocalIndexScan,
    loadStrmBrowse: local.loadStrmBrowse,
    openStrmBrowse: local.openStrmBrowse,
    openScrapBrowse: local.openScrapBrowse,
    onPickStrmDir: local.onPickStrmDir,
    onCreateStrmFolder: local.onCreateStrmFolder,
    onStrmSync: local.onStrmSync,
    onScrapEmbedSync: scrap.onScrapEmbedSync,
    onActressOptimize: scrap.onActressOptimize,
    onNfoOptimize: scrap.onNfoOptimize,
    onActressAvatarScrape: scrap.onActressAvatarScrape,
    localIndexPct: local.localIndexPct,
    localIndexCountLabel: local.localIndexCountLabel,
    strmPct: local.strmPct,
    strmCountLabel: local.strmCountLabel,
    scrapPct: scrap.scrapPct,
    scrapCountLabel: scrap.scrapCountLabel,
    actressOptPct: scrap.actressOptPct,
    actressOptCountLabel: scrap.actressOptCountLabel,
    nfoOptPct: scrap.nfoOptPct,
    nfoOptCountLabel: scrap.nfoOptCountLabel,
  };
}
