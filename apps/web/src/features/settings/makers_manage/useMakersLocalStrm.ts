'use client';

import { useEffect, useRef, useState, type MutableRefObject } from 'react';
import {
  browsePrefixCatalogStrmDirs,
  getPrefixCatalogLocalIndexStatus,
  getPrefixCatalogStrmSyncSettings,
  getPrefixCatalogStrmSyncStatus,
  mkdirPrefixCatalogStrmDir,
  putPrefixCatalogStrmSyncSettings,
  putScrapLibraryEmbedSettings,
  startPrefixCatalogLocalIndex,
  startPrefixCatalogStrmSync,
  type PrefixCatalogLocalIndexProgress,
  type PrefixCatalogStrmBrowse,
} from '@/lib/api';
import { strmStoppedHint } from './helpers';
import type { StatusReporter } from './types';

export function useMakersLocalStrm({
  onStatus,
  setMsg,
  catalogBusy,
  enrichBusyRef,
  refreshCatalogSummary,
  catalogNavLevel,
  scrapBusyRef,
  scrapRoot,
  setScrapRoot,
}: {
  onStatus: StatusReporter;
  setMsg: (text: string) => void;
  catalogBusy: boolean;
  enrichBusyRef: MutableRefObject<boolean>;
  refreshCatalogSummary: () => Promise<void>;
  catalogNavLevel: string | undefined;
  scrapBusyRef: MutableRefObject<boolean>;
  scrapRoot: string;
  setScrapRoot: (root: string) => void;
}) {
  const [localIndexBusy, setLocalIndexBusy] = useState(false);
  const [localIndexPhase, setLocalIndexPhase] = useState('');
  const [localIndexProgress, setLocalIndexProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [localIndexLog, setLocalIndexLog] = useState<string[]>([]);
  const localIndexPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const localIndexPollingRef = useRef(false);
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

  useEffect(() => {
    void (async () => {
      try {
        const s = await getPrefixCatalogStrmSyncSettings();
        setStrmRoot(s.root || 'strm-library');
      } catch {
        setStrmRoot('strm-library');
      }
    })();
  }, []);

  useEffect(() => {
    return () => {
      if (localIndexPollRef.current) clearTimeout(localIndexPollRef.current);
      if (strmPollRef.current) clearTimeout(strmPollRef.current);
    };
  }, []);

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
            const skPurged = st.result.skeleton?.purged_skeletons ?? 0;
            const skBits: string[] = [];
            if (st.result.skeleton?.ok) {
              skBits.push(
                `骨架重建 删壳${skPurged} 目录外-${skCodes} 新壳+${skIns} 保留已刮${skSkip}`,
              );
            } else if (st.result.skeleton?.error) {
              skBits.push(`骨架失败 · ${st.result.skeleton.error}`);
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
    if (localIndexBusy || catalogBusy || strmBusy) return;
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
            onStatus('本地同步失败', 'warn');
            setStrmPhase('');
            setStrmProgress(null);
          } else if (st.result) {
            const written = st.result.written ?? 0;
            const deleted = st.result.deleted ?? 0;
            const total = st.result.total ?? 0;
            const bits = [`写入 ${written}`, `合计 ${total}`];
            if (deleted > 0) bits.push(`删多余 ${deleted}`);
            setMsg(`本地同步完成 · ${bits.join(' · ')}`);
            onStatus('本地同步完成', 'ok');
            setStrmPhase('');
            setStrmProgress(null);
          } else {
            const hint = strmStoppedHint(st);
            if (hint) {
              setMsg(hint);
              onStatus('本地同步已中断', 'warn');
              setStrmPhase('interrupted');
            } else {
              setStrmPhase('');
              setStrmProgress(null);
            }
          }
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
    if (strmBusy || localIndexBusy || scrapBusyRef.current) return;
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
    if (strmBusy || localIndexBusy || scrapBusyRef.current) return;
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
    if (
      strmBusy ||
      localIndexBusy ||
      catalogBusy ||
      scrapBusyRef.current ||
      enrichBusyRef.current
    )
      return;
    const root = strmRoot.trim() || 'strm-library';
    setMsg('');
    setStrmBusy(true);
    setStrmPhase('starting');
    setStrmProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setStrmLog([]);
    onStatus('本地同步中…', 'mute');
    try {
      await startPrefixCatalogStrmSync(root);
      await pollStrmSyncUntilDone();
    } catch (e) {
      setStrmBusy(false);
      setStrmPhase('');
      setStrmProgress(null);
      const text = e instanceof Error ? e.message : '启动本地同步失败';
      setMsg(text);
      onStatus(text, 'warn');
    }
  }

  useEffect(() => {
    if (catalogNavLevel !== 'regions') return;
    void (async () => {
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
        } else {
          const hint = strmStoppedHint(st);
          if (hint) {
            setStrmPhase('interrupted');
            setStrmProgress(st.progress || null);
            setStrmLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
            setMsg(hint);
          }
        }
      } catch {
        /* ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resume poll when opening regions
  }, [catalogNavLevel]);

  const localIndexPct =
    typeof localIndexProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, localIndexProgress.percent))
      : localIndexBusy
        ? 0
        : null;
  const localIndexCountLabel =
    typeof localIndexProgress?.done === 'number'
      ? typeof localIndexProgress?.total === 'number' &&
        localIndexProgress.total > 0
        ? `${localIndexProgress.done.toLocaleString()} / ${localIndexProgress.total.toLocaleString()}`
        : `${localIndexProgress.done.toLocaleString()} 行`
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

  return {
    localIndexBusy,
    localIndexPhase,
    localIndexProgress,
    localIndexLog,
    strmRoot,
    setStrmRoot,
    strmBusy,
    strmPhase,
    strmProgress,
    strmLog,
    strmBrowseOpen,
    setStrmBrowseOpen,
    strmBrowseKind,
    strmBrowse,
    strmBrowseLoading,
    strmNewFolder,
    setStrmNewFolder,
    strmBrowseMsg,
    setStrmBrowseMsg,
    onLocalIndexScan,
    loadStrmBrowse,
    openStrmBrowse,
    openScrapBrowse,
    onPickStrmDir,
    onCreateStrmFolder,
    onStrmSync,
    localIndexPct,
    localIndexCountLabel,
    strmPct,
    strmCountLabel,
  };
}
