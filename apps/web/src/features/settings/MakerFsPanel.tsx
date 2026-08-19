'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, FolderTree, Plus, ScanSearch, Trash2 } from 'lucide-react';
import {
  addMakerFsRegionPrefix,
  buildMakerFs,
  fetchMakerFsManifest,
  fetchMakerFsPrefixCodes,
  fetchMakerFsRegion,
  fetchMakerFsRegions,
  fetchMakerFsStatus,
  materializeLibrary,
  fetchLibraryMaterializeStatus,
  putMakerFsPrefixRange,
  putMakerFsAutoDaily,
  removeMakerFsRegionPrefix,
  waitLibraryMaterialize,
  waitMakerFsBuild,
  type LibraryMaterializeStatus,
  type MakerFsBuildStatus,
  type MakerFsManifest,
  type MakerFsPrefixCodeItem,
  type MakerFsRegionCatalog,
  type MakerFsRegionSummary,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { CroppedCoverImg } from '@/components/cover/CroppedCoverImg';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { cn } from '@/lib/utils';
import {
  formatMakerFsCount,
  formatMakerFsIndexCode,
  groupMakerFsByMaker,
  indexesMakerFsActors,
  makerFsCodeSample,
  makerFsFormatKindLabel,
  makerFsPadEditable,
  makerFsGroupNoun,
  makerFsIndexLines,
  makerFsRegionMark,
  MAKER_FS_FALLBACK_REGIONS,
  notifyLibrarySynced,
  notifyMakerFsCatalogsSynced,
} from '@/lib/makerFsUi';

const CODES_PAGE = 60;
const STUCK_MS = 90_000;

function regionProgPct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((100 * done) / total)));
}

/** 合并构建状态：同一轮构建内 done/total 只增不减，避免双轮询乱序把进度条打回去 */
function mergeMakerFsStatus(
  prev: MakerFsBuildStatus | null,
  next: MakerFsBuildStatus,
): MakerFsBuildStatus {
  if (!next.running || !prev?.running) return next;
  const prevRp = prev.regionProgress || {};
  const nextRp = next.regionProgress || {};
  const merged: NonNullable<MakerFsBuildStatus['regionProgress']> = { ...nextRp };
  for (const [rid, n] of Object.entries(nextRp)) {
    const p = prevRp[rid];
    if (!p) continue;
    const done = Math.max(Number(p.done || 0), Number(n?.done || 0));
    const total = Math.max(Number(p.total || 0), Number(n?.total || 0));
    const covers = Math.max(Number(p.covers || 0), Number(n?.covers || 0));
    merged[rid] = {
      ...n,
      done,
      total,
      covers,
      // 前缀名可跳；进度数字保持单调
      currentPrefix: n?.currentPrefix || p.currentPrefix,
      updatedAt: n?.updatedAt || p.updatedAt,
    };
  }
  // 保留 prev 有、next 暂缺的分区进度（避免空对象闪断）
  for (const [rid, p] of Object.entries(prevRp)) {
    if (!merged[rid] && Number(p?.total || 0) > 0) {
      merged[rid] = p;
    }
  }
  return {
    ...next,
    prefixes: Math.max(Number(prev.prefixes || 0), Number(next.prefixes || 0)),
    prefixTotal: Math.max(Number(prev.prefixTotal || 0), Number(next.prefixTotal || 0)),
    covers: Math.max(Number(prev.covers || 0), Number(next.covers || 0)),
    regionProgress: merged,
  };
}

function isProgressStale(updatedAt: string | undefined, running: boolean): boolean {
  if (!running || !updatedAt) return false;
  const t = Date.parse(updatedAt);
  if (!Number.isFinite(t)) return false;
  return Date.now() - t > STUCK_MS;
}

type Stack =
  | { kind: 'hub' }
  | { kind: 'region'; region: MakerFsRegionSummary }
  | { kind: 'maker'; region: MakerFsRegionSummary; maker: string; catalog: MakerFsRegionCatalog }
  | {
      kind: 'prefix';
      region: MakerFsRegionSummary;
      maker: string;
      prefix: string;
      catalog: MakerFsRegionCatalog;
    }
  | {
      kind: 'prefix-format';
      region: MakerFsRegionSummary;
      maker: string;
      prefix: string;
      catalog: MakerFsRegionCatalog;
      pad: number;
    }
  | { kind: 'add-prefix'; region: MakerFsRegionSummary; catalog: MakerFsRegionCatalog };

