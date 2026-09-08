'use client';

import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  CloudDownload,
  Folder,
  FolderOpen,
  KeyRound,
  LoaderCircle,
  QrCode,
  RefreshCw,
} from 'lucide-react';
import {
  clearP115Tasks,
  completeP115Qrcode,
  getP115,
  getP115Status,
  listP115Folders,
  listP115Tasks,
  pollP115Qrcode,
  putP115,
  startP115Qrcode,
  validateP115,
  getSubtitleSettings,
  putSubtitleSettings,
  testAssrtToken,
  type P115ClearMode,
  type P115Config,
  type P115FolderItem,
  type P115QrStart,
  type P115SaveSource,
  type P115TargetFolder,
  type P115Task,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { cn } from '@/lib/utils';
import {
  cacheFromP115Config,
  emptyP115SubsFolder,
  getP115PanelCache,
  isP115PanelCacheFresh,
  patchP115PanelCache,
  setP115PanelCache,
  type P115PanelTab,
} from './p115PanelCache';

type Tab = P115PanelTab;
type BrowseTarget = P115SaveSource | 'subs';

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'overview', label: '概览' },
  { key: 'config', label: '配置' },
  { key: 'tasks', label: '任务' },
];

const SAVE_SOURCES: Array<{
  key: P115SaveSource;
  label: string;
  desc: string;
}> = [
  { key: 'warehouse', label: '仓库', desc: '先最近接受 → 再进本目录' },
  { key: 'movie', label: '电影', desc: '影视·电影 · 先最近接受 → 再进本目录' },
  { key: 'tv', label: '电视剧', desc: '影视·剧集 · 先最近接受 → 再进本目录' },
  { key: 'makers', label: '片商', desc: '片商 · 先最近接受 → 再进分区目录' },
];

function emptyTargets(): Record<P115SaveSource, P115TargetFolder> {
  return {
    warehouse: { folderCid: '0', folderName: '' },
    movie: { folderCid: '0', folderName: '' },
    tv: { folderCid: '0', folderName: '' },
    makers: { folderCid: '0', folderName: '' },
  };
}

function normalizeTargets(
  data: Partial<P115Config> | null | undefined,
): Record<P115SaveSource, P115TargetFolder> {
  const base = emptyTargets();
  const legacyCid = String(data?.folderCid || '0') || '0';
  const legacyName = String(data?.folderName || '');
  const legacyMedia = data?.targets?.media as P115TargetFolder | undefined;
  for (const row of SAVE_SOURCES) {
    const t = data?.targets?.[row.key];
    if (t?.folderCid != null || t?.folderName != null) {
      base[row.key] = {
        folderCid: String(t.folderCid || legacyCid || '0') || '0',
        folderName: String(t.folderName || ''),
      };
      continue;
    }
    if (
      (row.key === 'movie' || row.key === 'tv') &&
      (legacyMedia?.folderCid != null || legacyMedia?.folderName != null)
    ) {
      base[row.key] = {
        folderCid: String(legacyMedia.folderCid || legacyCid || '0') || '0',
        folderName: String(legacyMedia.folderName || ''),
      };
      continue;
    }
    base[row.key] = {
      folderCid: legacyCid,
      folderName: legacyName,
    };
  }
  return base;
}

function folderDisplayName(t: P115TargetFolder) {
  return t.folderName || (t.folderCid === '0' ? '根目录' : '自定义目录');
}

function formatQuota(remain: number | null | undefined, total: number | null | undefined) {
  if (remain == null && total == null) return null;
  if (remain != null && total != null) return `${remain} / ${total}`;
  if (remain != null) return String(remain);
  return String(total);
}

function formatBytes(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n) || n < 0) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  const digits = v >= 100 || i < 2 ? 0 : v >= 10 ? 1 : 2;
  const text = Number.isInteger(v) || digits === 0 ? String(Math.round(v)) : v.toFixed(digits);
  return `${text} ${units[i]}`;
}

