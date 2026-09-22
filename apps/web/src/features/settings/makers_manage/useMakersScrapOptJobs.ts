'use client';

import { useEffect, useRef, useState, type MutableRefObject } from 'react';
import {
  getScrapLibraryEmbedSettings,
  getScrapLibraryEmbedStatus,
  getScrapActressOptimizeStatus,
  getScrapNfoOptimizeStatus,
  getScrapActressAvatarStatus,
  startScrapLibraryEmbed,
  startScrapActressOptimize,
  startScrapNfoOptimize,
  startScrapActressAvatar,
  type PrefixCatalogLocalIndexProgress,
  type ScrapNfoOptimizeJobStatus,
  type ScrapActressAvatarJobStatus,
} from '@/lib/api';
import type { StatusReporter } from './types';

export function useMakersScrapOptJobs({
  onStatus,
  setMsg,
  catalogBusy,
  enrichBusyRef,
  localIndexBusyRef,
  strmBusyRef,
  catalogNavLevel,
  scrapHubOpen,
}: {
  onStatus: StatusReporter;
  setMsg: (text: string) => void;
  catalogBusy: boolean;
  enrichBusyRef: MutableRefObject<boolean>;
  localIndexBusyRef: MutableRefObject<boolean>;
  strmBusyRef: MutableRefObject<boolean>;
  catalogNavLevel: string | undefined;
  scrapHubOpen: boolean;
}) {
  const [scrapRoot, setScrapRoot] = useState('scrap-library');
  const [scrapBusy, setScrapBusy] = useState(false);
  const [scrapPhase, setScrapPhase] = useState('');
  /** 当前灌库任务：meta=同步数据库 · embed=向量化 · full=旧合一 */
  const [scrapJobMode, setScrapJobMode] = useState<
    'meta' | 'embed' | 'full' | null
  >(null);
  const scrapJobModeRef = useRef<'meta' | 'embed' | 'full' | null>(null);
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

  const [nfoOptBusy, setNfoOptBusy] = useState(false);
  const [nfoOptPhase, setNfoOptPhase] = useState('');
  const [nfoOptProgress, setNfoOptProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [nfoOptLog, setNfoOptLog] = useState<string[]>([]);
  const nfoOptPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nfoOptPollingRef = useRef(false);

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

  useEffect(() => {
    void (async () => {
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
          const logText = (Array.isArray(st.log) ? st.log : []).join('\n');
          const resumedMode: 'meta' | 'embed' | 'full' =
            logText.includes('开始向量化') || logText.includes('待向量化')
              ? 'embed'
              : logText.includes('同步数据库') || logText.includes('仅写元数据')
                ? 'meta'
                : 'full';
          setScrapJobMode(resumedMode);
          scrapJobModeRef.current = resumedMode;
          void pollScrapEmbedUntilDone();
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
        const st = await getScrapNfoOptimizeStatus();
        if (st.running) {
          setNfoOptBusy(true);
          setNfoOptPhase(st.phase || '优化中…');
          setNfoOptProgress(st.progress || null);
          setNfoOptLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
          void pollNfoOptUntilDone();
        }
      } catch {
        /* ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount resume only
  }, []);

  useEffect(() => {
    return () => {
      if (scrapPollRef.current) clearTimeout(scrapPollRef.current);
      if (actressOptPollRef.current) clearTimeout(actressOptPollRef.current);
      if (nfoOptPollRef.current) clearTimeout(nfoOptPollRef.current);
      if (actressAvatarPollRef.current)
        clearTimeout(actressAvatarPollRef.current);
    };
  }, []);

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
            const mode = String(
              st.result?.mode || scrapJobModeRef.current || 'full',
            );
            if (st.error) {
              setMsg(st.error);
              onStatus(
                mode === 'embed'
                  ? '数据库向量化失败'
                  : mode === 'meta'
                    ? '同步数据库失败'
                    : '刮削库向量同步失败',
                'warn',
              );
            } else if (st.result) {
              const written = st.result.written ?? 0;
              const total = st.result.total ?? 0;
              const deleted = st.result.deleted ?? 0;
              if (mode === 'embed') {
                setMsg(`数据库向量化完成 · ${written}/${total}`);
                onStatus('数据库向量化完成', 'ok');
              } else if (mode === 'meta') {
                setMsg(
                  deleted > 0
                    ? `数据库已同步 · ${written}/${total} · 删多余 ${deleted}`
                    : `数据库已同步 · ${written}/${total}`,
                );
                onStatus('数据库已同步', 'ok');
              } else {
                setMsg(
                  deleted > 0
                    ? `刮削库已写入元库 · ${written}/${total} · 删多余 ${deleted}`
                    : `刮削库已写入元库 · ${written}/${total}`,
                );
                onStatus('刮削库向量已同步', 'ok');
              }
            }
          }
          setScrapBusy(false);
          setScrapPhase('');
          setScrapProgress(null);
          // 保留 scrapJobMode，日志按钮仍挂在对应行
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

  async function onScrapEmbedSync(
    force = false,
    mode: 'meta' | 'embed' = 'meta',
  ) {
    if (
      strmBusyRef.current ||
      localIndexBusyRef.current ||
      catalogBusy ||
      scrapBusy ||
      enrichBusyRef.current ||
      actressOptBusy ||
      nfoOptBusy ||
      actressAvatarBusy
    )
      return;
    const root = scrapRoot.trim() || 'scrap-library';
    setMsg('');
    setScrapBusy(true);
    setScrapJobMode(mode);
    scrapJobModeRef.current = mode;
    const phase =
      mode === 'embed'
        ? force
          ? '全量向量化…'
          : '增量向量化…'
        : force
          ? '全量同步数据库…'
          : '增量同步数据库…';
    setScrapPhase(phase);
    setScrapProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setScrapLog([]);
    onStatus(
      mode === 'embed'
        ? force
          ? '数据库全量向量化中…'
          : '数据库增量向量化中（仅零向量）…'
        : force
          ? '全量同步数据库中…'
          : '增量同步数据库中（跳过未变）…',
      'mute',
    );
    try {
      await startScrapLibraryEmbed({ root, force, mode });
      await pollScrapEmbedUntilDone({ notify: true });
    } catch (e) {
      setScrapBusy(false);
      setScrapPhase('');
      setScrapProgress(null);
      setScrapJobMode(null);
      scrapJobModeRef.current = null;
      const text =
        e instanceof Error
          ? e.message
          : mode === 'embed'
            ? '启动向量化失败'
            : '启动数据库同步失败';
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
      strmBusyRef.current ||
      localIndexBusyRef.current ||
      catalogBusy ||
      scrapBusy ||
      enrichBusyRef.current ||
      actressOptBusy ||
      nfoOptBusy ||
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

  async function pollNfoOptUntilDone(opts?: { notify?: boolean }) {
    if (nfoOptPollingRef.current) return;
    nfoOptPollingRef.current = true;
    let seenRunning = Boolean(opts?.notify);
    try {
      for (;;) {
        const st: ScrapNfoOptimizeJobStatus = await getScrapNfoOptimizeStatus();
        if (st.running) seenRunning = true;
        setNfoOptBusy(st.running);
        setNfoOptPhase(st.phase || (st.running ? '优化中…' : ''));
        setNfoOptProgress(st.progress || null);
        setNfoOptLog(Array.isArray(st.log) ? st.log.slice(-40) : []);
        if (!st.running) {
          if (seenRunning) {
            if (st.error) {
              setMsg(st.error);
              onStatus('NFO 优化失败', 'warn');
            } else if (st.result) {
              const updated = st.result.updated ?? 0;
              const total = st.result.total ?? 0;
              const unchanged = st.result.unchanged ?? 0;
              setMsg(
                `NFO 已优化 · 更新 ${updated}/${total} · 未变 ${unchanged}`,
              );
              onStatus('NFO 已优化', 'ok');
            }
          }
          setNfoOptBusy(false);
          setNfoOptPhase('');
          setNfoOptProgress(null);
          return;
        }
        await new Promise<void>((resolve) => {
          nfoOptPollRef.current = setTimeout(resolve, 450);
        });
      }
    } finally {
      nfoOptPollingRef.current = false;
    }
  }

  async function onNfoOptimize(force = false) {
    if (
      strmBusyRef.current ||
      localIndexBusyRef.current ||
      catalogBusy ||
      scrapBusy ||
      enrichBusyRef.current ||
      actressOptBusy ||
      nfoOptBusy ||
      actressAvatarBusy
    )
      return;
    setMsg('');
    setNfoOptBusy(true);
    setNfoOptPhase(force ? '全量优化…' : '增量优化…');
    setNfoOptProgress({ stage: 'prepare', percent: 0, label: 'starting' });
    setNfoOptLog([]);
    onStatus(
      force
        ? '全量用本地映射重写 NFO…'
        : '增量用本地映射优化 NFO（有变才写）…',
      'mute',
    );
    try {
      await startScrapNfoOptimize({ force });
      await pollNfoOptUntilDone({ notify: true });
    } catch (e) {
      setNfoOptBusy(false);
      setNfoOptPhase('');
      setNfoOptProgress(null);
      const text = e instanceof Error ? e.message : '启动 NFO 优化失败';
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
      strmBusyRef.current ||
      localIndexBusyRef.current ||
      catalogBusy ||
      scrapBusy ||
      enrichBusyRef.current ||
      actressOptBusy ||
      nfoOptBusy ||
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

  useEffect(() => {
    if (catalogNavLevel !== 'regions' && !scrapHubOpen) return;
    void (async () => {
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
  }, [catalogNavLevel, scrapHubOpen]);

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
  const nfoOptPct =
    typeof nfoOptProgress?.percent === 'number'
      ? Math.max(0, Math.min(100, nfoOptProgress.percent))
      : nfoOptBusy
        ? 0
        : null;
  const nfoOptCountLabel =
    typeof nfoOptProgress?.done === 'number' &&
    typeof nfoOptProgress?.total === 'number' &&
    nfoOptProgress.total > 0
      ? `${nfoOptProgress.done.toLocaleString()} / ${nfoOptProgress.total.toLocaleString()}`
      : typeof nfoOptProgress?.done === 'number' && nfoOptProgress.done > 0
        ? nfoOptProgress.done.toLocaleString()
        : '';

  return {
    scrapRoot,
    setScrapRoot,
    scrapBusy,
    scrapPhase,
    scrapJobMode,
    scrapProgress,
    scrapLog,
    actressOptBusy,
    actressOptPhase,
    actressOptProgress,
    actressOptLog,
    nfoOptBusy,
    nfoOptPhase,
    nfoOptProgress,
    nfoOptLog,
    actressAvatarBusy,
    actressAvatarPhase,
    actressAvatarProgress,
    actressAvatarLog,
    actressAvatarMode,
    setActressAvatarMode,
    onScrapEmbedSync,
    onActressOptimize,
    onNfoOptimize,
    onActressAvatarScrape,
    scrapPct,
    scrapCountLabel,
    actressOptPct,
    actressOptCountLabel,
    nfoOptPct,
    nfoOptCountLabel,
  };
}