function PrefixCodesBody({
  regionId,
  prefix,
}: {
  regionId: string;
  prefix: string;
}) {
  const { toast } = useOverlay();
  const [items, setItems] = useState<MakerFsPrefixCodeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pad, setPad] = useState(3);
  const [codeSample, setCodeSample] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadPage = useCallback(
    async (offset: number, append: boolean) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      try {
        const data = await fetchMakerFsPrefixCodes({
          prefix,
          region: regionId,
          offset,
          limit: CODES_PAGE,
        });
        if (!data) {
          if (!append) {
            setItems([]);
            setTotal(0);
          }
          return;
        }
        setTotal(data.total);
        if (typeof data.pad === 'number' && data.pad > 0) setPad(data.pad);
        if (data.codeSample) setCodeSample(String(data.codeSample));
        setItems((prev) => (append ? [...prev, ...(data.items || [])] : data.items || []));
      } catch (e) {
        toast(e instanceof Error ? e.message : '读取条目失败', 'error');
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [prefix, regionId, toast],
  );

  useEffect(() => {
    void loadPage(0, false);
  }, [loadPage]);

  const hasMore = items.length < total;
  const sample =
    codeSample ||
    makerFsCodeSample(prefix, regionId, { pad, codeFormat: 'digit_pad' });

  if (loading) return <p className="app-loading">加载中…</p>;
  if (items.length === 0) return <p className="app-empty">暂无已确认条目</p>;

  return (
    <div className="mfs-code-list">
      <div className="mfs-code-list__head">
        <span className="mfs-code-list__meta">
          {formatMakerFsCount(total)} 条 · 规范 {sample}
        </span>
      </div>
      <ul className="mfs-code-list__ul">
        {items.map((it) => {
          const code = formatMakerFsIndexCode(it.code, { prefix, pad });
          const { actors, title } = makerFsIndexLines(it, regionId);
          const actorsRegion = indexesMakerFsActors(regionId);
          const src = it.source === 'bit' ? 'bit' : 'sehua';
          return (
            <li key={code} className="mfs-code-row">
              <CroppedCoverImg
                src={it.coverUrl}
                srcs={it.coverUrls || undefined}
                region={regionId}
                layout="thumb"
                className="mfs-code-row__thumb"
                emptyClassName="mfs-code-row__thumb mfs-code-row__thumb--empty"
                frameClassName="mfs-code-row__thumb-frame"
                alt=""
              />
              <span className="mfs-code-row__main">
                <span className="mfs-code-row__head">
                  <span className="mfs-code-row__code allow-select">{code}</span>
                  <span
                    className={cn(
                      'mfs-code-row__src',
                      src === 'bit' ? 'mfs-code-row__src--bit' : 'mfs-code-row__src--sehua',
                    )}
                    title={src === 'bit' ? '来源：bitmagnet 补充' : '来源：sehua 主库'}
                  >
                    {src === 'bit' ? 'BIT' : 'SEHUA'}
                  </span>
                </span>
                {title ? (
                  <span className="mfs-code-row__title allow-select" title="标题">
                    {title}
                  </span>
                ) : null}
                {actorsRegion && actors ? (
                  <span className="mfs-code-row__actors allow-select" title="女优">
                    {actors}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
      {hasMore ? (
        <button
          type="button"
          className="mfs-load-more"
          disabled={loadingMore}
          onClick={() => void loadPage(items.length, true)}
        >
          {loadingMore ? '加载中…' : '加载更多'}
        </button>
      ) : (
        <p className="mfs-code-list__end">已全部加载</p>
      )}
    </div>
  );
}

export function MakerFsPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const { toast } = useOverlay();
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [manifest, setManifest] = useState<MakerFsManifest | null>(null);
  const [regions, setRegions] = useState<MakerFsRegionSummary[]>(MAKER_FS_FALLBACK_REGIONS);
  const [status, setStatus] = useState<MakerFsBuildStatus | null>(null);
  const [catalog, setCatalog] = useState<MakerFsRegionCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  const [addPrefix, setAddPrefix] = useState('');
  const [addBoardName, setAddBoardName] = useState('');
  const [scanningId, setScanningId] = useState<string | null>(null);
  const [libSync, setLibSync] = useState<LibraryMaterializeStatus | null>(null);

  const running = Boolean(status?.running);
  const autoDaily = Boolean(status?.autoDaily?.enabled);
  const autoDailyMeta = status?.autoDaily;

  const refreshHub = useCallback(async (opts?: { light?: boolean }) => {
    const light = Boolean(opts?.light);
    try {
      // 构建中只拉内存 status + 轻量 manifest，勿等 regions（磁盘忙会卡死「加载中」）
      const [m, s] = await Promise.all([
        fetchMakerFsManifest(),
        fetchMakerFsStatus(),
      ]);
      setManifest(m);
      setStatus((prev) => mergeMakerFsStatus(prev, s));
      let list =
        (m.regions?.length ? m.regions : null) || MAKER_FS_FALLBACK_REGIONS;
      setRegions(list);
      const text = s.running
        ? `构建中 ${s.prefixes || 0}/${s.prefixTotal || 0}`
        : m.ready
          ? '已就绪'
          : '未构建';
      onStatusRef.current(text, s.running ? 'mute' : m.ready ? 'ok' : 'warn');

      if (!light && !s.running) {
        try {
          const ov = await fetchMakerFsRegions();
          if (ov?.regions?.length) {
            setRegions(ov.regions);
          }
        } catch {
          /* 用 manifest / 兜底即可 */
        }
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取失败');
      onStatusRef.current('异常', 'warn');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      await refreshHub({ light: true });
      if (!cancelled) setLoading(false);
      // 进入后再补全 regions（空闲时）；构建中保持轻量
      if (!cancelled) void refreshHub();
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshHub]);

  // 从后台切回 / 面板一直挂着时，补一次拉齐（避免卡在中途快照）
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible') void refreshHub({ light: true });
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [refreshHub]);

  // 构建中：只轻量轮询 status（内存态）；勿狂刷 regions enrich（会堵死 API）
  const wasRunningRef = useRef(false);
  const waitAbortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => {
      waitAbortRef.current?.abort();
      waitAbortRef.current = null;
    };
  }, []);
  useEffect(() => {
    if (!running) {
      if (wasRunningRef.current) {
        wasRunningRef.current = false;
        void refreshHub();
      }
      return;
    }
    wasRunningRef.current = true;
    let inFlight = false;
    const t = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void (async () => {
        try {
          const s = await fetchMakerFsStatus();
          setStatus((prev) => mergeMakerFsStatus(prev, s));
          onStatusRef.current(
            `构建中 ${s.prefixes || 0}/${s.prefixTotal || 0}`,
            'mute',
          );
        } catch {
          /* ignore */
        } finally {
          inFlight = false;
        }
      })();
    }, 5000);
    return () => window.clearInterval(t);
  }, [running, refreshHub]);

  const openRegion = useCallback(async (region: MakerFsRegionSummary) => {
    setOpeningId(region.id);
    setMsg('');
    const ac = new AbortController();
    const kill = window.setTimeout(() => ac.abort(), 20000);
    try {
      const cat = await fetchMakerFsRegion(region.id, ac.signal);
      setCatalog(cat);
      setStack({ kind: 'region', region });
      if ((cat as { building?: boolean }).building) {
        toast('该区仍在构建，目录会陆续出现', 'info');
      }
    } catch (e) {
      const aborted =
        (e instanceof DOMException && e.name === 'AbortError') ||
        (e instanceof Error && /abort/i.test(e.message));
      const text = aborted
        ? '读取超时：构建占满磁盘，请稍后再进该区'
        : e instanceof Error
          ? e.message
          : '读取分区失败';
      setMsg(text);
      toast(text, 'error');
    } finally {
      window.clearTimeout(kill);
      setOpeningId(null);
    }
  }, [toast]);

  const reloadCatalog = useCallback(async (regionId: string) => {
    const cat = await fetchMakerFsRegion(regionId);
    setCatalog(cat);
    return cat;
  }, []);

  async function runBuild(opts: {
    catalogsOnly?: boolean;
    force?: boolean;
    skipFreshHours?: number;
    region?: string;
    prefix?: string;
    label: string;
  }) {
    setMsg('');
    const scanKey = opts.prefix
      ? `p:${opts.region || ''}:${opts.prefix}`
      : opts.region
        ? opts.region
        : '__all__';
    setScanningId(scanKey);
    try {
      // 仅启动请求短暂占 busy；等待过程中必须可下钻浏览
      setBusy(true);
      await buildMakerFs({
        catalogsOnly: opts.catalogsOnly,
        force: opts.force ?? Boolean(opts.prefix),
        skipFreshHours: opts.prefix ? 0 : opts.skipFreshHours,
        region: opts.region,
        prefix: opts.prefix,
        workers: opts.prefix ? 1 : undefined,
      });
      try {
        const s0 = await fetchMakerFsStatus();
        setStatus((prev) => mergeMakerFsStatus(prev, s0));
      } catch {
        /* 轮询 effect 会接上 */
      }
      setBusy(false);
      onStatusRef.current('构建中', 'mute');
      toast(`${opts.label}已开始`, 'info');

      waitAbortRef.current?.abort();
      const ac = new AbortController();
      waitAbortRef.current = ac;
      const st = await waitMakerFsBuild({
        signal: ac.signal,
        intervalMs: 5000,
        onTick: (s) => setStatus((prev) => mergeMakerFsStatus(prev, s)),
      });
      await refreshHub();
      if (stack.kind === 'region' || stack.kind === 'maker' || stack.kind === 'prefix') {
        await reloadCatalog(stack.region.id);
      }
      toast(st.message && st.message !== 'ok' ? st.message : `${opts.label}完成`, 'success');
      setMsg(`${opts.label}完成`);
      notifyMakerFsCatalogsSynced();
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      const text = e instanceof Error ? e.message : '构建失败';
      setMsg(text);
      toast(text, 'error');
      await refreshHub();
    } finally {
      setScanningId(null);
      setBusy(false);
    }
  }

  async function runLibrarySync(opts?: { region?: string; label?: string }) {
    const label = opts?.label || '同步本地片库';
    setMsg('');
    try {
      setBusy(true);
      let started: LibraryMaterializeStatus;
      let alreadyRunning = false;
      try {
        started = await materializeLibrary({ region: opts?.region });
      } catch (e) {
        const text = e instanceof Error ? e.message : '同步失败';
        if (!/正在进行中/.test(text)) throw e;
        // 已有任务：跟进度；状态已空闲则强制抢占僵死 running 标志
        const cur = await fetchLibraryMaterializeStatus();
        if (cur.running) {
          const msg = String(cur.message || '');
          const updated = Date.parse(String(cur.updatedAt || cur.startedAt || ''));
          const ageSec = Number.isFinite(updated)
            ? (Date.now() - updated) / 1000
            : 0;
          // queued 超过 90s 仍未开跑 → 强制抢占
          if (msg === 'queued' && ageSec >= 90) {
            started = await materializeLibrary({
              region: opts?.region,
              force: true,
            });
          } else {
            started = cur;
            alreadyRunning = true;
          }
        } else {
          started = await materializeLibrary({
            region: opts?.region,
            force: true,
          });
        }
      }
      setLibSync(started);
      onStatusRef.current('同步片库中', 'mute');
      toast(alreadyRunning ? `${label}进行中，继续等待…` : `${label}已开始`, 'info');
      const st = await waitLibraryMaterialize({
        expectStartedAt: started.startedAt,
        onTick: (s) => setLibSync(s),
      });
      const detail = `写入 ${st.written ?? 0} · 更新 ${st.updated ?? 0} · 跳过 ${st.skipped ?? 0}`;
      toast(`${label}完成 · ${detail}`, 'success');
      setMsg(`${label}完成 · ${detail}`);
      notifyLibrarySynced();
      await refreshHub();
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      const text = e instanceof Error ? e.message : '同步失败';
      setMsg(text);
      toast(text, 'error');
    } finally {
      setBusy(false);
      setLibSync(null);
    }
  }

  const makersRegionId =
    stack.kind === 'region'
      ? stack.region.id
      : stack.kind === 'maker' ||
          stack.kind === 'prefix' ||
          stack.kind === 'add-prefix'
        ? stack.region.id
        : catalog?.id;
  const makers = useMemo(
    () => groupMakerFsByMaker(catalog?.prefixes, makersRegionId),
    [catalog, makersRegionId],
  );
  const groupNoun = makerFsGroupNoun(makersRegionId);

  const hubBody = (
    <div className="mfs-panel">
      <ul className="settings-group mfs-status-card">
        <li>
          <div className="settings-nav mfs-status-row">
            <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
              <FolderTree size={15} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">索引状态</span>
              <span className="settings-nav__desc">
                {running
                  ? `${status?.prefixes || 0}/${status?.prefixTotal || 0} 前缀 · ${formatMakerFsCount(status?.covers)} 条${
                      status?.currentPrefix ? ` · ${status.currentPrefix}` : ''
                    }`
                  : manifest?.ready
                    ? `前缀 ${formatMakerFsCount(manifest.prefixCount)} · 封面 ${formatMakerFsCount(manifest.coverCount)}`
                    : '七大路径尚未构建'}
              </span>
            </span>
            <span
              className={cn(
                'mfs-status-pill',
                running
                  ? 'mfs-status-pill--run'
                  : manifest?.ready
                    ? 'mfs-status-pill--ok'
                    : 'mfs-status-pill--warn',
              )}
            >
              {running ? '构建中' : manifest?.ready ? '已就绪' : '未构建'}
            </span>
          </div>
        </li>
        <li>
          <label className="settings-toggle-row mfs-auto-daily">
            <span className="settings-nav__main">
              <span className="settings-nav__title">每天自动增量</span>
              <span className="settings-nav__desc">
                {autoDaily
                  ? autoDailyMeta?.lastRunDate
                    ? `已开启 · 上次 ${autoDailyMeta.lastRunDate}`
                    : autoDailyMeta?.starting
                      ? '已开启 · 正在补跑…'
                      : '已开启 · 约 00:05 增量索引并更新本地目录'
                  : '关闭 · 开启后每日增量索引并同步片库'}
              </span>
            </span>
            <input
              type="checkbox"
              className="scrape-src-card__switch"
              checked={autoDaily}
              disabled={busy}
              onChange={(e) => {
                const on = e.target.checked;
                void (async () => {
                  setBusy(true);
                  try {
                    const cfg = await putMakerFsAutoDaily(on);
                    setStatus((prev) =>
                      prev
                        ? { ...prev, autoDaily: cfg }
                        : ({
                            running: false,
                            autoDaily: cfg,
                          } as MakerFsBuildStatus),
                    );
                    toast(
                      on
                        ? cfg.starting
                          ? '已开启，正在补跑今日增量…'
                          : '已开启每天自动增量'
                        : '已关闭每天自动增量',
                      'success',
                    );
                  } catch (err) {
                    toast(
                      err instanceof Error ? err.message : '保存失败',
                      'error',
                    );
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            />
          </label>
        </li>
      </ul>

      <p className="settings-group-label">七大路径</p>
      <ul className="settings-group mfs-region-list">
        {regions.map((r) => {
          const scanning = scanningId === r.id;
          const rp = status?.regionProgress?.[r.id];
          const total = Number(rp?.total || 0);
          const done = Number(rp?.done || 0);
          const showBar =
            running && total > 0 && (!status?.region || status.region === r.id);
          const pct = regionProgPct(done, total);
          const cur = String(rp?.currentPrefix || '').trim();
          const stuck =
            showBar &&
            isProgressStale(rp?.updatedAt || status?.updatedAt, running && done < total);
          const active = showBar && done < total && (Boolean(cur) || scanning);
          return (
            <li key={r.id}>
              <div
                className={cn(
                  'mfs-region-row',
                  showBar && 'mfs-region-row--prog',
                )}
              >
                <div className="mfs-region-row__top">
                  <button
                    type="button"
                    className="mfs-region-row__main"
                    disabled={openingId === r.id}
                    onClick={() => void openRegion(r)}
                  >
                    <span className="mfs-region-mark" aria-hidden>
                      {makerFsRegionMark(r.id)}
                    </span>
                    <span className="mfs-region-row__text">
                      <span className="settings-nav__title">{r.label}</span>
                      <span className="settings-nav__desc">
                        {makerFsGroupNoun(r.id)} {formatMakerFsCount(r.makerCount)} · 前缀{' '}
                        {formatMakerFsCount(r.prefixCount)} · 条目{' '}
                        {formatMakerFsCount(
                          Math.max(
                            Number(r.codeCount || 0),
                            showBar ? Number(rp?.covers || 0) : 0,
                          ),
                        )}
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'mfs-scan-chip',
                      (scanning || active) && 'is-scanning',
                    )}
                    disabled={busy || running}
                    onClick={() =>
                      void runBuild({
                        force: true,
                        region: r.id,
                        label: `扫描「${r.label}」`,
                      })
                    }
                  >
                    <ScanSearch size={13} strokeWidth={2.25} aria-hidden />
                    {scanning || active ? '扫描中' : '扫描'}
                  </button>
                  <button
                    type="button"
                    className="mfs-region-chev"
                    disabled={openingId === r.id}
                    aria-label={`打开${r.label}`}
                    onClick={() => void openRegion(r)}
                  >
                    <ChevronRight size={17} strokeWidth={2.25} aria-hidden />
                  </button>
                </div>
                {showBar ? (
                  <div className="mfs-region-prog">
                    <div
                      className={cn(
                        'mfs-progress-bar mfs-region-prog__bar',
                        stuck && 'is-stuck',
                      )}
                      role="progressbar"
                      aria-valuenow={pct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`${r.label} 索引进度`}
                    >
                      <div
                        className="mfs-progress-bar__fill"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div
                      className={cn(
                        'mfs-region-prog__meta',
                        stuck && 'is-stuck',
                      )}
                    >
                      {done}/{total} 前缀 · {pct}%
                      {cur ? ` · ${cur}` : done < total ? ' · …' : ' · 完成'}
                      {stuck ? ' · 可能卡住' : ''}
                    </div>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>

      <p className="settings-group-label">构建操作</p>
      <ul className="settings-group mfs-actions">
        <li>
          <button
            type="button"
            className="settings-nav"
            disabled={busy || running || Boolean(libSync?.running)}
            onClick={() => void runLibrarySync()}
          >
            <span className="mfs-action-dot mfs-action-dot--sync" aria-hidden />
            <span className="settings-nav__main">
              <span className="settings-nav__title">同步本地片库</span>
              <span className="settings-nav__desc">
                {libSync?.running
                  ? (() => {
                      const done = libSync.done ?? 0;
                      const total = libSync.total ?? 0;
                      const sk = libSync.skipped ?? 0;
                      const up = libSync.updated ?? 0;
                      const wr = libSync.written ?? 0;
                      const rm = libSync.removed ?? 0;
                      const msg = String(libSync.message || '');
                      if (/收集|准备|queued/i.test(msg)) {
                        return msg === 'queued' ? '收集索引…' : msg;
                      }
                      if (/清理/.test(msg)) {
                        return msg;
                      }
                      const cur = libSync.currentCode
                        ? ` · ${libSync.currentCode}`
                        : '';
                      return `同步中 ${done}/${total} · 跳过 ${sk} · 更新 ${up} · 新写 ${wr} · 清理 ${rm}${cur}`;
                    })()
                  : '严格对齐索引：每番号仅 {番号}.strm，多余文件/目录一律删除'}
              </span>
            </span>
            <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
          </button>
        </li>
        <li>
          <button
            type="button"
            className="settings-nav"
            disabled={busy || running}
            onClick={() =>
              void runBuild({ skipFreshHours: 24, label: '增量扫库' })
            }
          >
            <span className="mfs-action-dot mfs-action-dot--incr" aria-hidden />
            <span className="settings-nav__main">
              <span className="settings-nav__title">增量扫库</span>
              <span className="settings-nav__desc">已有索引只补漏（色花主、Bit 补），空缺才全扫</span>
            </span>
            <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
          </button>
        </li>
        <li>
          <button
            type="button"
            className="settings-nav"
            disabled={busy || running}
            onClick={() => void runBuild({ force: true, label: '全量重扫' })}
          >
            <span className="mfs-action-dot mfs-action-dot--full" aria-hidden />
            <span className="settings-nav__main">
              <span className="settings-nav__title">全量重扫</span>
              <span className="settings-nav__desc">强制重建全部七区（色花主、Bit 补）</span>
            </span>
            <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
          </button>
        </li>
      </ul>
    </div>
  );

  let push: ReactNode = null;

  if (stack.kind === 'region' && catalog) {
    push = (
      <AppPush title={stack.region.label} onBack={() => setStack({ kind: 'hub' })}>
        <div className="mfs-panel">
          <ul className="settings-group mfs-meta-card">
            <li>
              <div className="mfs-meta-row">
                <span className="mfs-region-mark" aria-hidden>
                  {makerFsRegionMark(stack.region.id)}
                </span>
                <span className="mfs-meta-row__main">
                  <span className="mfs-meta-row__path allow-select">
                    {catalog.navPath || stack.region.navPath || catalog.id}
                  </span>
                  <span className="mfs-meta-row__stats">
                    {groupNoun} {formatMakerFsCount(catalog.makerCount)} · 前缀{' '}
                    {formatMakerFsCount(catalog.prefixCount)} · 条目{' '}
                    {formatMakerFsCount(catalog.codeCount)}
                  </span>
                </span>
              </div>
            </li>
          </ul>
          <div className="mfs-toolbar">
            <button
              type="button"
              className="mfs-toolbar__btn mfs-toolbar__btn--ghost"
              disabled={busy || running}
              onClick={() =>
                void runBuild({
                  force: true,
                  region: stack.region.id,
                  label: `扫描「${stack.region.label}」`,
                })
              }
            >
              <ScanSearch size={15} strokeWidth={2.25} aria-hidden />
              扫描本区
            </button>
            <button
              type="button"
              className="mfs-toolbar__btn mfs-toolbar__btn--primary"
              onClick={() =>
                setStack({ kind: 'add-prefix', region: stack.region, catalog })
              }
            >
              <Plus size={15} strokeWidth={2.25} aria-hidden />
              加前缀
            </button>
          </div>
          <p className="settings-group-label">{groupNoun}</p>
          {makers.length === 0 ? (
            <p className="app-empty">暂无{groupNoun}，请先扫库并同步本地片库</p>
          ) : (
            <ul className="settings-group mfs-drill-list">
              {makers.map((g) => (
                <li key={g.maker}>
                  <button
                    type="button"
                    className="settings-nav"
                    onClick={() =>
                      setStack({
                        kind: 'maker',
                        region: stack.region,
                        maker: g.maker,
                        catalog,
                      })
                    }
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{g.maker}</span>
                      <span className="settings-nav__desc">
                        {g.prefixCount} 前缀 · {formatMakerFsCount(g.codeCount)} 条
                      </span>
                    </span>
                    <ChevronRight className="settings-nav__chev" size={17} strokeWidth={2.25} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <AppMsg allowSelect onDismiss={() => setMsg('')}>
            {msg}
          </AppMsg>
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'maker') {
    const group = groupMakerFsByMaker(stack.catalog.prefixes, stack.region.id).find(
      (g) => g.maker === stack.maker,
    );
    push = (
      <AppPush
        title={stack.maker}
        onBack={() => setStack({ kind: 'region', region: stack.region })}
      >
        <div className="mfs-panel">
          <ul className="settings-group mfs-drill-list">
            {(group?.prefixes || []).map((p) => {
              const padEditable = makerFsPadEditable(p);
              const pad = Math.max(1, Math.min(8, Number(p.pad || 3)));
              const sample = makerFsCodeSample(p.prefix, stack.region.id, {
                pad,
                codeSample: p.codeSample,
                codeFormat: p.codeFormat,
                padEditable: p.padEditable,
              });
              const scanKey = `p:${stack.region.id}:${p.prefix}`;
              const scanning = scanningId === scanKey;
              return (
              <li key={p.prefix}>
                <div className="settings-nav mfs-prefix-row">
                  <button
                    type="button"
                    className="mfs-prefix-row__main"
                    onClick={() =>
                      setStack({
                        kind: 'prefix',
                        region: stack.region,
                        maker: stack.maker,
                        prefix: p.prefix,
                        catalog: stack.catalog,
                      })
                    }
                  >
                    <span className="settings-nav__title allow-select">{p.prefix}</span>
                    <span className="settings-nav__desc">
                      {p.custom ? '自定义 · ' : ''}
                      {formatMakerFsCount(p.codeCount)} 条 · 规范 {sample}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'mfs-scan-chip',
                      scanning && 'is-scanning',
                    )}
                    disabled={busy || Boolean(scanningId)}
                    aria-label={`扫描 ${p.prefix}`}
                    onClick={() => {
                      void runBuild({
                        region: stack.region.id,
                        prefix: p.prefix,
                        force: true,
                        label: `扫描 ${p.prefix}`,
                      });
                    }}
                  >
                    <ScanSearch size={14} strokeWidth={2.25} aria-hidden />
                    {scanning ? '扫描中' : '扫描'}
                  </button>
                  {padEditable ? (
                    <button
                      type="button"
                      className="mfs-prefix-format"
                      disabled={busy}
                      aria-label={`编辑 ${p.prefix} 规范位数`}
                      onClick={() =>
                        setStack({
                          kind: 'prefix-format',
                          region: stack.region,
                          maker: stack.maker,
                          prefix: p.prefix,
                          catalog: stack.catalog,
                          pad,
                        })
                      }
                    >
                      {pad}位
                    </button>
                  ) : null}
                  {p.custom ? (
                    <button
                      type="button"
                      className="mfs-prefix-del"
                      disabled={busy}
                      aria-label="删除前缀"
                      onClick={() => {
                        void (async () => {
                          setBusy(true);
                          try {
                            const cat = await removeMakerFsRegionPrefix({
                              regionId: stack.region.id,
                              prefix: p.prefix,
                            });
                            setCatalog(cat);
                            setStack({
                              kind: 'maker',
                              region: stack.region,
                              maker: stack.maker,
                              catalog: cat,
                            });
                            toast(`已删除 ${p.prefix}`, 'success');
                          } catch (e) {
                            toast(e instanceof Error ? e.message : '删除失败', 'error');
                          } finally {
                            setBusy(false);
                          }
                        })();
                      }}
                    >
                      <Trash2 size={15} strokeWidth={2.25} />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="mfs-region-chev"
                    aria-label={`打开 ${p.prefix}`}
                    onClick={() =>
                      setStack({
                        kind: 'prefix',
                        region: stack.region,
                        maker: stack.maker,
                        prefix: p.prefix,
                        catalog: stack.catalog,
                      })
                    }
                  >
                    <ChevronRight size={17} strokeWidth={2.25} aria-hidden />
                  </button>
                </div>
              </li>
              );
            })}
          </ul>
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'prefix-format') {
    const backToMaker = () =>
      setStack({
        kind: 'maker',
        region: stack.region,
        maker: stack.maker,
        catalog: stack.catalog,
      });
    const rowMeta = stack.catalog.prefixes?.find((x) => x.prefix === stack.prefix);
    const padEditable = makerFsPadEditable({
      prefix: stack.prefix,
      codeFormat: rowMeta?.codeFormat,
      padEditable: rowMeta?.padEditable,
    });
    // 非 digit_pad / 不可编辑：只展示配置检测出的规范样例
    if (!padEditable) {
      const sample = makerFsCodeSample(stack.prefix, stack.region.id, {
        codeSample: rowMeta?.codeSample,
        codeFormat: rowMeta?.codeFormat,
      });
      push = (
        <AppPush title="规范格式" onBack={backToMaker}>
          <div className="mfs-panel">
            <ul className="settings-group">
              <li>
                <div className="settings-nav">
                  <span className="settings-nav__main">
                    <span className="settings-nav__title allow-select">{stack.prefix}</span>
                    <span className="settings-nav__desc allow-select">
                      {makerFsFormatKindLabel(rowMeta?.codeFormat)} · {sample}
                    </span>
                  </span>
                </div>
              </li>
            </ul>
          </div>
        </AppPush>
      );
    } else {
    const sample = makerFsCodeSample(stack.prefix, stack.region.id, {
      pad: stack.pad,
    });
    push = (
      <AppPush
        title="规范格式"
        onBack={backToMaker}
      >
        <div className="mfs-panel">
          <ul className="settings-group">
            <li>
              <div className="settings-nav">
                <span className="settings-nav__main">
                  <span className="settings-nav__title allow-select">{stack.prefix}</span>
                  <span className="settings-nav__desc">
                    当前规范 {sample} · 抽码按此位数截断
                  </span>
                </span>
              </div>
            </li>
          </ul>
          <p className="settings-group-label">数字位数</p>
          <ul className="settings-group mfs-pad-picks">
            {[2, 3, 4, 5, 6].map((n) => (
              <li key={n}>
                <button
                  type="button"
                  className={cn(
                    'settings-nav',
                    n === stack.pad && 'settings-nav--active',
                  )}
                  disabled={busy}
                  onClick={() => {
                    void (async () => {
                      setBusy(true);
                      try {
                        const rng = await putMakerFsPrefixRange({
                          prefix: stack.prefix,
                          pad: n,
                          lock: true,
                          region: stack.region.id,
                        });
                        const pad = Math.max(1, Math.min(8, Number(rng.pad || n)));
                        const codeSample = makerFsCodeSample(stack.prefix, stack.region.id, {
                          pad,
                          codeSample: rng.sample,
                        });
                        const cat: MakerFsRegionCatalog = {
                          ...stack.catalog,
                          prefixes: (stack.catalog.prefixes || []).map((it) =>
                            it.prefix === stack.prefix
                              ? {
                                  ...it,
                                  pad,
                                  padLocked: true,
                                  codeSample,
                                }
                              : it,
                          ),
                        };
                        setCatalog(cat);
                        setStack({
                          kind: 'prefix-format',
                          region: stack.region,
                          maker: stack.maker,
                          prefix: stack.prefix,
                          catalog: cat,
                          pad,
                        });
                        toast(`已设为 ${pad} 位 · ${codeSample}`, 'success');
                      } catch (e) {
                        toast(e instanceof Error ? e.message : '保存失败', 'error');
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{n} 位</span>
                    <span className="settings-nav__desc allow-select">
                      {makerFsCodeSample(stack.prefix, stack.region.id, { pad: n })}
                    </span>
                  </span>
                  {n === stack.pad ? (
                    <span className="mfs-pad-check" aria-hidden>
                      ✓
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </AppPush>
    );
    }
  } else if (stack.kind === 'prefix') {
    push = (
      <AppPush
        title={stack.prefix}
        onBack={() =>
          setStack({
            kind: 'maker',
            region: stack.region,
            maker: stack.maker,
            catalog: stack.catalog,
          })
        }
      >
        <div className="mfs-panel">
          <PrefixCodesBody regionId={stack.region.id} prefix={stack.prefix} />
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'add-prefix') {
    push = (
      <AppPush
        title="添加前缀"
        onBack={() => setStack({ kind: 'region', region: stack.region })}
      >
        <div className="mfs-panel">
          <section className="app-section mfs-add-form">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">前缀</span>
                <input
                  className="allow-select"
                  value={addPrefix}
                  onChange={(e) => setAddPrefix(e.target.value.toUpperCase())}
                  placeholder="如 SONE"
                  autoCapitalize="characters"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </label>
              <label className="app-field">
                <span className="app-label">
                  {makerFsGroupNoun(stack.region.id)}名
                </span>
                <input
                  className="allow-select"
                  value={addBoardName}
                  onChange={(e) => setAddBoardName(e.target.value)}
                  placeholder={
                    stack.region.id === 'fc2' ? '可选，作者名；空则未分类' : '可选'
                  }
                />
              </label>
            </div>
          </section>
          <div className="mfs-toolbar">
            <button
              type="button"
              className="mfs-toolbar__btn mfs-toolbar__btn--primary"
              style={{ flex: 1 }}
              disabled={busy || !addPrefix.trim()}
              onClick={() => {
                void (async () => {
                  setBusy(true);
                  try {
                    const cat = await addMakerFsRegionPrefix({
                      regionId: stack.region.id,
                      prefix: addPrefix.trim(),
                      boardName: addBoardName.trim() || undefined,
                    });
                    setCatalog(cat);
                    setAddPrefix('');
                    setAddBoardName('');
                    toast('已添加前缀', 'success');
                    setStack({ kind: 'region', region: stack.region });
                  } catch (e) {
                    toast(e instanceof Error ? e.message : '添加失败', 'error');
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              保存
            </button>
          </div>
        </div>
      </AppPush>
    );
  }

  return (
    <>
      <AppPush title="本地索引" onBack={onBack}>
        {loading ? <p className="app-loading">加载中…</p> : hubBody}
        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </AppPush>
      {push}
    </>
  );
}