function formatTaskTime(ts: number | null | undefined) {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return '';
  const ms = ts < 1e12 ? ts * 1000 : ts;
  try {
    return new Date(ms).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

function taskTone(status: number): 'ok' | 'warn' | 'run' | 'mute' {
  if (status === 2) return 'ok';
  if (status < 0) return 'warn';
  if (status === 1) return 'run';
  return 'mute';
}

type TaskFilter = 'run' | 'failed' | 'done';

const TASK_FILTERS: Array<{ key: TaskFilter; label: string }> = [
  { key: 'run', label: '下载中' },
  { key: 'failed', label: '已失败' },
  { key: 'done', label: '已完成' },
];

function taskFilterOf(status: number): TaskFilter {
  if (status === 2) return 'done';
  if (status < 0) return 'failed';
  return 'run';
}

function isHashLikeName(name: string, infoHash?: string) {
  const n = String(name || '').trim();
  if (!n) return false;
  const h = String(infoHash || '').trim();
  if (h && n.toLowerCase() === h.toLowerCase()) return true;
  return /^[a-f0-9]{32,40}$/i.test(n);
}

function formatHashShort(raw: string) {
  const h = raw.trim();
  if (h.length <= 14) return h;
  return `${h.slice(0, 8)}…${h.slice(-6)}`;
}

function taskDisplay(t: P115Task) {
  const raw = String(t.name || '').trim() || '未命名任务';
  if (isHashLikeName(raw, t.infoHash)) {
    const full = String(t.infoHash || raw).trim();
    return {
      title: '磁力任务',
      subtitle: formatHashShort(full),
      hashFull: full,
      isHash: true,
    };
  }
  return { title: raw, subtitle: null, hashFull: null, isHash: false };
}

export function P115Panel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const cached = getP115PanelCache();
  const [tab, setTab] = useState<Tab>(() => cached?.tab ?? 'config');
  const [configured, setConfigured] = useState(() => Boolean(cached?.configured));
  const [hint, setHint] = useState(() => cached?.hint ?? '');
  const [cookie, setCookie] = useState('');
  const [showCookieEdit, setShowCookieEdit] = useState(() => !cached?.configured);
  const [targets, setTargets] = useState<Record<P115SaveSource, P115TargetFolder>>(
    () => cached?.targets ?? emptyTargets(),
  );
  const [subsFolder, setSubsFolder] = useState<P115TargetFolder>(
    () => cached?.subsFolder ?? emptyP115SubsFolder(),
  );
  const [subsLayered, setSubsLayered] = useState(
    () => cached?.subsLayered ?? true,
  );
  const [assrtToken, setAssrtToken] = useState('');
  const [assrtHint, setAssrtHint] = useState('');
  const [assrtConfigured, setAssrtConfigured] = useState(false);
  const [assrtFromEnv, setAssrtFromEnv] = useState(false);
  const [assrtShowEdit, setAssrtShowEdit] = useState(true);
  const [browseSource, setBrowseSource] = useState<BrowseTarget>('warehouse');
  const [quota, setQuota] = useState<number | null>(() => cached?.quota ?? null);
  const [quotaTotal, setQuotaTotal] = useState<number | null>(() => cached?.quotaTotal ?? null);
  const [quotaError, setQuotaError] = useState(() => cached?.quotaError ?? '');
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [spaceUsedText, setSpaceUsedText] = useState(() => cached?.spaceUsedText ?? '');
  const [spaceTotalText, setSpaceTotalText] = useState(() => cached?.spaceTotalText ?? '');
  const [spaceRemainText, setSpaceRemainText] = useState(() => cached?.spaceRemainText ?? '');
  const [spaceUsed, setSpaceUsed] = useState<number | null>(() => cached?.spaceUsed ?? null);
  const [spaceTotal, setSpaceTotal] = useState<number | null>(() => cached?.spaceTotal ?? null);
  const [showBrowser, setShowBrowser] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [folderPath, setFolderPath] = useState<P115FolderItem[]>([]);
  const [folders, setFolders] = useState<P115FolderItem[]>([]);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [tasks, setTasks] = useState<P115Task[]>(() => cached?.tasks ?? []);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState(() => cached?.tasksError ?? '');
  const [tasksLoaded, setTasksLoaded] = useState(() => Boolean(cached?.tasksLoaded));
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('run');
  const [clearing, setClearing] = useState<P115ClearMode | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [qrBusy, setQrBusy] = useState(false);
  const [qrSession, setQrSession] = useState<P115QrStart | null>(null);
  const [qrStatusLabel, setQrStatusLabel] = useState('');
  const qrGenRef = useRef(0);

  function applyQuotaInfo(
    data: Partial<P115Config> & {
      quota?: number | null;
      quotaTotal?: number | null;
      quotaError?: string;
    },
  ) {
    const nextQuota = 'quota' in data || 'quotaTotal' in data ? data.quota ?? null : undefined;
    const nextQuotaTotal =
      'quota' in data || 'quotaTotal' in data ? data.quotaTotal ?? null : undefined;
    const nextQuotaError = data.quotaError
      ? data.quotaError
      : 'quota' in data
        ? ''
        : undefined;

    if (nextQuota !== undefined) setQuota(nextQuota);
    if (nextQuotaTotal !== undefined) setQuotaTotal(nextQuotaTotal);
    if (nextQuotaError !== undefined) setQuotaError(nextQuotaError);

    if (data.spaceUsedText != null) setSpaceUsedText(String(data.spaceUsedText || ''));
    if (data.spaceTotalText != null) setSpaceTotalText(String(data.spaceTotalText || ''));
    if (data.spaceRemainText != null) setSpaceRemainText(String(data.spaceRemainText || ''));
    if ('spaceUsed' in data) setSpaceUsed(data.spaceUsed ?? null);
    if ('spaceTotal' in data) setSpaceTotal(data.spaceTotal ?? null);

    patchP115PanelCache({
      ...(nextQuota !== undefined ? { quota: nextQuota } : {}),
      ...(nextQuotaTotal !== undefined ? { quotaTotal: nextQuotaTotal } : {}),
      ...(nextQuotaError !== undefined ? { quotaError: nextQuotaError } : {}),
      ...(data.spaceUsedText != null
        ? { spaceUsedText: String(data.spaceUsedText || '') }
        : {}),
      ...(data.spaceTotalText != null
        ? { spaceTotalText: String(data.spaceTotalText || '') }
        : {}),
      ...(data.spaceRemainText != null
        ? { spaceRemainText: String(data.spaceRemainText || '') }
        : {}),
      ...('spaceUsed' in data ? { spaceUsed: data.spaceUsed ?? null } : {}),
      ...('spaceTotal' in data ? { spaceTotal: data.spaceTotal ?? null } : {}),
    });
  }

  function applyConfig(data: P115Config, opts?: { forceOverview?: boolean }) {
    const nextConfigured = Boolean(data.configured);
    const nextHint = data.cookieHint || '';
    const nextTargets = normalizeTargets(data);
    const nextSubs = data.subsFolder || emptyP115SubsFolder();
    const nextLayered = data.subsLayered ?? true;
    setConfigured(nextConfigured);
    setHint(nextHint);
    setTargets(nextTargets);
    setSubsFolder(nextSubs);
    setSubsLayered(nextLayered);
    setCookie('');
    setShowCookieEdit(!nextConfigured);
    applyQuotaInfo(data);
    onStatus(nextConfigured ? '已就绪' : '未配置', nextConfigured ? 'ok' : 'warn');
    if (!nextConfigured) {
      setTab('config');
      setTasks([]);
      setTasksLoaded(false);
      setTasksError('');
      setShowBrowser(false);
      setP115PanelCache({
        configured: false,
        hint: nextHint,
        targets: nextTargets,
        subsFolder: nextSubs,
        subsLayered: nextLayered,
        tab: 'config',
        quota: null,
        quotaTotal: null,
        quotaError: '',
        spaceUsedText: '',
        spaceTotalText: '',
        spaceRemainText: '',
        spaceUsed: null,
        spaceTotal: null,
        tasks: [],
        tasksLoaded: false,
        tasksError: '',
      });
      return;
    }
    if (opts?.forceOverview) setTab('overview');
    cacheFromP115Config(data, nextTargets, getP115PanelCache());
  }

  async function refreshStatus(opts?: { quiet?: boolean }) {
    const quiet = Boolean(opts?.quiet) && (quota != null || spaceUsed != null);
    if (!quiet) {
      setQuotaLoading(true);
      setQuotaError('');
    }
    try {
      const status = await getP115Status();
      applyQuotaInfo(status);
      if (status.configured) onStatus('已就绪', 'ok');
    } catch (e) {
      if (!quiet) setQuotaError(e instanceof Error ? e.message : '状态读取失败');
    } finally {
      if (!quiet) setQuotaLoading(false);
    }
  }

  async function refreshTasks(opts?: { quiet?: boolean }) {
    if (!configured && !opts?.quiet) return;
    if (!opts?.quiet) {
      setTasksLoading(true);
      setTasksError('');
    }
    try {
      const data = await listP115Tasks(1);
      const nextTasks = data.tasks || [];
      setTasks(nextTasks);
      setTasksLoaded(true);
      setTasksError('');
      patchP115PanelCache({
        tasks: nextTasks,
        tasksLoaded: true,
        tasksError: '',
      });
      if (data.quota != null || data.quotaTotal != null) {
        applyQuotaInfo({
          quota: data.quota,
          quotaTotal: data.quotaTotal,
        });
      }
    } catch (e) {
      const err = e instanceof Error ? e.message : '获取任务失败';
      setTasksError(err);
      setTasksLoaded(true);
      patchP115PanelCache({ tasksLoaded: true, tasksError: err });
    } finally {
      if (!opts?.quiet) setTasksLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const fresh = isP115PanelCacheFresh();
    if (cached?.configured) onStatus('已就绪', 'ok');
    else if (cached && !cached.configured) onStatus('未配置', 'warn');

    void (async () => {
      try {
        // 有新鲜且已配置的缓存：直接展示，后台静默刷配额
        if (fresh && cached?.configured) {
          void refreshStatus({ quiet: true });
          return;
        }
        const data = await getP115();
        if (cancelled) return;
        applyConfig(data, { forceOverview: !cached?.configured && data.configured });
        if (data.configured) {
          // 无配额缓存时才显示「读取中」
          const needSpin = getP115PanelCache()?.quota == null;
          if (needSpin) setQuotaLoading(true);
          try {
            const status = await getP115Status();
            if (cancelled) return;
            applyQuotaInfo(status);
          } catch (e) {
            if (cancelled) return;
            setQuotaError(e instanceof Error ? e.message : '状态读取失败');
          } finally {
            if (!cancelled) setQuotaLoading(false);
          }
        } else {
          setQuotaLoading(false);
        }
      } catch (e) {
        if (cancelled) return;
        setMsg(e instanceof Error ? e.message : '读取失败');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const d = await getSubtitleSettings();
        if (cancelled) return;
        setAssrtHint(d.assrtTokenHint || '');
        setAssrtConfigured(Boolean(d.assrtConfigured));
        setAssrtFromEnv(Boolean(d.assrtFromEnv));
        setAssrtShowEdit(!d.assrtConfigured || Boolean(d.assrtFromEnv));
      } catch {
        /* 字幕设置可选，失败不挡主流程 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSaveAssrt() {
    const key = assrtToken.trim();
    if (!key && !assrtConfigured) {
      setMsg('请填写 Assrt Token（assrt.net 用户面板）');
      return;
    }
    setBusy(true);
    setMsg('');
    try {
      const next = await putSubtitleSettings({ assrtToken: key });
      setAssrtHint(next.assrtTokenHint || '');
      setAssrtToken('');
      setAssrtConfigured(Boolean(next.assrtConfigured));
      setAssrtFromEnv(Boolean(next.assrtFromEnv));
      setAssrtShowEdit(!next.assrtConfigured || Boolean(next.assrtFromEnv));
      setMsg(
        next.assrtFromEnv
          ? '已保存（仍以环境变量 ASSRT_TOKEN 为准）'
          : next.assrtConfigured
            ? 'Assrt Token 已保存'
            : '已保存',
      );
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  async function onTestAssrt() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testAssrtToken({ assrtToken: assrtToken.trim() });
      setMsg(r.message || (r.ok ? '测试成功' : '失败'));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '测试失败');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    patchP115PanelCache({ tab });
  }, [tab]);

  useEffect(() => {
    if (tab !== 'tasks' || !configured) return;
    if (tasksLoaded && !tasksError) return;
    void refreshTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, configured]);

  useEffect(() => {
    return () => {
      // 勿在卸载时用闭包 state 回写缓存：会覆盖掉 applyConfig/applyQuotaInfo
      // 已写入的正确快照（第二次进入就会空白）。
      qrGenRef.current += 1;
    };
  }, []);

  async function startQrLogin() {
    const gen = ++qrGenRef.current;
    setQrBusy(true);
    setQrOpen(true);
    setQrStatusLabel('生成二维码…');
    setQrSession(null);
    setMsg('');
    try {
      const session = await startP115Qrcode('alipaymini');
      if (gen !== qrGenRef.current) return;
      setQrSession(session);
      setQrStatusLabel('请用 115 App 扫码');
      setShowCookieEdit(true);

      for (;;) {
        if (gen !== qrGenRef.current) return;
        await new Promise((r) => window.setTimeout(r, 1400));
        if (gen !== qrGenRef.current) return;
        const st = await pollP115Qrcode({
          uid: session.uid,
          time: session.time,
          sign: session.sign,
        });
        if (gen !== qrGenRef.current) return;
        setQrStatusLabel(st.statusLabel || '');
        if (st.expired) {
          setMsg(st.statusLabel || '二维码已失效，请重新扫码');
          break;
        }
        if (st.done) {
          setQrStatusLabel('正在获取 Cookie…');
          const done = await completeP115Qrcode({
            uid: session.uid,
            app: session.app || 'alipaymini',
            save: true,
          });
          if (gen !== qrGenRef.current) return;
          applyConfig(done);
          setShowCookieEdit(false);
          setCookie('');
          setQrOpen(false);
          setQrSession(null);
          setMsg(done.message || '扫码登录成功');
          setTab('overview');
          void refreshStatus();
          break;
        }
      }
    } catch (e) {
      if (gen === qrGenRef.current) {
        setMsg(e instanceof Error ? e.message : '扫码登录失败');
        setQrStatusLabel('扫码失败');
      }
    } finally {
      if (gen === qrGenRef.current) setQrBusy(false);
    }
  }

  function cancelQrLogin() {
    qrGenRef.current += 1;
    setQrBusy(false);
    setQrOpen(false);
    setQrSession(null);
    setQrStatusLabel('');
  }

  async function browseFolders(source: BrowseTarget, cid = '0') {
    setBrowseSource(source);
    setBrowsing(true);
    setMsg('');
    try {
      const data = await listP115Folders({
        cid,
        cookie: cookie.trim() || undefined,
      });
      setFolderPath(data.path || []);
      setFolders(data.folders || []);
      setShowBrowser(true);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '获取目录失败');
    } finally {
      setBrowsing(false);
    }
  }

  function selectFolder(item: P115FolderItem) {
    if (browseSource === 'subs') {
      setSubsFolder({ folderCid: item.cid, folderName: item.name });
      setShowBrowser(false);
      setMsg(`已选择「${item.name}」作为字幕目录，记得保存`);
      return;
    }
    setTargets((prev) => ({
      ...prev,
      [browseSource]: {
        folderCid: item.cid,
        folderName: item.name,
      },
    }));
    setShowBrowser(false);
    const label = SAVE_SOURCES.find((s) => s.key === browseSource)?.label || '';
    setMsg(`已选择「${item.name}」作为${label}目录，记得保存`);
  }

  async function onTest() {
    setBusy(true);
    setMsg('');
    try {
      const warehouse = targets.warehouse;
      const r = await validateP115({
        cookie: cookie.trim() || undefined,
        folderCid: warehouse.folderCid,
      });
      if (r.folderName) {
        setTargets((prev) => ({
          ...prev,
          warehouse: {
            ...prev.warehouse,
            folderName: String(r.folderName),
          },
        }));
      }
      applyQuotaInfo(r);
      const q = formatQuota(r.quota, r.quotaTotal);
      setMsg(
        [r.message || (r.ok ? '验证成功' : '验证失败'), q ? `云转存 ${q}` : '']
          .filter(Boolean)
          .join(' · '),
      );
      if (r.ok) onStatus('已就绪', 'ok');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '验证失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putP115({
        cookie: cookie.trim() || undefined,
        targets,
        subsFolder,
        subsLayered,
        validate: true,
      });
      applyConfig(next);
      setShowCookieEdit(false);
      const q = formatQuota(next.quota, next.quotaTotal);
      setMsg(
        [next.message || '已保存', q ? `云转存 ${q}` : ''].filter(Boolean).join(' · '),
      );
      setTab('overview');
      void refreshStatus();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  async function onClear(mode: P115ClearMode) {
    const labels: Record<P115ClearMode, string> = {
      done: '已完成',
      failed: '已失败',
      all: '全部',
    };
    if (mode === 'all' && !window.confirm('确定清理全部离线任务？（不会删除网盘内文件）')) {
      return;
    }
    setClearing(mode);
    setMsg('');
    try {
      const data = await clearP115Tasks(mode);
      if (data.tasks) setTasks(data.tasks);
      else await refreshTasks({ quiet: true });
      if (data.quota != null || data.quotaTotal != null) {
        applyQuotaInfo({
          quota: data.quota,
          quotaTotal: data.quotaTotal,
        });
      }
      setMsg(data.message || `已清理${labels[mode]}任务`);
      setTasksError('');
      setTasksLoaded(true);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '清理失败');
    } finally {
      setClearing(null);
    }
  }

  const locked = busy || browsing || clearing != null || qrBusy;
  const taskCounts = {
    run: 0,
    failed: 0,
    done: 0,
  };
  for (const t of tasks) {
    taskCounts[taskFilterOf(t.status)] += 1;
  }
  const filteredTasks = tasks.filter((t) => taskFilterOf(t.status) === taskFilter);
  const quotaRatio =
    quota != null && quotaTotal != null && quotaTotal > 0
      ? Math.max(0, Math.min(1, quota / quotaTotal))
      : null;
  const quotaLow =
    quota != null && quotaTotal != null && quotaTotal > 0 && quota / quotaTotal <= 0.2;
  const spaceRatio =
    spaceUsed != null && spaceTotal != null && spaceTotal > 0
      ? Math.max(0, Math.min(1, spaceUsed / spaceTotal))
      : null;
  return (
    <AppPush title="115 转存" onBack={onBack}>
      <div className="p115-console">
        {!configured ? (
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">状态</span>
                <span className="settings-nav__status settings-nav__status--warn">
                  待配置
                </span>
              </div>
            </li>
          </ul>
        ) : (
          <div className="app-seg" role="tablist" aria-label="115 转存工作台">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={cn('app-seg__btn', tab === t.key && 'app-seg__btn--active')}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {tab === 'overview' && configured ? (
          <div className="p115-console__pane">
            <section className="p115-stats" aria-label="115 概览">
              <div className="p115-stats__head">
                <span className="p115-stats__badge p115-stats__badge--ok">已就绪</span>
                <button
                  type="button"
                  className="p115-stats__refresh"
                  disabled={quotaLoading || locked}
                  onClick={() => void refreshStatus()}
                >
                  <RefreshCw
                    size={13}
                    strokeWidth={2.25}
                    className={cn(quotaLoading && 'p115-spin')}
                    aria-hidden
                  />
                  刷新状态
                </button>
              </div>

              <div className="p115-stats__grid">
                <div className="p115-stat">
                  <div className="p115-stat__top">
                    <span className="p115-stat__label">云转存</span>
                    <span className={cn('p115-stat__pct', quotaLow ? 'is-warn' : 'is-ok')}>
                      {quotaRatio != null ? `${Math.round(quotaRatio * 100)}%` : ''}
                    </span>
                  </div>
                  <div className="p115-stat__value allow-select">
                    {quotaLoading && quota == null ? (
                      <span className="p115-stat__muted">读取中…</span>
                    ) : quota != null ? (
                      <>
                        <strong>{quota}</strong>
                        {quotaTotal != null ? (
                          <span className="p115-stat__den"> / {quotaTotal}</span>
                        ) : null}
                      </>
                    ) : (
                      <span className="p115-stat__muted">{quotaError || '暂无数据'}</span>
                    )}
                  </div>
                  {quotaRatio != null ? (
                    <div
                      className={cn('p115-quota-bar', quotaLow && 'p115-quota-bar--low')}
                      role="meter"
                      aria-valuemin={0}
                      aria-valuemax={quotaTotal ?? 0}
                      aria-valuenow={quota ?? 0}
                      aria-label="云转存剩余额度"
                    >
                      <span style={{ width: `${Math.round(quotaRatio * 100)}%` }} />
                    </div>
                  ) : (
                    <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                      <span style={{ width: '0%' }} />
                    </div>
                  )}
                  <p className="p115-stat__hint">剩余任务额度</p>
                </div>

                <div className="p115-stat">
                  <div className="p115-stat__top">
                    <span className="p115-stat__label">网盘空间</span>
                    <span className="p115-stat__pct is-mute">
                      {spaceRatio != null ? `${Math.round(spaceRatio * 100)}%` : ''}
                    </span>
                  </div>
                  <div className="p115-stat__value allow-select">
                    {spaceRemainText ? (
                      <>
                        <strong>{spaceRemainText}</strong>
                        <span className="p115-stat__den"> 剩余</span>
                      </>
                    ) : spaceUsedText && spaceTotalText ? (
                      <span className="p115-stat__muted">
                        {spaceUsedText} / {spaceTotalText}
                      </span>
                    ) : (
                      <span className="p115-stat__muted">暂无数据</span>
                    )}
                  </div>
                  {spaceRatio != null ? (
                    <div
                      className="p115-quota-bar p115-quota-bar--space"
                      role="meter"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(spaceRatio * 100)}
                      aria-label="网盘已用空间"
                    >
                      <span style={{ width: `${Math.round(spaceRatio * 100)}%` }} />
                    </div>
                  ) : (
                    <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                      <span style={{ width: '0%' }} />
                    </div>
                  )}
                  <p className="p115-stat__hint allow-select">
                    {spaceUsedText && spaceTotalText
                      ? `已用 ${spaceUsedText} · 共 ${spaceTotalText}`
                      : '容量占用'}
                  </p>
                </div>
              </div>
            </section>

            <ul className="settings-group">
              <li>
                <div className="settings-nav">
                  <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                    <CloudDownload size={14} strokeWidth={2.25} />
                  </span>
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">转存流程</span>
                    <span className="settings-nav__desc allow-select">
                      影视 / 片商 / 仓库：先入根目录「最近接受」，完成后再移到各自指定目录
                    </span>
                  </span>
                </div>
              </li>
              <li>
                <div className="settings-nav">
                  <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                    <KeyRound size={14} strokeWidth={2.25} />
                  </span>
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">登录态</span>
                    <span className="settings-nav__desc allow-select">
                      {hint || '已配置 Cookie'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="settings-inline-action"
                    onClick={() => setTab('config')}
                  >
                    管理
                  </button>
                </div>
              </li>
              {SAVE_SOURCES.map((src) => {
                const t = targets[src.key];
                return (
                  <li key={src.key}>
                    <div className="settings-nav">
                      <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
                        <FolderOpen size={14} strokeWidth={2.25} />
                      </span>
                      <span className="settings-nav__main">
                        <span className="settings-nav__title">{src.label}</span>
                        <span className="settings-nav__desc allow-select">
                          {folderDisplayName(t)} · CID {t.folderCid || '0'}
                        </span>
                      </span>
                      <button
                        type="button"
                        className="settings-inline-action"
                        onClick={() => setTab('config')}
                      >
                        更改
                      </button>
                    </div>
                  </li>
                );
              })}
              <li>
                <div className="settings-nav">
                  <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                    <FolderOpen size={14} strokeWidth={2.25} />
                  </span>
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">字幕</span>
                    <span className="settings-nav__desc allow-select">
                      {subsFolder.folderName
                        ? `${folderDisplayName(subsFolder)} · CID ${subsFolder.folderCid || '0'}`
                        : '未配置（默认片商根/字幕）'}
                      {subsLayered ? ' · 按分区分层' : ' · 扁平'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="settings-inline-action"
                    onClick={() => setTab('config')}
                  >
                    更改
                  </button>
                </div>
              </li>
            </ul>
          </div>
        ) : null}

        {tab === 'config' ? (
          <div className="p115-console__pane">
            <section className="p115-console__block">
              <div className="p115-cookie-head">
                <p className="settings-group-label">登录 Cookie</p>
                <button
                  type="button"
                  className="p115-qr-trigger"
                  disabled={locked}
                  onClick={() => void startQrLogin()}
                >
                  <QrCode size={14} strokeWidth={2.25} aria-hidden />
                  {qrBusy ? '扫码中…' : '扫码获取'}
                </button>
              </div>

              {qrOpen ? (
                <div className="p115-qr">
                  <div className="p115-qr__frame">
                    {qrSession?.qrImage ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        className="p115-qr__img"
                        src={qrSession.qrImage}
                        alt="115 登录二维码"
                      />
                    ) : (
                      <p className="p115-qr__placeholder">
                        {qrBusy ? '生成中…' : '暂无二维码'}
                      </p>
                    )}
                  </div>
                  <p className="p115-qr__status">{qrStatusLabel || '等待扫码'}</p>
                  <p className="p115-qr__hint">
                    打开 115 App 扫一扫；绑定设备为支付宝小程序通道，不易挤掉网页端。
                  </p>
                  <div className="p115-qr__actions">
                    <button
                      type="button"
                      className="app-btn-secondary"
                      onClick={() => void startQrLogin()}
                    >
                      刷新二维码
                    </button>
                    <button
                      type="button"
                      className="app-btn-secondary"
                      onClick={cancelQrLogin}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : null}

              {configured && !showCookieEdit ? (
                <ul className="settings-group">
                  <li>
                    <div className="settings-nav">
                      <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                        <KeyRound size={14} strokeWidth={2.25} />
                      </span>
                      <span className="settings-nav__main">
                        <span className="settings-nav__title">已登录</span>
                        <span className="settings-nav__desc allow-select">{hint || '••••'}</span>
                      </span>
                      <button
                        type="button"
                        className="settings-inline-action"
                        disabled={locked}
                        onClick={() => setShowCookieEdit(true)}
                      >
                        更换
                      </button>
                    </div>
                  </li>
                </ul>
              ) : (
                <>
                  <div className="p115-cookie-card">
                    <textarea
                      className="p115-cookie-card__input allow-select"
                      rows={4}
                      placeholder="UID=…; CID=…; SEID=…; KID=…"
                      value={cookie}
                      onChange={(e) => setCookie(e.target.value)}
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                      disabled={locked}
                      aria-label="115 Cookie"
                    />
                  </div>
                  {configured ? (
                    <button
                      type="button"
                      className="settings-text-link"
                      disabled={locked}
                      onClick={() => {
                        setCookie('');
                        setShowCookieEdit(false);
                        cancelQrLogin();
                      }}
                    >
                      取消更换
                    </button>
                  ) : null}
                </>
              )}
            </section>

            {configured ? (
              <section className="p115-console__block">
                <p className="settings-group-label">按入口保存目录</p>
                <ul className="settings-group">
                  {SAVE_SOURCES.map((src) => {
                    const t = targets[src.key];
                    return (
                      <li key={src.key}>
                        <div className="settings-nav">
                          <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
                            <FolderOpen size={14} strokeWidth={2.25} />
                          </span>
                          <span className="settings-nav__main">
                            <span className="settings-nav__title">{src.label}</span>
                            <span className="settings-nav__desc allow-select">
                              {folderDisplayName(t)} · CID {t.folderCid || '0'}
                              <span className="p115-target-hint"> · {src.desc}</span>
                            </span>
                          </span>
                          <button
                            type="button"
                            className="settings-inline-action"
                            disabled={locked}
                            onClick={() => void browseFolders(src.key, t.folderCid || '0')}
                          >
                            浏览
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <p className="settings-group-label" style={{ marginTop: 16 }}>
                  字幕目录
                </p>
                <ul className="settings-group">
                  <li>
                    <div className="settings-nav">
                      <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                        <FolderOpen size={14} strokeWidth={2.25} />
                      </span>
                      <span className="settings-nav__main">
                        <span className="settings-nav__title">字幕根目录</span>
                        <span className="settings-nav__desc allow-select">
                          {subsFolder.folderName
                            ? `${folderDisplayName(subsFolder)} · CID ${subsFolder.folderCid || '0'}`
                            : '未选：默认片商根下「字幕」'}
                          <span className="p115-target-hint">
                            {' '}
                            · 仅中文 · 命名 ABC-123.chi.srt · 多源评分选优
                          </span>
                        </span>
                      </span>
                      <button
                        type="button"
                        className="settings-inline-action"
                        disabled={locked}
                        onClick={() =>
                          void browseFolders('subs', subsFolder.folderCid || '0')
                        }
                      >
                        浏览
                      </button>
                    </div>
                  </li>
                  <li>
                    <div className="settings-nav">
                      <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                        <Folder size={14} strokeWidth={2.25} />
                      </span>
                      <span className="settings-nav__main">
                        <span className="settings-nav__title">按分区分层</span>
                        <span className="settings-nav__desc allow-select">
                          {subsLayered
                            ? '开启：字幕根/日本有码/SSIS-949.chi.srt'
                            : '关闭：字幕根/SSIS-949.chi.srt'}
                        </span>
                      </span>
                      <button
                        type="button"
                        className={cn(
                          'makers-ios-switch',
                          subsLayered && 'makers-ios-switch--on',
                        )}
                        role="switch"
                        aria-checked={subsLayered}
                        disabled={locked}
                        onClick={() => setSubsLayered((v) => !v)}
                      >
                        <span className="makers-ios-switch__thumb" />
                      </button>
                    </div>
                  </li>
                </ul>
                <p className="settings-group-label" style={{ marginTop: 16 }}>
                  字幕源
                </p>
                <ul className="settings-group">
                  <li>
                    <div className="settings-nav" style={{ alignItems: 'flex-start' }}>
                      <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                        <KeyRound size={14} strokeWidth={2.25} />
                      </span>
                      <span className="settings-nav__main" style={{ flex: 1, minWidth: 0 }}>
                        <span className="settings-nav__title">Assrt Token（可选）</span>
                        <span className="settings-nav__desc allow-select">
                          多源：SubtitleCat / 迅雷 / Assrt / SubHD，自动评分选最优。
                          {assrtConfigured
                            ? ` · 已配置${assrtFromEnv ? '（环境变量）' : ''} ${assrtHint}`
                            : ' · 未配置时跳过 Assrt'}
                        </span>
                        {assrtShowEdit ? (
                          <input
                            type="password"
                            className="p115-cookie-card__input allow-select"
                            style={{ marginTop: 8, width: '100%' }}
                            placeholder="assrt.net 用户面板 API Token"
                            value={assrtToken}
                            disabled={locked || busy}
                            onChange={(e) => setAssrtToken(e.target.value)}
                            autoComplete="off"
                          />
                        ) : null}
                        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                          {!assrtShowEdit ? (
                            <button
                              type="button"
                              className="settings-inline-action"
                              disabled={locked || busy}
                              onClick={() => setAssrtShowEdit(true)}
                            >
                              更换
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="settings-inline-action"
                              disabled={locked || busy}
                              onClick={() => void onSaveAssrt()}
                            >
                              保存 Token
                            </button>
                          )}
                          <button
                            type="button"
                            className="settings-inline-action"
                            disabled={locked || busy}
                            onClick={() => void onTestAssrt()}
                          >
                            测试
                          </button>
                        </div>
                      </span>
                    </div>
                  </li>
                </ul>
              </section>
            ) : null}

            <AppCenterModal
              open={showBrowser}
              title={
                browseSource === 'subs'
                  ? '选择字幕目录'
                  : `选择${SAVE_SOURCES.find((s) => s.key === browseSource)?.label || ''}目录`
              }
              onClose={() => setShowBrowser(false)}
              cardClassName="p115-browser-modal"
              footer={
                <button
                  type="button"
                  className="app-btn-primary"
                  style={{ flex: 1 }}
                  onClick={() => {
                    const cur = folderPath[folderPath.length - 1];
                    if (cur) {
                      selectFolder(cur);
                      return;
                    }
                    selectFolder({ cid: '0', name: '根目录' });
                  }}
                >
                  {folderPath.length > 0 ? '选用当前路径' : '选用根目录'}
                </button>
              }
            >
              <div className="p115-browser p115-browser--modal">
                <nav className="p115-browser__path" aria-label="目录路径">
                  {folderPath.length === 0 ? (
                    <span className="p115-browser__crumb">
                      <span className="p115-browser__link is-current">根目录</span>
                    </span>
                  ) : (
                    folderPath.map((p, idx) => (
                      <span key={`${p.cid}-${idx}`} className="p115-browser__crumb">
                        {idx > 0 ? <span className="p115-browser__sep">/</span> : null}
                        <button
                          type="button"
                          className={cn(
                            'p115-browser__link',
                            idx === folderPath.length - 1 && 'is-current',
                          )}
                          onClick={() => void browseFolders(browseSource, p.cid)}
                        >
                          {p.name}
                        </button>
                      </span>
                    ))
                  )}
                  <button
                    type="button"
                    className="p115-browser__refresh"
                    disabled={browsing || locked}
                    onClick={() => {
                      const cur = folderPath[folderPath.length - 1];
                      void browseFolders(browseSource, cur?.cid || '0');
                    }}
                  >
                    刷新
                  </button>
                </nav>
                <div className="p115-browser__list">
                  {browsing ? (
                    <p className="p115-browser__empty">加载中…</p>
                  ) : folders.length === 0 ? (
                    <p className="p115-browser__empty">此层无子文件夹，可选用当前路径</p>
                  ) : (
                    folders.map((f) => {
                      const selectedCid =
                        browseSource === 'subs'
                          ? subsFolder.folderCid
                          : targets[browseSource].folderCid;
                      const selected = f.cid === selectedCid;
                      return (
                        <div
                          key={f.cid}
                          className={cn('p115-browser__row', selected && 'is-selected')}
                        >
                          <span className="p115-browser__fold" aria-hidden>
                            <Folder size={16} strokeWidth={2} />
                          </span>
                          <button
                            type="button"
                            className="p115-browser__name"
                            onClick={() => void browseFolders(browseSource, f.cid)}
                          >
                            {f.name}
                          </button>
                          <button
                            type="button"
                            className={cn('p115-browser__pick', selected && 'is-on')}
                            onClick={() => selectFolder(f)}
                          >
                            {selected ? '已选' : '选用'}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </AppCenterModal>

            <div className="app-actions">
              <button
                type="button"
                className="app-btn-secondary"
                disabled={locked}
                onClick={() => void onTest()}
              >
                测试
              </button>
              <button
                type="button"
                className="app-btn-primary"
                style={{ flex: 1 }}
                disabled={locked}
                onClick={() => void onSave()}
              >
                保存
              </button>
            </div>
          </div>
        ) : null}

        {tab === 'tasks' && configured ? (
          <div className="p115-console__pane p115-console__pane--tasks">
            <div className="p115-tasks-toolbar">
              <div className="p115-tasks-toolbar__lead">
                <span className="p115-tasks-toolbar__title">云下载队列</span>
                <span className="p115-tasks-toolbar__count allow-select">
                  {tasksLoaded && !tasksError
                    ? tasks.length > 0
                      ? `${tasks.length} 项`
                      : '空'
                    : tasksLoading
                      ? '读取中'
                      : '—'}
                </span>
              </div>
              <div className="p115-tasks-toolbar__actions" role="toolbar" aria-label="任务操作">
                <button
                  type="button"
                  className="p115-tasks-action"
                  disabled={tasksLoading || locked}
                  onClick={() => void refreshTasks()}
                >
                  <RefreshCw
                    size={14}
                    strokeWidth={2.25}
                    className={cn(tasksLoading && 'p115-spin')}
                    aria-hidden
                  />
                  刷新
                </button>
                {taskFilter === 'done' ? (
                  <button
                    type="button"
                    className="p115-tasks-action"
                    disabled={
                      tasksLoading || locked || clearing === 'done' || taskCounts.done === 0
                    }
                    onClick={() => void onClear('done')}
                  >
                    {clearing === 'done' ? '清理中' : '清完成'}
                  </button>
                ) : null}
                {taskFilter === 'failed' ? (
                  <button
                    type="button"
                    className="p115-tasks-action p115-tasks-action--warn"
                    disabled={
                      tasksLoading ||
                      locked ||
                      clearing === 'failed' ||
                      taskCounts.failed === 0
                    }
                    onClick={() => void onClear('failed')}
                  >
                    {clearing === 'failed' ? '清理中' : '清失败'}
                  </button>
                ) : null}
              </div>
            </div>

            <div className="app-seg p115-tasks-filter" role="tablist" aria-label="任务状态">
              {TASK_FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  role="tab"
                  aria-selected={taskFilter === f.key}
                  className={cn(
                    'app-seg__btn',
                    taskFilter === f.key && 'app-seg__btn--active',
                  )}
                  onClick={() => setTaskFilter(f.key)}
                >
                  {f.label}
                  <span className="p115-tasks-filter__n allow-select">
                    {tasksLoaded && !tasksError ? taskCounts[f.key] : '—'}
                  </span>
                </button>
              ))}
            </div>

            {tasksError ? (
              <div className="p115-tasks-empty p115-tasks-empty--err">
                <p>{tasksError}</p>
                <button
                  type="button"
                  className="p115-tasks-empty__link"
                  onClick={() => void refreshTasks()}
                >
                  重试
                </button>
              </div>
            ) : tasksLoading && !tasksLoaded ? (
              <div className="p115-tasks-empty" aria-busy="true">
                <p>加载任务中…</p>
              </div>
            ) : tasks.length === 0 ? (
              <div className="p115-tasks-empty">
                <span className="p115-tasks-empty__icon" aria-hidden>
                  <CloudDownload size={22} strokeWidth={1.75} />
                </span>
                <p>暂无离线任务</p>
                <span>转存后会出现在这里；额度紧时清理已完成或失败项即可腾出队列。</span>
              </div>
            ) : filteredTasks.length === 0 ? (
              <div className="p115-tasks-empty">
                <p>
                  {taskFilter === 'run'
                    ? '没有下载中的任务'
                    : taskFilter === 'failed'
                      ? '没有失败任务'
                      : '没有已完成任务'}
                </p>
                <span>
                  {taskFilter === 'run'
                    ? '排队或进行中的任务会显示在这里。'
                    : taskFilter === 'failed'
                      ? '失败记录可一键清理，腾出额度。'
                      : '完成后可清理记录，网盘文件不受影响。'}
                </span>
              </div>
            ) : (
              <ul className="p115-tasks" aria-label="离线任务列表">
                {filteredTasks.map((t, idx) => {
                  const tone = taskTone(t.status);
                  const show = taskDisplay(t);
                  const timeText = formatTaskTime(t.updateTime || t.addTime);
                  const sizeText = formatBytes(t.size);
                  const pctText =
                    t.percent != null && t.status === 1
                      ? `${Math.round(t.percent)}%`
                      : null;
                  const showBadge = taskFilterOf(t.status) !== taskFilter;
                  return (
                    <li
                      key={`${t.infoHash || t.name}-${idx}`}
                      className={cn('p115-task', `p115-task--${tone}`)}
                    >
                      <span className={cn('p115-task__mark', `is-${tone}`)} aria-hidden>
                        {tone === 'ok' ? (
                          <CheckCircle2 size={15} strokeWidth={2.1} />
                        ) : tone === 'warn' ? (
                          <AlertCircle size={15} strokeWidth={2.1} />
                        ) : tone === 'run' ? (
                          <LoaderCircle
                            size={15}
                            strokeWidth={2.1}
                            className="p115-spin"
                          />
                        ) : (
                          <Clock3 size={15} strokeWidth={2.1} />
                        )}
                      </span>
                      <div className="p115-task__body">
                        <div className="p115-task__head">
                          <div className="p115-task__titles">
                            <p className="p115-task__name allow-select">{show.title}</p>
                            {show.subtitle ? (
                              <p
                                className="p115-task__hash allow-select"
                                title={show.hashFull || undefined}
                              >
                                {show.subtitle}
                              </p>
                            ) : null}
                          </div>
                          {showBadge ? (
                            <span className={cn('p115-task__badge', `is-${tone}`)}>
                              {t.statusLabel}
                            </span>
                          ) : null}
                        </div>
                        {(pctText || sizeText || timeText) ? (
                          <div className="p115-task__meta">
                            {pctText ? (
                              <span className="p115-task__chip is-run allow-select">
                                {pctText}
                              </span>
                            ) : null}
                            {sizeText ? (
                              <span className="p115-task__chip allow-select">
                                {sizeText}
                              </span>
                            ) : null}
                            {timeText ? (
                              <span className="p115-task__chip allow-select">
                                {timeText}
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                        {t.status === 1 && t.percent != null ? (
                          <div
                            className="p115-quota-bar p115-quota-bar--space p115-task__bar"
                            role="progressbar"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={Math.round(t.percent)}
                            aria-label="下载进度"
                          >
                            <span style={{ width: `${Math.round(t.percent)}%` }} />
                          </div>
                        ) : null}
                        {t.error ? (
                          <p className="p115-task__err allow-select">{t.error}</p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            <AppFootnote>清理只移除云下载队列记录，不会删除已转存到网盘的文件。</AppFootnote>
          </div>
        ) : null}

        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </div>
    </AppPush>
  );
}
