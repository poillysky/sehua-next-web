'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Folder, FolderPlus, RefreshCw } from 'lucide-react';
import {
  browsePrefixCatalogStrmDirs,
  getPrefixCatalogLocalIndexStatus,
  getPrefixCatalogPrefixDetail,
  getPrefixCatalogPrefixes,
  getPrefixCatalogStrmSyncSettings,
  getPrefixCatalogStrmSyncStatus,
  getPrefixCatalogSummary,
  getScrapLibraryEmbedSettings,
  getScrapLibraryEmbedStatus,
  mkdirPrefixCatalogStrmDir,
  putPrefixCatalogStrmSyncSettings,
  putScrapLibraryEmbedSettings,
  startPrefixCatalogLocalIndex,
  startPrefixCatalogStrmSync,
  startScrapLibraryEmbed,
  type PrefixCatalogLocalIndexProgress,
  type PrefixCatalogPrefixDetail,
  type PrefixCatalogPrefixRow,
  type PrefixCatalogStrmBrowse,
  type PrefixCatalogSummary,
} from '@/lib/api';
import { MAKER_KIND_TABS } from '@/features/makers/makersUi';
import { AppPush } from '@/components/ui/AppPush';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { AppMsg } from '@/components/ui/AppMsg';
import { ScrapeSourcesSection } from '@/features/settings/ScrapeSourcesSection';

const CODES_PAGE_SIZE = 50;

type ScanLogModal = 'local' | 'strm' | 'scrap' | null;

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
  const [scrapRoot, setScrapRoot] = useState('scrap-library');
  const [scrapBusy, setScrapBusy] = useState(false);
  const [scrapPhase, setScrapPhase] = useState('');
  const [scrapProgress, setScrapProgress] =
    useState<PrefixCatalogLocalIndexProgress | null>(null);
  const [scrapLog, setScrapLog] = useState<string[]>([]);
  const scrapPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrapPollingRef = useRef(false);
  const [scanLogModal, setScanLogModal] = useState<ScanLogModal>(null);

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
    })();
  }, []);

  useEffect(() => {
    return () => {
      if (localIndexPollRef.current) clearTimeout(localIndexPollRef.current);
      if (strmPollRef.current) clearTimeout(strmPollRef.current);
      if (scrapPollRef.current) clearTimeout(scrapPollRef.current);
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
            setMsg(
              codes != null
                ? `扫描完成 · 更新 ${updated} 前缀 · ${codes} 番号`
                : `扫描完成 · 更新 ${updated} 前缀`,
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
            onStatus('STRM 同步失败', 'warn');
          } else if (st.result) {
            const written = st.result.written ?? 0;
            const total = st.result.total ?? 0;
            setMsg(`STRM 同步完成 · 写入 ${written} · 合计 ${total}`);
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
    if (strmBusy || localIndexBusy || catalogBusy || scrapBusy) return;
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
            setMsg(`刮削库已写入元库 · ${written}/${total}`);
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
    if (strmBusy || localIndexBusy || catalogBusy || scrapBusy) return;
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

  useEffect(() => {
    if (catalogNav?.level !== 'regions') return;
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
        }
      } catch {
        /* ignore */
      }
      try {
        const st = await getScrapLibraryEmbedStatus();
        if (st.running) {
          setScrapBusy(true);
          setScrapPhase(st.phase || '同步中…');
          await pollScrapEmbedUntilDone();
        }
      } catch {
        /* ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resume poll only when opening regions
  }, [catalogNav?.level]);

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
    catalogNav?.level === 'prefix'
      ? catalogNav.prefix
      : catalogNav?.level === 'region'
        ? catalogNav.label
        : catalogNav?.level === 'regions'
          ? '七区目录'
          : '片商管理';
  const catalogPushBack =
    catalogNav?.level === 'prefix'
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

  const catalogScrollKey =
    catalogNav?.level === 'prefix'
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
      skipEnterAnimation={Boolean(catalogNav)}
      scrollKey={catalogScrollKey}
    >
      {catalogNav?.level === 'prefix' ? (
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
                      : 'Sehua · Bitmagnet 更新七区番号'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={localIndexBusy || catalogBusy || strmBusy || scrapBusy}
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
                      : '生成 STRM 供刮削获取元数据'}
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

          <p className="settings-group-label">刮削库向量</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削目录</span>
                  <span className="settings-nav__desc allow-select">
                    {scrapRoot
                      ? `media/${scrapRoot}`
                      : 'media/scrap-library（默认）'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={strmBusy || localIndexBusy || scrapBusy}
                  onClick={() => void openScrapBrowse()}
                >
                  选择
                </button>
              </div>
            </li>
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">同步向量数据库</span>
                  <span className="settings-nav__desc">
                    {scrapBusy
                      ? scrapPhase || '同步中…'
                      : 'NFO → 元库向量 + HNSW 索引'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={strmBusy || localIndexBusy || catalogBusy || scrapBusy}
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

          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      )}

      <AppCenterModal
        open={scanLogModal != null}
        title={
          scanLogModal === 'strm'
            ? 'STRM 同步日志'
            : scanLogModal === 'scrap'
              ? '刮削库同步日志'
              : '双库扫描日志'
        }
        onClose={() => setScanLogModal(null)}
        cardClassName="makers-manage__log-modal"
      >
        <ul className="makers-manage__scan-log-modal allow-select">
          {(scanLogModal === 'strm'
            ? strmLog
            : scanLogModal === 'scrap'
              ? scrapLog
              : localIndexLog
          ).map((line, i) => (
            <li key={`${scanLogModal}-${i}-${line}`}>{line}</li>
          ))}
          {(scanLogModal === 'strm'
            ? strmLog
            : scanLogModal === 'scrap'
              ? scrapLog
              : localIndexLog
          ).length === 0 ? (
            <li className="makers-manage__scan-log-modal--empty">暂无日志</li>
          ) : null}
        </ul>
      </AppCenterModal>
    </AppPush>
  );
}
