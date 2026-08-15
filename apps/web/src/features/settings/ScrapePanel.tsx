"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronRight,
  Play,
  Plus,
  RefreshCw,
  ScanSearch,
} from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { ScrapeSourcesTab } from '@/features/settings/ScrapeSourcesTab';
import {
  ScrapeTaskModal,
  type ScrapeTaskDraft,
} from '@/features/settings/ScrapeTaskModal';
import { ScrapeProgressLog } from '@/features/settings/ScrapeProgressLog';
import {
  clearScrapeExport,
  resetScrapeExportCheckpoint,
  purgeScrapeTaskLogs,
  cancelScrapeExportTask,
  fetchMakerFsRegions,
  fetchScrapeExportCodes,
  fetchScrapeExportStatus,
  getScrape,
  pauseScrapeExport,
  putScrape,
  resumeScrapeExport,
  startScrapeExport,
  testScrape,
  type MakerFsRegionSummary,
  type ScrapeConfig,
  type CoverDownloadStrategy,
  type MetadataOptimizeConfig,
  type MetadataOptimizeLang,
  DEFAULT_METADATA_OPTIMIZE,
  type ScrapeExportStatus,
  type ScrapeLibraryOption,
  type ScrapeRegionProfile,
  type ScrapeSourceCard,
  type ScrapeTask,
} from '@/lib/api';

const COVER_STRATEGY_OPTIONS: Array<{
  value: CoverDownloadStrategy;
  title: string;
  sub: string;
}> = [
  {
    value: "priority",
    title: "按数据源优先级",
    sub: "根据数据源设置页的优先级配置，依次尝试下载",
  },
  {
    value: "size",
    title: "按文件大小",
    sub: "访问全部候选链接，根据图片文件大小进行选择（速度相对慢）",
  },
];

function normalizeMetadataOptimize(
  raw?: MetadataOptimizeConfig | null,
): MetadataOptimizeConfig {
  const base = DEFAULT_METADATA_OPTIMIZE;
  const langRaw = String(raw?.mappingLanguage || base.mappingLanguage);
  const lang: MetadataOptimizeLang =
    langRaw === "zh-TW" || langRaw === "ja" || langRaw === "en"
      ? langRaw
      : "zh-CN";
  return {
    useForumZhTitle:
      raw?.useForumZhTitle == null ? base.useForumZhTitle : Boolean(raw.useForumZhTitle),
    enableActorMapping:
      raw?.enableActorMapping == null
        ? base.enableActorMapping
        : Boolean(raw.enableActorMapping),
    enableTagMapping:
      raw?.enableTagMapping == null
        ? base.enableTagMapping
        : Boolean(raw.enableTagMapping),
    compactOutlineNewlines:
      raw?.compactOutlineNewlines == null
        ? base.compactOutlineNewlines
        : Boolean(raw.compactOutlineNewlines),
    mappingLanguage: lang,
  };
}

function hasProgressCard(st: ScrapeExportStatus | null, exporting: boolean) {
  if (exporting) return true;
  if (!st) return false;
  if (st.running) return true;
  if ((st.total || 0) > 0) return true;
  if ((st.events?.length || 0) > 0) return true;
  if (st.currentDetail?.code) return true;
  if (st.message) return true;
  return false;
}

/** 任务卡统计：优先用字段，否则从 lastStatus 文案解析；合计不够时抬高，不压成功数 */
function reconcileStats(s: {
  done: number;
  empty: number;
  failed: number;
  total: number;
}): {
  done: number;
  empty: number;
  failed: number;
  total: number;
} {
  const done = Math.max(0, Number(s.done) || 0);
  const empty = Math.max(0, Number(s.empty) || 0);
  const failed = Math.max(0, Number(s.failed) || 0);
  let total = Math.max(0, Number(s.total) || 0);
  const processed = done + empty + failed;
  if (processed > total) total = processed;
  return { done, empty, failed, total };
}

function uniqCodes(codes: string[] | null | undefined): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of codes || []) {
    const c = String(raw || "").trim();
    if (!c || seen.has(c)) continue;
    seen.add(c);
    out.push(c);
  }
  return out;
}

/** 任务终身桶合并：成功 > 空号 > 失败（全源无详情归空号，可从失败迁出） */
function mergeLifetimeBuckets(
  base: { done: string[]; empty: string[]; failed: string[] },
  extra: { done: string[]; empty: string[]; failed: string[] },
): {
  doneCodes: string[];
  emptyCodes: string[];
  failedCodes: string[];
  done: number;
  empty: number;
  failed: number;
  total: number;
} {
  const doneCodes = uniqCodes([...base.done, ...extra.done]);
  const doneSet = new Set(doneCodes);
  const emptyCodes = uniqCodes(
    [...base.empty, ...extra.empty].filter((c) => !doneSet.has(c)),
  );
  const emptySet = new Set(emptyCodes);
  const failedCodes = uniqCodes(
    [...base.failed, ...extra.failed].filter(
      (c) => !doneSet.has(c) && !emptySet.has(c),
    ),
  );
  const done = doneCodes.length;
  const empty = emptyCodes.length;
  const failed = failedCodes.length;
  return {
    doneCodes,
    emptyCodes,
    failedCodes,
    done,
    empty,
    failed,
    total: done + empty + failed,
  };
}

function taskStats(task: ScrapeTask): {
  done: number;
  empty: number;
  failed: number;
  total: number;
} {
  const hasNum =
    task.done != null ||
    task.empty != null ||
    task.skipped != null ||
    task.failed != null ||
    task.total != null;
  if (hasNum) {
    const done = Number(task.done || 0);
    const empty = Number(task.empty || 0);
    const failed = Number(task.failed || 0);
    const total = Number(task.total || 0) || done + empty + failed;
    return reconcileStats({ done, empty, failed, total });
  }
  const mEmpty = String(task.lastStatus || "").match(
    /成功\s*(\d+)\s*·\s*空号\s*(\d+)\s*·\s*(?:数据不全|失败)\s*(\d+)/,
  );
  if (mEmpty) {
    const done = Number(mEmpty[1]);
    const empty = Number(mEmpty[2]);
    const failed = Number(mEmpty[3]);
    return reconcileStats({
      done,
      empty,
      failed,
      total: done + empty + failed,
    });
  }
  const m = String(task.lastStatus || "").match(
    /成功\s*(\d+)\s*·\s*跳过\s*(\d+)\s*·\s*(?:数据不全|失败)\s*(\d+)/,
  );
  if (m) {
    const done = Number(m[1]);
    const empty = Number(m[2]);
    const failed = Number(m[3]);
    return reconcileStats({
      done,
      empty,
      failed,
      total: done + empty + failed,
    });
  }
  return { done: 0, empty: 0, failed: 0, total: 0 };
}

/** 进度快照是否属于该任务（必须 taskId 一致，禁止厂牌/前缀回退串卡） */
function progressBelongsToTask(
  st: ScrapeExportStatus | null | undefined,
  task: ScrapeTask,
): boolean {
  if (!st) return false;
  const taskId = String(task.id || "").trim();
  const stTid = String(st.taskId || "").trim();
  if (!taskId || !stTid) return false;
  return stTid === taskId;
}

function taskIsQueued(
  st: ScrapeExportStatus | null | undefined,
  task: ScrapeTask,
): boolean {
  if (!st?.queue?.length) return false;
  const taskId = String(task.id || "").trim();
  if (!taskId) return false;
  return st.queue.some((q) => String(q.taskId || "") === taskId);
}

/** 排队 / 进行中 / 暂停 / 可续跑：视为正在工作，列表置顶 */
function taskIsWorking(
  st: ScrapeExportStatus | null | undefined,
  task: ScrapeTask,
): boolean {
  if (taskIsQueued(st, task)) return true;
  if (!progressBelongsToTask(st, task) || !st) return false;
  const msg = String(st.message || "");
  return (
    Boolean(st.running) ||
    Boolean(st.paused) ||
    msg === "cancelling" ||
    msg === "paused" ||
    ((Boolean(st.resumable) || Boolean(st.pauseSaved)) && !st.running)
  );
}

type TaskBadge = { badge: string; tone: "run" | "ok" | "err" | "idle" | "warn" };

/** 任务卡徽章：优先真实进度，再回退 lastStatus；避免他卡 running 把本卡标成进行中 */
function resolveTaskBadge(
  task: ScrapeTask,
  progress: ScrapeExportStatus | null,
  exporting: boolean,
): TaskBadge & { live: boolean } {
  if (taskIsQueued(progress, task)) {
    return { badge: "排队中", tone: "warn", live: true };
  }
  const live = progressBelongsToTask(progress, task);
  if (live && progress) {
    const msg = String(progress.message || "");
    const running = Boolean(progress.running || exporting);
    const paused =
      Boolean(progress.paused) ||
      msg === "paused" ||
      (Boolean(progress.pauseSaved) && !running);
    if (msg === "cancelling") {
      return { badge: "取消中", tone: "run", live: true };
    }
    if (paused) {
      return { badge: "已暂停", tone: "warn", live: true };
    }
    if (running) {
      return {
        badge: "进行中",
        tone: "run",
        live: true,
      };
    }
    if (msg === "cancelled") {
      return { badge: "已取消", tone: "idle", live: true };
    }
    if (msg === "interrupted") {
      const pauseHint =
        Boolean(progress.pauseSaved) ||
        (progress.events || []).some((e) =>
          String(e.text || "").includes("已暂停"),
        );
      return {
        badge: pauseHint ? "已暂停" : "已中断",
        tone: "warn",
        live: true,
      };
    }
    if (msg === "ok" || msg === "") {
      const failed = Number(progress.failed || 0);
      if (failed > 0) return { badge: "数据不全", tone: "err", live: true };
      const processed =
        Number(progress.done || 0) +
        Number(progress.empty || 0) +
        Number(progress.skipped || 0) +
        failed;
      if (processed > 0 || Number(progress.total || 0) > 0) {
        return { badge: "已完成", tone: "ok", live: true };
      }
    }
  }

  // 进度快照属于本卡但已停：仍用快照计数展示已暂停（服务重启后）
  if (
    live &&
    progress &&
    (progress.resumable || progress.pauseSaved) &&
    !progress.running
  ) {
    return { badge: "已暂停", tone: "warn", live: true };
  }

  const ls = String(task.lastStatus || "").trim();
  if (!ls) return { badge: "待开始", tone: "idle", live: false };
  // 过期的「running / 排队中」：全局已不是本任务时，回退到存档结果语义
  if (ls === "running" || ls === "排队中") {
    const stats = taskStats(task);
    if (stats.failed > 0) return { badge: "数据不全", tone: "err", live: false };
    if (stats.done + stats.empty > 0 || stats.total > 0) {
      return { badge: "已完成", tone: "ok", live: false };
    }
    return { badge: "待开始", tone: "idle", live: false };
  }
  if (ls.includes("已暂停") || ls === "paused") {
    return { badge: "已暂停", tone: "warn", live: false };
  }
  if (ls.includes("已中断") || ls === "interrupted") {
    return { badge: "已中断", tone: "warn", live: false };
  }
  if (ls.includes("已取消") || ls === "cancelled") {
    return { badge: "已取消", tone: "idle", live: false };
  }
  if (
    (ls.includes("数据不全") || ls.includes("失败")) &&
    !ls.startsWith("完成")
  ) {
    return { badge: "数据不全", tone: "err", live: false };
  }
  if (/(?:数据不全|失败)\s*[1-9]/.test(ls)) {
    return { badge: "数据不全", tone: "err", live: false };
  }
  if (ls.startsWith("完成") || ls.includes("成功")) {
    return { badge: "已完成", tone: "ok", live: false };
  }
  return { badge: ls.slice(0, 12), tone: "idle", live: false };
}

type ScrapeTab = "config" | "task" | "progress" | "sources";

const TABS: Array<{ key: ScrapeTab; label: string }> = [
  { key: "config", label: "配置" },
  { key: "task", label: "任务" },
  { key: 'progress', label: '详情' },
  { key: "sources", label: "数据源" },
];

const FALLBACK_REGIONS: MakerFsRegionSummary[] = [
  { id: 'japan_censored', label: '日本有码', prefixCount: 0, codeCount: 0 },
  { id: 'japan_gravure', label: '日本写真', prefixCount: 0, codeCount: 0 },
  { id: 'japan_uncensored', label: '日本无码', prefixCount: 0, codeCount: 0 },
  { id: 'japan_amateur', label: '日本素人', prefixCount: 0, codeCount: 0 },
  { id: 'fc2', label: 'FC2', prefixCount: 0, codeCount: 0 },
  { id: 'china', label: '国产无码', prefixCount: 0, codeCount: 0 },
  { id: 'western', label: '欧美无码', prefixCount: 0, codeCount: 0 },
];

/** 任务可刮削字段（与数据源「字段优先级」一致） */
const ALL_SCRAPE_FIELDS: ScrapeTask["fields"] = [
  "cover",
  "titleZh",
  "outline",
  "studio",
  "actors",
  "tags",
  "series",
];

const SCRAPE_FIELD_LABELS: Record<ScrapeTask["fields"][number], string> = {
  cover: "封面图",
  titleZh: "中文标题",
  outline: "简介",
  studio: "制片方",
  actors: "女优",
  tags: "标签",
  series: "系列",
};

function taskFieldHint(fields: ScrapeTask["fields"] | undefined): string {
  const norm = normalizeTaskFields(fields);
  if (norm.length >= ALL_SCRAPE_FIELDS.length) return "";
  return norm.map((f) => SCRAPE_FIELD_LABELS[f] || f).join("/");
}

function normalizeTaskFields(
  raw: ScrapeTask["fields"] | undefined,
): ScrapeTask["fields"] {
  const seen = new Set<ScrapeTask["fields"][number]>();
  const out: ScrapeTask["fields"] = [];
  for (const item of raw || []) {
    if (!ALL_SCRAPE_FIELDS.includes(item) || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out.length ? out : [...ALL_SCRAPE_FIELDS];
}

const LOCAL_REUSE_FIELDS: ScrapeTask["fields"] = [
  "titleZh",
  "outline",
  "studio",
  "actors",
  "tags",
  "series",
];

function normalizeLocalFields(
  raw: ScrapeTask["fields"] | undefined,
  scrapeFields: ScrapeTask["fields"],
): ScrapeTask["fields"] {
  const allow = new Set(LOCAL_REUSE_FIELDS);
  const scrape = new Set(scrapeFields);
  const seen = new Set<ScrapeTask["fields"][number]>();
  const out: ScrapeTask["fields"] = [];
  for (const item of raw || []) {
    if (!allow.has(item) || !scrape.has(item) || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

const DEFAULT_ORIGIN_HOST = "127.0.0.1:9210";
const DEFAULT_LIBRARY_REL = "data/library";
const FALLBACK_LIBRARY_OPTIONS: ScrapeLibraryOption[] = [
  { value: DEFAULT_LIBRARY_REL, label: "data/library（默认）" },
];

/** 展示/编辑用：host:port */
function toOriginHostPort(raw: string | null | undefined): string {
  const s = String(raw || "").trim();
  if (!s) return DEFAULT_ORIGIN_HOST;
  try {
    const u = new URL(/^https?:\/\//i.test(s) ? s : `http://${s}`);
    return u.port ? `${u.hostname}:${u.port}` : u.hostname;
  } catch {
    return s.replace(/^https?:\/\//i, "").replace(/\/+$/, "") || DEFAULT_ORIGIN_HOST;
  }
}

/** 请求用：补全 http:// */
function toOriginUrl(raw: string | null | undefined): string {
  const host = toOriginHostPort(raw);
  return `http://${host}`;
}

/** 英雄条 / 设置中心：9210 真实连通短文案 */
function scrapeLinkLabel(
  online: boolean | null,
  opts?: { running?: boolean; configured?: boolean; loading?: boolean },
): string {
  if (opts?.loading || online == null) return "检测中";
  if (opts?.running) return "刮削中";
  if (opts?.configured === false) return "未配置";
  return online ? '已在线' : '离线';
}

function scrapeLinkTone(
  online: boolean | null,
  opts?: { running?: boolean; configured?: boolean; loading?: boolean },
): "ok" | "warn" | "mute" | "loading" {
  if (opts?.loading || online == null) return "loading";
  if (opts?.running) return "ok";
  if (opts?.configured === false) return "warn";
  return online ? "ok" : "warn";
}

function applyScrapeConfig(
  d: ScrapeConfig,
  setters: {
    setCfg: (v: ScrapeConfig) => void;
    setOrigin: (v: string) => void;
    setLibraryRoot: (v: string) => void;
    setLibraryOptions: (v: ScrapeLibraryOption[]) => void;
    setFlareSolverrUrl: (v: string) => void;
    setProxyUrl: (v: string) => void;
    setCoverDownloadStrategy: (v: CoverDownloadStrategy) => void;
    setExportFastConcurrency: (v: number) => void;
    setExportSlowConcurrency: (v: number) => void;
    setMetadataOptimize: (v: MetadataOptimizeConfig) => void;
    setKindProfiles: (v: Record<string, ScrapeRegionProfile>) => void;
    setSources: (v: ScrapeSourceCard[]) => void;
    setRetryDefault: (v: number) => void;
    setScrapeTasks: (v: ScrapeTask[]) => void;
  },
) {
  setters.setCfg(d);
  setters.setOrigin(toOriginHostPort(d.origin));
  const lib =
    String(d.libraryRoot || "")
      .trim()
      .replace(/\\/g, "/") || DEFAULT_LIBRARY_REL;
  // 旧绝对路径 / 非法值 → 默认相对路径
  const libRel = lib.startsWith("data/") ? lib : DEFAULT_LIBRARY_REL;
  setters.setLibraryRoot(libRel);
  const opts = d.libraryOptions?.length
    ? d.libraryOptions
    : FALLBACK_LIBRARY_OPTIONS;
  // 当前值若不在列表中，补一条以免 select 空白
  setters.setLibraryOptions(
    opts.some((o) => o.value === libRel)
      ? opts
      : [{ value: libRel, label: libRel }, ...opts],
  );
  setters.setFlareSolverrUrl(d.flareSolverrUrl || "");
  setters.setProxyUrl(d.proxyUrl || "");
  setters.setCoverDownloadStrategy(
    d.coverDownloadStrategy === "size" ? "size" : "priority",
  );
  const legacyConc = Math.max(1, Math.min(4, Number(d.exportConcurrency) || 2));
  const fastConc = Math.max(
    1,
    Math.min(4, Number(d.exportFastConcurrency) || Math.min(legacyConc, 2)),
  );
  const slowConc = Math.max(
    1,
    Math.min(4, Number(d.exportSlowConcurrency) || Math.min(legacyConc, 1)),
  );
  setters.setExportFastConcurrency(fastConc);
  setters.setExportSlowConcurrency(slowConc);
  setters.setMetadataOptimize(normalizeMetadataOptimize(d.metadataOptimize));
  const profiles = d.kindProfiles || d.regionProfiles;
  if (profiles) setters.setKindProfiles(profiles);
  if (d.sources?.length) setters.setSources(d.sources);
  if (d.retry?.defaultRetry != null) {
    setters.setRetryDefault(Number(d.retry.defaultRetry) || 0);
  }
  // 与文案一致：可同时保留多张任务卡（上限 12）；合计不足时抬高，不压成功数
  setters.setScrapeTasks(
    (d.scrapeTasks || []).slice(0, 12).map((t) => {
      const s = taskStats(t);
      const prevDone = Number(t.done || 0);
      const prevEmpty = Number(t.empty || 0);
      const prevFail = Number(t.failed || 0);
      const prevTotal = Number(t.total || 0);
      if (
        s.done === prevDone &&
        s.empty === prevEmpty &&
        s.failed === prevFail &&
        s.total === prevTotal
      ) {
        return t;
      }
      const ls = String(t.lastStatus || "");
      const nextStatus = ls.startsWith("完成")
        ? `完成 · 成功 ${s.done} · 空号 ${s.empty} · 数据不全 ${s.failed}`
        : t.lastStatus;
      return {
        ...t,
        done: s.done,
        empty: s.empty,
        skipped: 0,
        failed: s.failed,
        total: s.total || t.total,
        lastStatus: nextStatus,
      };
    }),
  );
}

export function ScrapePanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const { toast } = useOverlay();
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  const [tab, setTab] = useState<ScrapeTab>("config");

  const [cfg, setCfg] = useState<ScrapeConfig | null>(null);
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN_HOST);
  const [libraryRoot, setLibraryRoot] = useState(DEFAULT_LIBRARY_REL);
  const [libraryOptions, setLibraryOptions] = useState<ScrapeLibraryOption[]>(
    FALLBACK_LIBRARY_OPTIONS,
  );
  const [flareSolverrUrl, setFlareSolverrUrl] = useState("");
  const [proxyUrl, setProxyUrl] = useState("");
  const [coverDownloadStrategy, setCoverDownloadStrategy] =
    useState<CoverDownloadStrategy>("priority");
  const [exportFastConcurrency, setExportFastConcurrency] = useState(2);
  const [exportSlowConcurrency, setExportSlowConcurrency] = useState(1);
  const [fastConcurrencyText, setFastConcurrencyText] = useState("2");
  const [slowConcurrencyText, setSlowConcurrencyText] = useState("1");
  const [metadataOptimize, setMetadataOptimize] = useState<MetadataOptimizeConfig>(
    DEFAULT_METADATA_OPTIMIZE,
  );

  const [kindProfiles, setKindProfiles] = useState<
    Record<string, ScrapeRegionProfile>
  >({});
  const [sources, setSources] = useState<ScrapeSourceCard[]>([]);
  const [retryDefault, setRetryDefault] = useState(0);
  const [scrapeTasks, setScrapeTasks] = useState<ScrapeTask[]>([]);

  const [regions, setRegions] = useState<MakerFsRegionSummary[]>([]);
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<ScrapeTask | null>(null);

  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState<{
    taskId: string;
    title: string;
    mode: "cancel" | "delete-running";
  } | null>(null);
  /** 任务卡统计点击：成功/空号/失败/进行中/合计 番号明细 */
  const [statCodesOpen, setStatCodesOpen] = useState<{
    title: string;
    status: string;
    tone: "ok" | "run" | "mute" | "err" | "total";
    codes: string[];
    task: ScrapeTask;
  } | null>(null);
  const [statRescrapeBusy, setStatRescrapeBusy] = useState(false);
  /** 从番号列表点进进度页「详细数据」 */
  const [focusDetail, setFocusDetail] = useState<{
    code: string;
    nonce: number;
  } | null>(null);
  /** 进度页钉住番号：不自动跟到下一片；点「回到当前」清空 */
  const [stickCode, setStickCode] = useState<string | null>(null);
  const [progressRefreshNonce, setProgressRefreshNonce] = useState(0);
  const [progress, setProgress] = useState<ScrapeExportStatus | null>(null);
  /** null=探测中；true/false=9210 /health 结果 */
  const [linkOnline, setLinkOnline] = useState<boolean | null>(null);

  const applyCfg = useCallback((d: ScrapeConfig) => {
    applyScrapeConfig(d, {
      setCfg,
      setOrigin,
      setLibraryRoot,
      setLibraryOptions,
      setFlareSolverrUrl,
      setProxyUrl,
      setCoverDownloadStrategy,
      setExportFastConcurrency: (v: number) => {
        setExportFastConcurrency(v);
        setFastConcurrencyText(String(v));
      },
      setExportSlowConcurrency: (v: number) => {
        setExportSlowConcurrency(v);
        setSlowConcurrencyText(String(v));
      },
      setMetadataOptimize,
      setKindProfiles,
      setSources,
      setRetryDefault,
      setScrapeTasks,
    });
    if (typeof d.online === "boolean") setLinkOnline(d.online);
  }, []);

  const publishLinkStatus = useCallback(
    (online: boolean | null, running?: boolean, configured?: boolean, paused?: boolean) => {
      if (running) {
        onStatusRef.current?.(paused ? '已暂停' : '刮削中', paused ? 'warn' : 'mute');
        return;
      }
      const text = scrapeLinkLabel(online, {
        running,
        configured,
        loading: online == null,
      });
      const tone = scrapeLinkTone(online, {
        running,
        configured,
        loading: online == null,
      });
      const hubTone: 'ok' | 'warn' | 'mute' =
        tone === 'loading' ? 'mute' : tone === 'ok' ? 'ok' : 'warn';
      onStatusRef.current?.(text, hubTone);
    },
    [],
  );

  const probeLink = useCallback(async () => {
    try {
      const r = await testScrape({
        enabled: true,
        origin: toOriginUrl(DEFAULT_ORIGIN_HOST),
      });
      setLinkOnline(r.ok);
      return r.ok;
    } catch {
      setLinkOnline(false);
      return false;
    }
  }, []);

  const loadRegions = useCallback(async () => {
    try {
      const overview = await fetchMakerFsRegions();
      setRegions(overview.regions?.length ? overview.regions : FALLBACK_REGIONS);
    } catch {
      setRegions(FALLBACK_REGIONS);
    }
  }, []);

  useEffect(() => {
    void getScrape()
      .then((d) => {
        applyCfg(d);
        const online = typeof d.online === "boolean" ? d.online : null;
        setLinkOnline(online);
        publishLinkStatus(online, false, d.configured);
        // GET 已探活；未登录时 test 会失败，不必再打
        if (online == null) void probeLink().then((ok) => publishLinkStatus(ok, false, d.configured));
      })
      .catch((e: unknown) => {
        setLinkOnline(false);
        publishLinkStatus(false, false, false);
        toast(e instanceof Error ? e.message : "读取失败", "error");
      });
    void loadRegions();
    void fetchScrapeExportStatus()
      .then((st) => setProgress(st))
      .catch(() => {});
  }, [applyCfg, loadRegions, probeLink, publishLinkStatus, toast]);

  // 面板打开时周期性复探 :9210，启停服务后状态会跟上
  useEffect(() => {
    let cancelled = false;
    const id = window.setInterval(() => {
      void getScrape()
        .then((d) => {
          if (cancelled) return;
          if (typeof d.online === "boolean") {
            setLinkOnline(d.online);
            publishLinkStatus(
              d.online,
              exporting || Boolean(progress?.running),
              d.configured,
            );
          }
        })
        .catch(() => {
          if (cancelled) return;
          setLinkOnline(false);
          publishLinkStatus(false, exporting || Boolean(progress?.running), true);
        });
    }, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [exporting, progress?.running, publishLinkStatus]);

  useEffect(() => {
    if (tab !== "progress" && tab !== "task") return;
    let cancelled = false;
    let inFlight = false;
    let lastTaskId = "";
    let wasBusy = false;
    let timer: number | null = null;
    const busyRef = { current: Boolean(exporting || progress?.running) };

    const schedule = () => {
      if (cancelled) return;
      if (timer != null) window.clearTimeout(timer);
      // 运行中 1.5s；空闲 5s。用 setTimeout 链，避免 interval + 慢请求叠死
      const delay = busyRef.current ? 1500 : 5000;
      timer = window.setTimeout(() => void tick(), delay);
    };

    const tick = async () => {
      if (cancelled) return;
      if (inFlight) return;
      inFlight = true;
      const ac = new AbortController();
      const kill = window.setTimeout(() => ac.abort(), 12000);
      try {
        const st = await fetchScrapeExportStatus(ac.signal);
        if (cancelled) return;
        setProgress(st);
        const busyExport =
          Boolean(st.running) || Boolean(st.queue && st.queue.length);
        busyRef.current = busyExport;
        setExporting(busyExport);
        const tid = String(st.taskId || "");
        // 任务切换或整队结束：从设置拉回各卡 lastStatus/统计
        const finishedWave = wasBusy && !busyExport;
        const switched =
          Boolean(lastTaskId) && tid && tid !== lastTaskId;
        if (finishedWave || switched) {
          try {
            const cfgNext = await getScrape();
            if (!cancelled) applyCfg(cfgNext);
          } catch {
            /* ignore */
          }
        } else if (busyExport) {
          // 运行中纠偏：把非本卡的过期 running/排队中 徽章清掉，避免多卡同时「进行中」
          // 同时把本卡终身计数与本轮进度合并进本地状态（开跑不清零）
          const liveTid = tid;
          const queuedIds = new Set(
            (st.queue || [])
              .map((q) => String(q.taskId || "").trim())
              .filter(Boolean),
          );
          setScrapeTasks((prev) => {
            let dirty = false;
            const patched = prev.map((t) => {
              const id = String(t.id || "").trim();
              const ls = String(t.lastStatus || "").trim();
              let next = t;
              if (id && id === liveTid && (st.running || st.paused)) {
                const truncated = Boolean(st.codesTruncated);
                if (truncated) {
                  // 轮询未带全量列表：只抬高计数，不覆盖番号数组
                  const nextDone = Math.max(
                    Number(t.done || 0),
                    Number(st.done || 0),
                  );
                  const nextEmpty = Math.max(
                    Number(t.empty || 0),
                    Number(st.empty || 0),
                  );
                  const nextFail = Math.max(
                    Number(t.failed || 0),
                    Number(st.failed || 0),
                  );
                  const nextTotal = Math.max(
                    Number(t.total || 0),
                    Number(st.total || 0),
                    nextDone + nextEmpty + nextFail,
                  );
                  if (
                    nextDone !== Number(t.done || 0) ||
                    nextEmpty !== Number(t.empty || 0) ||
                    nextFail !== Number(t.failed || 0) ||
                    nextTotal !== Number(t.total || 0)
                  ) {
                    dirty = true;
                    next = {
                      ...t,
                      done: nextDone,
                      empty: nextEmpty,
                      skipped: 0,
                      failed: nextFail,
                      total: nextTotal,
                    };
                  }
                } else {
                  // 列表未截断时也可合并预览；计数必须取数字字段的较大值
                  const merged = mergeLifetimeBuckets(
                    {
                      done: t.doneCodes || [],
                      empty: [
                        ...(t.emptyCodes || []),
                        ...(t.skippedCodes || []),
                      ],
                      failed: t.failedCodes || [],
                    },
                    {
                      done: st.doneCodes || [],
                      empty: [
                        ...(st.emptyCodes || []),
                        ...(st.skippedCodes || []),
                      ],
                      failed: st.failedCodes || [],
                    },
                  );
                  const nextDone = Math.max(
                    Number(t.done || 0),
                    Number(st.done || 0),
                    merged.done,
                  );
                  const nextEmpty = Math.max(
                    Number(t.empty || 0),
                    Number(st.empty || 0),
                    merged.empty,
                  );
                  const nextFail = Math.max(
                    Number(t.failed || 0),
                    Number(st.failed || 0),
                    merged.failed,
                  );
                  const nextTotal = Math.max(
                    Number(t.total || 0),
                    Number(st.total || 0),
                    nextDone + nextEmpty + nextFail,
                  );
                  const previewCap = 200;
                  const nextDoneCodes = merged.doneCodes.slice(-previewCap);
                  const nextEmptyCodes = merged.emptyCodes.slice(-previewCap);
                  const nextFailCodes = merged.failedCodes.slice(-previewCap);
                  if (
                    nextDone !== Number(t.done || 0) ||
                    nextEmpty !== Number(t.empty || 0) ||
                    nextFail !== Number(t.failed || 0) ||
                    nextTotal !== Number(t.total || 0) ||
                    nextDoneCodes.length !== (t.doneCodes || []).length ||
                    nextEmptyCodes.length !== (t.emptyCodes || []).length ||
                    nextFailCodes.length !== (t.failedCodes || []).length
                  ) {
                    dirty = true;
                    next = {
                      ...t,
                      done: nextDone,
                      empty: nextEmpty,
                      skipped: 0,
                      failed: nextFail,
                      total: nextTotal,
                      doneCodes: nextDoneCodes,
                      emptyCodes: nextEmptyCodes,
                      skippedCodes: [],
                      failedCodes: nextFailCodes,
                    };
                  }
                }
              }
              if (ls !== "running" && ls !== "排队中") return next;
              if (id && id === liveTid && st.running) {
                if (ls === "running" && next === t) return next;
                dirty = true;
                return { ...next, lastStatus: "running" };
              }
              if (id && queuedIds.has(id)) {
                if (ls === "排队中" && next === t) return next;
                dirty = true;
                return { ...next, lastStatus: "排队中" };
              }
              dirty = true;
              return { ...next, lastStatus: "" };
            });
            return dirty ? patched : prev;
          });
        }
        lastTaskId = tid;
        wasBusy = busyExport;
      } catch {
        /* ignore — 超时/中止后继续排程，勿永久卡住 */
      } finally {
        window.clearTimeout(kill);
        inFlight = false;
        schedule();
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer != null) window.clearTimeout(timer);
    };
    // 仅随 tab 启停轮询；忙闲节奏用 busyRef，避免 running 抖动反复 teardown
  }, [tab, applyCfg]);

  const running = exporting || Boolean(progress?.running);
  const tone = scrapeLinkTone(linkOnline, {
    running,
    configured: cfg?.configured,
    loading: !cfg || linkOnline == null,
  });
  const statusText = scrapeLinkLabel(linkOnline, {
    running,
    configured: cfg?.configured,
    loading: !cfg || linkOnline == null,
  });
  const regionList = regions.length ? regions : FALLBACK_REGIONS;

  function regionLabels(ids: string[]): string {
    return ids
      .map((id) => regionList.find((r) => r.id === id)?.label || id)
      .filter(Boolean)
      .join(" · ");
  }

  async function onSave() {
    setBusy(true);
    try {
      const next = await putScrape({
        enabled: true,
        // 单容器内置：地址不开放填写，固定本机 scrape
        origin: toOriginUrl(DEFAULT_ORIGIN_HOST),
        libraryRoot: libraryRoot.trim() || DEFAULT_LIBRARY_REL,
        coverDownloadStrategy,
        exportFastConcurrency,
        exportSlowConcurrency,
        exportConcurrency: Math.max(
          exportFastConcurrency,
          exportSlowConcurrency,
        ),
        metadataOptimize,
        kindProfiles,
        regionProfiles: kindProfiles,
        sources,
        retry: { defaultRetry: retryDefault },
      });
      applyCfg(next);
      const online = typeof next.online === "boolean" ? next.online : await probeLink();
      setLinkOnline(online);
      publishLinkStatus(online, running, next.configured);
      toast("刮削配置已保存", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "保存失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onPauseExport() {
    setControlBusy(true);
    try {
      const st = await pauseScrapeExport();
      setProgress(st);
      toast("已暂停", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "暂停失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  async function onResumeExport() {
    setControlBusy(true);
    try {
      const st = await resumeScrapeExport();
      setProgress(st);
      setExporting(
        Boolean(st.running) || Boolean(st.queue && st.queue.length),
      );
      toast("已继续", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "继续失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  async function onConfirmStopTask() {
    const conf = confirmClear;
    setConfirmClear(null);
    if (!conf?.taskId) return;
    setControlBusy(true);
    try {
      const st = await cancelScrapeExportTask(conf.taskId);
      setProgress(hasProgressCard(st, false) ? st : null);
      setExporting(
        Boolean(st.running) || Boolean(st.queue && st.queue.length),
      );
      if (conf.mode === "delete-running") {
        try {
          await purgeScrapeTaskLogs(conf.taskId);
        } catch {
          /* 无日志也可删卡 */
        }
        const next = scrapeTasks.filter((t) => t.id !== conf.taskId);
        await persistTasks(next);
        toast("已取消并删除任务", "info");
      } else {
        const next = scrapeTasks.map((t) =>
          t.id === conf.taskId
            ? {
                ...t,
                lastStatus: "已取消",
                updatedAt: new Date().toISOString(),
              }
            : t,
        );
        await persistTasks(next);
        toast("已取消该任务", "info");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "操作失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  async function persistTasks(nextTasks: ScrapeTask[]) {
    const saved = await putScrape({
      enabled: true,
      origin: toOriginUrl(DEFAULT_ORIGIN_HOST),
      scrapeTasks: nextTasks.slice(0, 12),
    });
    applyCfg(saved);
    return saved;
  }

  /** 删除任务卡：只动本卡；若本卡在跑/排队则先按 taskId 停止，不清其它任务 */
  async function onDeleteTask(taskId?: string) {
    const tid = String(taskId || "").trim();
    if (!tid) return;
    setControlBusy(true);
    try {
      const target = scrapeTasks.find((t) => t.id === tid);
      const mineLive = target
        ? progressBelongsToTask(progress, target)
        : false;
      const mineQueued = target ? taskIsQueued(progress, target) : false;
      if (mineLive || mineQueued) {
        try {
          const st = await clearScrapeExport({ taskId: tid });
          setProgress(hasProgressCard(st, false) ? st : null);
          setExporting(
            Boolean(st.running) || Boolean(st.queue && st.queue.length),
          );
        } catch {
          /* 已不在跑/排队 */
        }
      }
      try {
        await purgeScrapeTaskLogs(tid);
      } catch {
        /* 无库内日志也可删卡 */
      }
      const next = scrapeTasks.filter((t) => t.id !== tid);
      await persistTasks(next);
      toast(next.length ? "已删除任务" : "已清空任务", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "删除失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  /** 仅移出队列，保留任务卡 */
  async function onDequeueTask(task: ScrapeTask) {
    setControlBusy(true);
    try {
      if (!taskIsQueued(progress, task) && !progressBelongsToTask(progress, task)) {
        toast("该任务不在队列中", "info");
        return;
      }
      const st = await clearScrapeExport({ taskId: task.id });
      setProgress(hasProgressCard(st, false) ? st : null);
      setExporting(
        Boolean(st.running) || Boolean(st.queue && st.queue.length),
      );
      const next = scrapeTasks.map((t) =>
        t.id === task.id
          ? {
              ...t,
              lastStatus: "",
              updatedAt: new Date().toISOString(),
            }
          : t,
      );
      await persistTasks(next);
      toast("已移出队列", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "移出队列失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  function draftFromTask(task: ScrapeTask): ScrapeTaskDraft {
    const fields = normalizeTaskFields(task.fields);
    return {
      id: task.id,
      name: task.name || "",
      regions: [...(task.regions || [])],
      maker: task.maker || "",
      prefix: task.prefix || "",
      code: task.code || "",
      mode: task.mode === "force" ? "force" : "incremental",
      fields,
      localFields: normalizeLocalFields(task.localFields, fields),
      watchEnabled: Boolean(task.watchEnabled),
    };
  }

  async function onRerunTask(task: ScrapeTask) {
    await onStartTask(draftFromTask(task));
  }

  /** 弹窗内自动保存：不关弹窗、不 toast；失败才提示。暂停中会热更新到当前导出。 */
  async function onSaveTask(draft: ScrapeTaskDraft, opts?: { toastOk?: boolean }) {
    try {
      const now = new Date().toISOString();
      const prev = scrapeTasks.find((t) => t.id === draft.id);
      const fields = normalizeTaskFields(draft.fields);
      const nextTask: ScrapeTask = {
        id: draft.id,
        name: draft.name || draft.prefix || draft.maker || "刮削任务",
        regions: draft.regions,
        maker: draft.maker || "",
        prefix: draft.prefix || "",
        code: draft.code || "",
        mode: draft.mode,
        fields,
        localFields: normalizeLocalFields(draft.localFields, fields),
        watchEnabled: Boolean(draft.watchEnabled),
        watchArmed: Boolean(draft.watchEnabled) ? Boolean(prev?.watchArmed) : false,
        lastStatus: prev?.lastStatus || "",
        done: prev?.done,
        empty: prev?.empty,
        skipped: prev?.skipped,
        failed: prev?.failed,
        total: prev?.total,
        doneCodes: prev?.doneCodes,
        emptyCodes: prev?.emptyCodes,
        skippedCodes: prev?.skippedCodes,
        failedCodes: prev?.failedCodes,
        updatedAt: now,
      };
      // 保序：只替换本卡，不把编辑项顶到列表第一
      const nextTasks = scrapeTasks.map((t) =>
        t.id === draft.id ? nextTask : t,
      );
      if (!scrapeTasks.some((t) => t.id === draft.id)) {
        nextTasks.unshift(nextTask);
      }
      await persistTasks(nextTasks.slice(0, 12));
      // 若正在编辑当前暂停/运行任务，立刻拉进度（后端已热更新 mode/fields）
      if (progressBelongsToTask(progress, nextTask)) {
        try {
          const st = await fetchScrapeExportStatus();
          setProgress(st);
        } catch {
          /* ignore */
        }
      }
      if (opts?.toastOk) toast("已保存", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "保存失败", "error");
    }
  }

  async function onToggleWatch(task: ScrapeTask) {
    const nextOn = !task.watchEnabled;
    setControlBusy(true);
    try {
      const nextTasks = scrapeTasks.map((t) =>
        t.id === task.id
          ? {
              ...t,
              watchEnabled: nextOn,
              // 关掉监控时解除武装；开启后仍需手动跑完一轮
              watchArmed: nextOn ? Boolean(t.watchArmed) : false,
              updatedAt: new Date().toISOString(),
            }
          : t,
      );
      await persistTasks(nextTasks);
      toast(
        nextOn
          ? "监控已开启（需手动开始并跑完一轮后才会自动增量）"
          : "监控已关闭",
        "info",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "更新失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  /** 重置任务：清本卡进度统计 + 断点；若本卡在跑则只停本卡，不影响其它排队 */
  async function onResetTask(task: ScrapeTask) {
    const mine = progressBelongsToTask(progress, task);
    const mineQueued = taskIsQueued(progress, task);
    setControlBusy(true);
    try {
      // 先清断点/内存计数并打 discard 标记，避免随后 cancel 收尾把旧数字 max 写回
      let st: ScrapeExportStatus | null = null;
      try {
        st = await resetScrapeExportCheckpoint(task.id);
      } catch {
        /* 无断点也可忽略 */
      }
      if (mine || mineQueued) {
        try {
          st = await clearScrapeExport({ taskId: task.id });
        } catch {
          /* 已 idle */
        }
      }
      const zeroed: ScrapeExportStatus | null = st
        ? {
            ...st,
            done: 0,
            empty: 0,
            skipped: 0,
            failed: 0,
            total: 0,
            doneCodes: [],
            emptyCodes: [],
            skippedCodes: [],
            failedCodes: [],
            pauseSaved: false,
            resumable: false,
            paused: false,
          }
        : null;
      setProgress(
        zeroed && hasProgressCard(zeroed, Boolean(zeroed.running))
          ? zeroed
          : null,
      );
      setExporting(
        Boolean(zeroed?.running) || Boolean(zeroed?.queue && zeroed.queue.length),
      );
      const next = scrapeTasks.map((t) =>
        t.id === task.id
          ? {
              ...t,
              lastStatus: "",
              watchArmed: false,
              done: 0,
              empty: 0,
              skipped: 0,
              failed: 0,
              total: 0,
              doneCodes: [],
              emptyCodes: [],
              skippedCodes: [],
              failedCodes: [],
              updatedAt: new Date().toISOString(),
            }
          : t,
      );
      await persistTasks(next);
      toast("已重置任务", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "重置失败", "error");
    } finally {
      setControlBusy(false);
    }
  }

  /** 失败重试：增量模式，跳过已成功，只补失败/缺失 */
  async function onRetryFailed(task: ScrapeTask) {
    // 本卡暂停/进行中：先停掉本卡，再入队增量补刮（不动其它排队）
    if (
      progressBelongsToTask(progress, task) &&
      (Boolean(progress?.running) || Boolean(progress?.queue?.length))
    ) {
      setControlBusy(true);
      try {
        const st = await clearScrapeExport({ taskId: task.id });
        setProgress(hasProgressCard(st, false) ? st : null);
        setExporting(
          Boolean(st.running) || Boolean(st.queue && st.queue.length),
        );
      } catch (e) {
        toast(e instanceof Error ? e.message : "停止当前任务失败", "error");
        setControlBusy(false);
        return;
      } finally {
        setControlBusy(false);
      }
    }
    await onStartTask({
      ...draftFromTask(task),
      mode: "incremental",
    });
  }

  async function enqueueTaskDraft(
    draft: ScrapeTaskDraft,
    opts?: { switchTab?: boolean; signal?: AbortSignal },
  ): Promise<ScrapeExportStatus> {
    const switchTab = Boolean(opts?.switchTab);
    const now = new Date().toISOString();
    const name = draft.name || draft.prefix || draft.maker || "刮削任务";
    const fields = normalizeTaskFields(draft.fields);
    const localFields = normalizeLocalFields(draft.localFields, fields);
    const prev = scrapeTasks.find((t) => t.id === draft.id);
    // 任务卡计数是终身累计：点开始不清零，仅「重置任务」清空
    const nextTask: ScrapeTask = {
      id: draft.id,
      name,
      regions: draft.regions,
      maker: draft.maker || "",
      prefix: draft.prefix || "",
      code: draft.code || "",
      mode: draft.mode,
      fields,
      localFields,
      watchEnabled: Boolean(draft.watchEnabled),
      watchArmed: Boolean(draft.watchEnabled) ? Boolean(prev?.watchArmed) : false,
      lastStatus: "running",
      done: Number(prev?.done || 0),
      empty: Number(prev?.empty || 0),
      skipped: Number(prev?.skipped || 0),
      failed: Number(prev?.failed || 0),
      total: Number(prev?.total || 0),
      doneCodes: [...(prev?.doneCodes || [])],
      emptyCodes: [...(prev?.emptyCodes || [])],
      skippedCodes: [...(prev?.skippedCodes || [])],
      failedCodes: [...(prev?.failedCodes || [])],
      updatedAt: now,
    };
    const nextTasks = scrapeTasks.map((t) =>
      t.id === draft.id ? nextTask : t,
    );
    if (!scrapeTasks.some((t) => t.id === draft.id)) {
      nextTasks.unshift(nextTask);
    }
    await persistTasks(nextTasks.slice(0, 12));
    const st = await startScrapeExport({
      taskId: draft.id,
      name,
      regions: draft.regions,
      maker: draft.maker || undefined,
      prefix: draft.prefix || undefined,
      code: draft.code || undefined,
      mode: draft.mode,
      force: draft.mode === "force",
      fields,
      localFields,
      signal: opts?.signal,
    });
    setProgress(st);
    const busyExport =
      Boolean(st.running) || Boolean(st.queue && st.queue.length);
    setExporting(busyExport);
    const mineRunning = st.running && String(st.taskId || "") === draft.id;
    const mineQueued = (st.queue || []).some(
      (q) => String(q.taskId || "") === draft.id,
    );
    const statusLabel = mineQueued
      ? "排队中"
      : mineRunning
        ? "running"
        : nextTask.lastStatus;
    if (statusLabel !== nextTask.lastStatus) {
      const patched = nextTasks.map((t) =>
        t.id === draft.id
          ? {
              ...t,
              lastStatus: statusLabel,
              updatedAt: new Date().toISOString(),
            }
          : t,
      );
      try {
        await persistTasks(patched.slice(0, 12));
      } catch {
        setScrapeTasks(patched.slice(0, 12));
      }
    }
    if (switchTab) setTab("progress");
    return st;
  }

  async function onRescrapeCodes(codes: string[], opts?: { closeModal?: boolean }) {
    const ctx = statCodesOpen;
    if (!ctx?.task || !codes.length || statRescrapeBusy) return;
    const task = ctx.task;
    const list = [
      ...new Set(
        codes
          .map((c) => String(c || "").trim().toUpperCase().replace(/_/g, "-"))
          .filter(Boolean),
      ),
    ];
    if (!list.length) return;
    setStatRescrapeBusy(true);
    try {
      const st = await startScrapeExport({
        taskId: task.id,
        name: task.name || undefined,
        regions: task.regions?.length ? task.regions : undefined,
        maker: task.maker || undefined,
        prefix: task.prefix || undefined,
        codes: list,
        mode: "force",
        force: true,
        fields: task.fields,
        localFields: task.localFields,
      });
      setProgress(st);
      const busyExport =
        Boolean(st.running) || Boolean(st.queue && st.queue.length);
      setExporting(busyExport);
      if (opts?.closeModal !== false) setStatCodesOpen(null);
      setTab("progress");
      const mineQueued = (st.queue || []).some(
        (q) => String(q.taskId || "") === task.id,
      );
      const mineRunning = st.running && String(st.taskId || "") === task.id;
      if (mineQueued) toast(`已排队强制重刮 ${list.length} 个`, "info");
      else if (mineRunning)
        toast(
          list.length === 1
            ? `正在强制重刮 ${list[0]}`
            : `正在强制重刮 ${list.length} 个`,
          "info",
        );
      else toast("已提交强制重刮", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "强制重刮失败", "error");
    } finally {
      setStatRescrapeBusy(false);
    }
  }

  async function onStartTask(draft: ScrapeTaskDraft) {
    setBusy(true);
    setTaskModalOpen(false);
    setEditingTask(null);
    const ac = new AbortController();
    const kill = window.setTimeout(() => ac.abort(), 20000);
    try {
      const st = await enqueueTaskDraft(draft, {
        switchTab: false,
        signal: ac.signal,
      });
      const mineQueued = (st.queue || []).some(
        (q) => String(q.taskId || "") === draft.id,
      );
      const mineRunning = st.running && String(st.taskId || "") === draft.id;
      if (mineQueued) toast("已加入队列，将依次刮削", "info");
      else if (mineRunning) toast("正在刮削…", "info");
      else toast("已提交", "info");
    } catch (e) {
      const aborted =
        (e instanceof DOMException && e.name === "AbortError") ||
        (e instanceof Error && /abort|timeout|超时/i.test(e.message));
      toast(
        aborted
          ? "启动超时：API 无响应，请重启 API 后再试"
          : e instanceof Error
            ? e.message
            : "刮削失败",
        "error",
      );
    } finally {
      window.clearTimeout(kill);
      setBusy(false);
    }
  }

  async function onStartAllTasks() {
    if (!scrapeTasks.length) {
      toast("还没有刮削任务", "info");
      return;
    }
    setBusy(true);
    try {
      const now = new Date().toISOString();
      const ordered = scrapeTasks.slice(0, 12);
      const marked = ordered.map((t) => ({
        ...t,
        lastStatus: "排队中",
        updatedAt: now,
      }));
      await persistTasks(marked);
      let started = 0;
      let queued = 0;
      let last: ScrapeExportStatus | null = null;
      for (const task of ordered) {
        const fields = normalizeTaskFields(task.fields);
        const st = await startScrapeExport({
          taskId: task.id,
          name: task.name || task.prefix || task.maker || "刮削任务",
          regions: task.regions,
          maker: task.maker || undefined,
          prefix: task.prefix || undefined,
          code: task.code || undefined,
          mode: task.mode === "force" ? "force" : "incremental",
          force: task.mode === "force",
          fields,
          localFields: normalizeLocalFields(task.localFields, fields),
        });
        last = st;
        if ((st.queue || []).some((q) => String(q.taskId || "") === task.id)) {
          queued += 1;
        } else if (st.running && String(st.taskId || "") === task.id) {
          started += 1;
        }
      }
      if (last) {
        setProgress(last);
        setExporting(
          Boolean(last.running) || Boolean(last.queue && last.queue.length),
        );
      }
      toast(
        started || queued
          ? `已启动 ${started} 个，排队 ${queued} 个`
          : "已提交全部任务",
        "info",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "启动失败", "error");
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <>
        <ul className="settings-group scrape-status-row" aria-label="刮削服务状态">
          <li>
            <div className="settings-nav" style={{ pointerEvents: 'none' }}>
              <span className="settings-nav__main">
                <span className="settings-nav__title">刮削服务</span>
                <span className="settings-nav__desc">内置 :9210</span>
              </span>
              <span
                className={`settings-status-pill settings-nav__status settings-nav__status--${tone}`}
              >
                <span className="settings-nav__dot" aria-hidden />
                <span>{statusText}</span>
              </span>
            </div>
          </li>
        </ul>

        <div className="scrape-tabs" role="tablist" aria-label="刮削分页">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={
                tab === t.key
                  ? "scrape-tabs__btn scrape-tabs__btn--active"
                  : "scrape-tabs__btn"
              }
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "config" ? (
          <div className="scrape-pane">
            <div className="scrape-pane-card">
              <div className="scrape-pane-card__band">服务配置</div>
              <div className="scrape-pane-field">
                <span className="scrape-pane-field__label">默认库</span>
                <span className="scrape-pane-field__value allow-select">
                  {libraryOptions.find((o) => o.value === libraryRoot)?.label ||
                    libraryRoot}
                </span>
              </div>
              <label className="scrape-pane-field">
                <span className="scrape-pane-field__label">快源并发</span>
                <input
                  className="scrape-pane-field__input"
                  type="text"
                  inputMode="numeric"
                  pattern="[1-4]"
                  value={fastConcurrencyText}
                  disabled={busy || exporting}
                  onChange={(e) => {
                    const raw = e.target.value.replace(/\D/g, "").slice(0, 1);
                    setFastConcurrencyText(raw);
                    if (!raw) return;
                    const n = Number(raw);
                    if (n >= 1 && n <= 4) setExportFastConcurrency(n);
                  }}
                  onBlur={() => {
                    const n = Math.max(
                      1,
                      Math.min(4, Number(fastConcurrencyText) || 2),
                    );
                    setExportFastConcurrency(n);
                    setFastConcurrencyText(String(n));
                  }}
                  placeholder="2"
                  autoComplete="off"
                />
              </label>
              <label className="scrape-pane-field">
                <span className="scrape-pane-field__label">慢源并发</span>
                <input
                  className="scrape-pane-field__input"
                  type="text"
                  inputMode="numeric"
                  pattern="[1-4]"
                  value={slowConcurrencyText}
                  disabled={busy || exporting}
                  onChange={(e) => {
                    const raw = e.target.value.replace(/\D/g, "").slice(0, 1);
                    setSlowConcurrencyText(raw);
                    if (!raw) return;
                    const n = Number(raw);
                    if (n >= 1 && n <= 4) setExportSlowConcurrency(n);
                  }}
                  onBlur={() => {
                    const n = Math.max(
                      1,
                      Math.min(4, Number(slowConcurrencyText) || 1),
                    );
                    setExportSlowConcurrency(n);
                    setSlowConcurrencyText(String(n));
                  }}
                  placeholder="1"
                  autoComplete="off"
                />
              </label>
              <p className="scrape-pane-card__hint">
                各 1–4（默认快 2 / 慢 1，目标整容器持续 &lt;1G）。过高易顶满；慢源过盾仍单飞排队。
              </p>
            </div>

            <div className="scrape-pane-card">
              <div className="scrape-pane-card__band">缩略图下载策略</div>
              <p className="scrape-pane-card__hint scrape-pane-card__hint--top">
                缩略图通常有多个来源候选，选择程序决策的方式
              </p>
              <div
                className="scrape-strategy-list"
                role="radiogroup"
                aria-label="缩略图下载策略"
              >
                {COVER_STRATEGY_OPTIONS.map((opt) => {
                  const active = coverDownloadStrategy === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      className={
                        active
                          ? "scrape-strategy-item scrape-strategy-item--active"
                          : "scrape-strategy-item"
                      }
                      disabled={busy || exporting}
                      onClick={() => setCoverDownloadStrategy(opt.value)}
                    >
                      <span
                        className={
                          active
                            ? "scrape-strategy-item__dot scrape-strategy-item__dot--on"
                            : "scrape-strategy-item__dot"
                        }
                        aria-hidden
                      />
                      <span className="scrape-strategy-item__text">
                        <span className="scrape-strategy-item__title">
                          {opt.title}
                        </span>
                        <span className="scrape-strategy-item__sub">
                          {opt.sub}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="scrape-pane-card">
              <div className="scrape-pane-card__band">元数据优化</div>
              <p className="scrape-pane-card__hint scrape-pane-card__hint--top">
                刮削后对元数据进行优化处理；中文标题源顺序请在「数据源 → 路径优先级」按区配置
              </p>
              <label className="settings-toggle-row scrape-pane-toggle">
                <span className="scrape-pane-toggle__text">
                  <span className="scrape-pane-toggle__title">
                    启用演员数据映射
                  </span>
                  <span className="scrape-pane-toggle__sub">
                    使用内置数据表规范化演员名、补充演员 javdb 页面链接
                  </span>
                </span>
                <input
                  type="checkbox"
                  className="scrape-src-card__switch"
                  checked={metadataOptimize.enableActorMapping}
                  disabled={busy || exporting}
                  onChange={(e) =>
                    setMetadataOptimize((prev) => ({
                      ...prev,
                      enableActorMapping: e.target.checked,
                    }))
                  }
                />
              </label>
              <label className="settings-toggle-row scrape-pane-toggle">
                <span className="scrape-pane-toggle__text">
                  <span className="scrape-pane-toggle__title">
                    启用标签数据映射
                  </span>
                  <span className="scrape-pane-toggle__sub">
                    使用内置数据表规范化标签描述
                  </span>
                </span>
                <input
                  type="checkbox"
                  className="scrape-src-card__switch"
                  checked={metadataOptimize.enableTagMapping}
                  disabled={busy || exporting}
                  onChange={(e) =>
                    setMetadataOptimize((prev) => ({
                      ...prev,
                      enableTagMapping: e.target.checked,
                    }))
                  }
                />
              </label>
              <label className="settings-toggle-row scrape-pane-toggle">
                <span className="scrape-pane-toggle__text">
                  <span className="scrape-pane-toggle__title">
                    精简多余的换行符 (简介)
                  </span>
                  <span className="scrape-pane-toggle__sub">
                    开启后简介中多个连续的换行符会被精简为单个
                  </span>
                </span>
                <input
                  type="checkbox"
                  className="scrape-src-card__switch"
                  checked={metadataOptimize.compactOutlineNewlines}
                  disabled={busy || exporting}
                  onChange={(e) =>
                    setMetadataOptimize((prev) => ({
                      ...prev,
                      compactOutlineNewlines: e.target.checked,
                    }))
                  }
                />
              </label>
              <label className="scrape-pane-field scrape-pane-field--wide">
                <span className="scrape-pane-field__label">映射语言</span>
                <select
                  className="scrape-pane-field__input"
                  value={metadataOptimize.mappingLanguage}
                  disabled={busy || exporting}
                  onChange={(e) => {
                    const v = e.target.value;
                    const lang: MetadataOptimizeLang =
                      v === "zh-TW" || v === "ja" || v === "en" ? v : "zh-CN";
                    setMetadataOptimize((prev) => ({
                      ...prev,
                      mappingLanguage: lang,
                    }));
                  }}
                >
                  <option value="zh-CN">简体中文</option>
                  <option value="zh-TW">繁体中文</option>
                  <option value="ja">日文</option>
                  <option value="en">英文</option>
                </select>
              </label>
              <p className="scrape-pane-card__hint">
                选择演员名、标签等静态数据映射时使用的语言；映射表放在
                data/scrape_maps/
              </p>
            </div>

            <div className="scrape-pane-actions">
              <button
                type="button"
                className="btn settings-actions__primary scrape-pane-actions__primary"
                disabled={busy || exporting}
                onClick={() => void onSave()}
              >
                {busy ? "处理中…" : "保存"}
              </button>
            </div>
          </div>
        ) : null}

        {tab === "task" ? (
          <div className="scrape-pane">
            <div className="scrape-task-head">
              <div className="scrape-task-head__titles">
                <h2 className="scrape-task-head__title">刮削任务</h2>
                {scrapeTasks.length ? (
                  <p className="scrape-task-head__meta">
                    {scrapeTasks.length} 个
                  </p>
                ) : null}
              </div>
              <div className="scrape-task-head__ops" role="group" aria-label="任务操作">
                {scrapeTasks.length ? (
                  <button
                    type="button"
                    className="scrape-task-head__btn scrape-task-head__btn--ghost"
                    disabled={busy || controlBusy}
                    onClick={() => void onStartAllTasks()}
                  >
                    <Play size={12} strokeWidth={2.5} aria-hidden />
                    全部开始
                  </button>
                ) : null}
                <button
                  type="button"
                  className="scrape-task-head__btn scrape-task-head__btn--primary"
                  disabled={busy}
                  onClick={() => {
                    setEditingTask(null);
                    setTaskModalOpen(true);
                  }}
                >
                  <Plus size={13} strokeWidth={2.5} aria-hidden />
                  新建
                </button>
              </div>
            </div>

            {scrapeTasks.length ? (
              <div className="scrape-task-list">
                {[...scrapeTasks]
                  .sort((a, b) => {
                    const aw = taskIsWorking(progress, a) ? 0 : 1;
                    const bw = taskIsWorking(progress, b) ? 0 : 1;
                    return aw - bw;
                  })
                  .map((task) => {
                  const title =
                    task.name ||
                    task.prefix ||
                    task.maker ||
                    task.code ||
                    "刮削任务";
                  const path = [
                    regionLabels(task.regions || []),
                    task.maker,
                    task.prefix,
                    task.code,
                  ]
                    .filter(Boolean)
                    .join("/");
                  const modeLabel =
                    task.mode === "force" ? "强制重刮" : "增量";
                  const live = progressBelongsToTask(progress, task);
                  const queued = taskIsQueued(progress, task);
                  // 仅真正在跑/暂停/取消中用实时进度；已结束后改用本卡存档，避免串全局快照
                  const liveActive = Boolean(
                    live &&
                      !queued &&
                      (Boolean(progress?.running) ||
                        Boolean(progress?.paused) ||
                        progress?.message === "cancelling" ||
                        progress?.message === "paused" ||
                        // 重启后断点：仍展示本卡进度计数
                        ((progress?.resumable || progress?.pauseSaved) &&
                          !progress?.running)),
                  );
                  // 卡片文案跟任务存档走，编辑后立即反映（不等进度轮询）
                  const liveModeLabel =
                    task.mode === "force" ? "强制重刮" : "增量";
                  const running = Boolean(
                    liveActive &&
                      progress?.running &&
                      (progress?.message !== "cancelling" ||
                        Boolean(progress?.running)),
                  );
                  const paused = Boolean(
                    liveActive &&
                      progress?.running &&
                      (progress?.paused || progress?.message === "paused"),
                  );
                  const cancelling =
                    liveActive && progress?.message === "cancelling";
                  // 成功/空号/失败/合计：以任务卡数字为准
                  // 仅真正在跑/暂停时才合并实时进度，避免重置后被旧 progress 抬回
                  const archivedStats = taskStats(task);
                  const progressStats =
                    liveActive && progress
                      ? reconcileStats({
                          done: Number(progress.done ?? 0),
                          empty: Number(progress.empty ?? 0),
                          failed: Number(progress.failed ?? 0),
                          total: Number(progress.total ?? 0),
                        })
                      : null;
                  const stats = reconcileStats({
                    done: Math.max(
                      archivedStats.done,
                      progressStats?.done ?? 0,
                    ),
                    empty: Math.max(
                      archivedStats.empty,
                      progressStats?.empty ?? 0,
                    ),
                    failed: Math.max(
                      archivedStats.failed,
                      progressStats?.failed ?? 0,
                    ),
                    total: Math.max(
                      archivedStats.total,
                      progressStats?.total ?? 0,
                      archivedStats.done +
                        archivedStats.empty +
                        archivedStats.failed,
                      (progressStats?.done ?? 0) +
                        (progressStats?.empty ?? 0) +
                        (progressStats?.failed ?? 0),
                    ),
                  });
                  const sessionStats = liveActive
                    ? reconcileStats({
                        done: Number(progress?.done ?? 0),
                        empty: Number(progress?.empty ?? 0),
                        failed: Number(progress?.failed ?? 0),
                        total: Number(progress?.total ?? 0),
                      })
                    : stats;
                  const processed =
                    stats.done + stats.empty + stats.failed;
                  const sessionProcessed =
                    sessionStats.done +
                    sessionStats.empty +
                    sessionStats.failed;
                  // 真正进入并发线程的数量；排队未开始的不算
                  const inProgress = liveActive
                    ? Math.max(0, Number(progress?.active ?? 0))
                    : 0;
                  const pct = liveActive
                    ? sessionStats.total
                      ? Math.min(
                          100,
                          Math.round(
                            (sessionProcessed / sessionStats.total) * 100,
                          ),
                        )
                      : 0
                    : stats.total
                      ? Math.min(
                          100,
                          Math.round((processed / stats.total) * 100),
                        )
                      : 0;
                  const { badge, tone: badgeTone } = resolveTaskBadge(
                    task,
                    progress,
                    exporting,
                  );
                  const fieldHint = taskFieldHint(task.fields);
                  const sub = liveActive
                    ? [
                        path,
                        liveModeLabel,
                        fieldHint,
                        progress?.current
                          ? `当前 ${progress.current}`
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : [path, modeLabel, fieldHint].filter(Boolean).join(" · ");
                  const canContinue = Boolean(
                    liveActive &&
                      !running &&
                      !queued &&
                      (progress?.resumable ||
                        progress?.pauseSaved ||
                        progress?.message === "interrupted" ||
                        progress?.message === "paused"),
                  );
                  return (
                    <article
                      key={task.id}
                      className="scrape-pane-card scrape-prog-card scrape-task-card"
                    >
                      <div className="scrape-prog-status">
                        <span
                          className="scrape-prog-status__icon"
                          aria-hidden
                        >
                          <ScanSearch size={16} strokeWidth={2} />
                        </span>
                        <div className="scrape-task-card__main">
                          <span className="scrape-task-card__title-row">
                            <span className="scrape-prog-status__title">
                              {title}
                            </span>
                            <button
                              type="button"
                              className={`scrape-task-card__watch-badge${
                                task.watchEnabled ? " is-on" : ""
                              }`}
                              disabled={controlBusy || busy}
                              title={
                                task.watchEnabled
                                  ? task.watchArmed
                                    ? "监控已就绪：本轮跑完后会定期增量"
                                    : "监控已开：请先点开始并跑完一轮"
                                  : "点击开启监控"
                              }
                              aria-pressed={Boolean(task.watchEnabled)}
                              onClick={() => void onToggleWatch(task)}
                            >
                              {task.watchEnabled
                                ? task.watchArmed
                                  ? "监控中"
                                  : "监控"
                                : "监控"}
                            </button>
                            <span
                              className={`scrape-log-badge scrape-log-badge--${badgeTone}`}
                            >
                              {badge}
                            </span>
                          </span>
                        </div>
                      </div>
                      <div className="scrape-prog-actions scrape-task-card__actions">
                        <div className="scrape-task-card__actions-main">
                          {running && !cancelling ? (
                            <button
                              type="button"
                              className="scrape-prog-action scrape-prog-action--text"
                              disabled={controlBusy}
                              aria-label={paused ? "继续" : "暂停"}
                              title={paused ? "继续" : "暂停"}
                              onClick={() =>
                                void (paused
                                  ? onResumeExport()
                                  : onPauseExport())
                              }
                            >
                              {paused ? "继续" : "暂停"}
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="scrape-prog-action scrape-prog-action--text"
                              disabled={busy || queued || controlBusy}
                              aria-label={canContinue ? "继续刮削" : "重新刮削"}
                              title={
                                queued
                                  ? "已在队列中"
                                  : canContinue
                                    ? "从断点继续刮削"
                                    : exporting
                                      ? "加入队列依次刮削"
                                      : "重新刮削"
                              }
                              onClick={() => void onRerunTask(task)}
                            >
                              {canContinue ? "继续" : "开始"}
                            </button>
                          )}
                          <button
                            type="button"
                            className="scrape-prog-action scrape-prog-action--text"
                            disabled={
                              busy ||
                              (running && !paused) ||
                              controlBusy
                            }
                            aria-label="重置任务"
                            title={
                              paused
                                ? "停止当前刮削并重置任务"
                                : "重置任务"
                            }
                            onClick={() => void onResetTask(task)}
                          >
                            重置任务
                          </button>
                          <button
                            type="button"
                            className="scrape-prog-action scrape-prog-action--text"
                            disabled={
                              busy ||
                              (running && !paused) ||
                              queued ||
                              controlBusy ||
                              (stats.failed <= 0 &&
                                !(stats.total > 0 && processed < stats.total))
                            }
                            aria-label="失败重试"
                            title={
                              paused
                                ? "停止当前刮削并失败重试"
                                : "失败重试"
                            }
                            onClick={() => void onRetryFailed(task)}
                          >
                            失败重试
                          </button>
                        </div>
                        <div className="scrape-task-card__actions-side">
                          <button
                            type="button"
                            className="scrape-prog-action scrape-prog-action--text"
                            disabled={
                              busy ||
                              // 仅真正刮削中不可编辑；停止 / 未开始 / 暂停可点
                              (running && !paused) ||
                              Boolean(cancelling)
                            }
                            aria-label="编辑任务"
                            title={
                              running && !paused
                                ? "刮削进行中，请先暂停或停止后再编辑"
                                : "编辑"
                            }
                            onClick={() => {
                              setEditingTask(task);
                              setTaskModalOpen(true);
                            }}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="scrape-prog-action scrape-prog-action--text scrape-prog-action--danger"
                            disabled={controlBusy || Boolean(cancelling)}
                            aria-label={
                              running
                                ? "取消本任务刮削"
                                : queued
                                  ? "移出队列"
                                  : "删除任务"
                            }
                            title={
                              running
                                ? "仅取消本任务，其它排队任务保留"
                                : queued
                                  ? "仅移出队列，保留任务卡"
                                  : "删除本任务"
                            }
                            onClick={() => {
                              if (running) {
                                setConfirmClear({
                                  taskId: task.id,
                                  title,
                                  mode: "cancel",
                                });
                                return;
                              }
                              if (queued) {
                                void onDequeueTask(task);
                                return;
                              }
                              void onDeleteTask(task.id);
                            }}
                          >
                            {running || queued ? "取消" : "删除"}
                          </button>
                        </div>
                      </div>

                      <div className="scrape-prog-stats">
                        {(
                          [
                            ["成功", stats.done, "ok", "done"],
                            ["进行中", inProgress, "run", "active"],
                            ["空号", stats.empty, "mute", "empty"],
                            ["数据不全", stats.failed, "err", "failed"],
                            ["合计", stats.total, "total", "total"],
                          ] as const
                        ).map(([label, n, tone, kind]) => {
                          const codesFor = (): string[] => {
                            if (kind === "done")
                              return [...(task.doneCodes || [])];
                            if (kind === "empty")
                              return [
                                ...(task.emptyCodes || []),
                                ...(task.skippedCodes || []),
                              ];
                            if (kind === "failed")
                              return [...(task.failedCodes || [])];
                            if (kind === "active")
                              return [...(progress?.activeCodes || [])];
                            const all = [
                              ...(task.doneCodes || []),
                              ...(task.emptyCodes || []),
                              ...(task.skippedCodes || []),
                              ...(task.failedCodes || []),
                              ...(liveActive
                                ? progress?.activeCodes || []
                                : []),
                            ];
                            return [...new Set(all)];
                          };
                          const clickable = kind !== "total" || n > 0;
                          return (
                            <button
                              key={label}
                              type="button"
                              className={`scrape-prog-stat scrape-prog-stat--${tone}${
                                clickable ? " is-clickable" : ""
                              }`}
                              disabled={!clickable}
                              aria-label={`查看${label}番号`}
                              title={`查看${label}明细`}
                              onClick={() => {
                                void (async () => {
                                  let codes = codesFor();
                                  if (
                                    kind !== "active" &&
                                    (Boolean(progress?.codesTruncated) ||
                                      n > (codes?.length || 0))
                                  ) {
                                    try {
                                      if (kind === "total") {
                                        const [d, e, s, f] = await Promise.all([
                                          fetchScrapeExportCodes({
                                            taskId: task.id,
                                            bucket: "done",
                                          }),
                                          fetchScrapeExportCodes({
                                            taskId: task.id,
                                            bucket: "empty",
                                          }),
                                          fetchScrapeExportCodes({
                                            taskId: task.id,
                                            bucket: "skipped",
                                          }),
                                          fetchScrapeExportCodes({
                                            taskId: task.id,
                                            bucket: "failed",
                                          }),
                                        ]);
                                        codes = [
                                          ...new Set([
                                            ...d.codes,
                                            ...e.codes,
                                            ...s.codes,
                                            ...f.codes,
                                          ]),
                                        ];
                                      } else if (
                                        kind === "done" ||
                                        kind === "empty" ||
                                        kind === "failed"
                                      ) {
                                        if (kind === "empty") {
                                          const [e, s] = await Promise.all([
                                            fetchScrapeExportCodes({
                                              taskId: task.id,
                                              bucket: "empty",
                                            }),
                                            fetchScrapeExportCodes({
                                              taskId: task.id,
                                              bucket: "skipped",
                                            }),
                                          ]);
                                          codes = [
                                            ...new Set([...e.codes, ...s.codes]),
                                          ];
                                        } else {
                                          const r = await fetchScrapeExportCodes({
                                            taskId: task.id,
                                            bucket: kind,
                                          });
                                          codes = r.codes;
                                        }
                                      }
                                    } catch {
                                      /* 回退本地预览列表 */
                                    }
                                  }
                                  setStatCodesOpen({
                                    title,
                                    status: label,
                                    tone,
                                    // 后端按完成顺序追加，界面最新在上
                                    codes: [...codes].reverse(),
                                    task,
                                  });
                                })();
                              }}
                            >
                              <span className="scrape-prog-stat__n">{n}</span>
                              <span className="scrape-prog-stat__l mute">
                                {label}
                              </span>
                            </button>
                          );
                        })}
                      </div>

                      {liveActive ? (
                        <div className="scrape-channel-box" aria-label="双通道进度">
                          {(
                            [
                              {
                                key: "fast",
                                label: "快源",
                                codes: progress?.activeFastCodes || [],
                                pending: Number(progress?.pendingFast || 0),
                                slots: Number(
                                  progress?.fastSlots ||
                                    exportFastConcurrency ||
                                    0,
                                ),
                              },
                              {
                                key: "slow",
                                label: "慢源",
                                codes: progress?.activeSlowCodes || [],
                                pending: Number(progress?.pendingSlow || 0),
                                slots: Number(
                                  progress?.slowSlots ||
                                    exportSlowConcurrency ||
                                    0,
                                ),
                              },
                            ] as const
                          ).map((ch) => {
                            const activeN = ch.codes.length;
                            const codesText = ch.codes.length
                              ? ch.codes.join(" · ")
                              : "空闲";
                            const meta = [
                              `${activeN}${ch.slots ? `/${ch.slots}` : ""}`,
                              ch.pending > 0 ? `排队 ${ch.pending}` : "",
                            ]
                              .filter(Boolean)
                              .join(" · ");
                            return (
                              <button
                                key={ch.key}
                                type="button"
                                className={`scrape-channel-box__row scrape-channel-box__row--${ch.key}${
                                  activeN > 0 ? " is-clickable" : ""
                                }`}
                                disabled={activeN <= 0}
                                title={
                                  activeN > 0
                                    ? `查看${ch.label}进行中`
                                    : undefined
                                }
                                onClick={() => {
                                  if (activeN <= 0) return;
                                  setStatCodesOpen({
                                    title,
                                    status: `${ch.label}进行中`,
                                    tone: "run",
                                    codes: [...ch.codes].reverse(),
                                    task,
                                  });
                                }}
                              >
                                <span className="scrape-channel-box__tag">
                                  {ch.label}
                                </span>
                                <span className="scrape-channel-box__meta">
                                  {meta}
                                </span>
                                <span className="scrape-channel-box__codes allow-select">
                                  {codesText}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      ) : null}

                      <div className="scrape-progress-bar" aria-hidden>
                        <div
                          className="scrape-progress-bar__fill"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <p className="scrape-progress-meta mute">
                        {[
                          liveActive
                            ? [
                                sessionProcessed,
                                sessionStats.total
                                  ? ` / ${sessionStats.total}`
                                  : "",
                                pct ? ` · ${pct}%` : "",
                              ].join("")
                            : [
                                processed,
                                stats.total ? ` / ${stats.total}` : "",
                                pct ? ` · ${pct}%` : "",
                              ].join(""),
                          sub,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="scrape-pane-card scrape-task-empty">
                <p className="scrape-task-empty__title">还没有刮削任务</p>
                <p className="mute scrape-task-empty__sub">
                  点右上角「新建」添加；可保留多张卡，启动后按队列依次刮削。
                </p>
              </div>
            )}
          </div>
        ) : null}

        {tab === "progress" ? (
          <div className="scrape-pane scrape-pane--log">
            <div className="scrape-src-head">
              <div className="scrape-src-head__left">
                <p className="scrape-src-head__title">刮削进度</p>
              </div>
              <div className="scrape-src-head__ops">
                {focusDetail?.code ||
                (stickCode &&
                  progress?.current &&
                  stickCode.toUpperCase() !==
                    String(progress.current).toUpperCase()) ||
                (stickCode &&
                  progress?.currentDetail?.code &&
                  stickCode.toUpperCase() !==
                    String(progress.currentDetail.code).toUpperCase()) ? (
                  <button
                    type="button"
                    className="btn btn-ghost scrape-src-head__test"
                    title="回到当前正在刮削的番号"
                    onClick={() => {
                      setFocusDetail(null);
                      setStickCode(null);
                    }}
                  >
                    回到当前
                  </button>
                ) : null}
                {focusDetail?.code ? null : (
                <button
                  type="button"
                  className="btn btn-ghost scrape-src-head__test"
                  title="刷新并跳到最新处理的番号"
                  onClick={() => {
                    void fetchScrapeExportStatus()
                      .then((st) => {
                        setProgress(st);
                        setFocusDetail(null);
                        const live = String(
                          st.currentDetail?.code || st.current || "",
                        ).trim();
                        const latestDone = String(
                          (st.doneCodes || [])[(st.doneCodes || []).length - 1] ||
                            "",
                        ).trim();
                        const latestFailed = String(
                          (st.failedCodes || [])[
                            (st.failedCodes || []).length - 1
                          ] || "",
                        ).trim();
                        // 刮削中跟当前片；空闲则跟最近完成/失败
                        setStickCode(live || latestDone || latestFailed || null);
                        setProgressRefreshNonce((n) => n + 1);
                      })
                      .catch((e: unknown) =>
                        toast(
                          e instanceof Error ? e.message : "刷新失败",
                          "error",
                        ),
                      );
                  }}
                >
                  <RefreshCw size={13} strokeWidth={2} />
                  刷新
                </button>
                )}
              </div>
            </div>

            <ScrapeProgressLog
              progress={progress}
              exporting={exporting}
              focusCode={focusDetail?.code}
              focusNonce={focusDetail?.nonce}
              refreshNonce={progressRefreshNonce}
              stickCode={stickCode}
              onStickCode={setStickCode}
            />
          </div>
        ) : null}

        {tab === "sources" ? (
          <ScrapeSourcesTab
            cfg={cfg}
            origin={toOriginUrl(DEFAULT_ORIGIN_HOST)}
            libraryRoot={libraryRoot}
            flareSolverrUrl={flareSolverrUrl}
            proxyUrl={proxyUrl}
            kindProfiles={kindProfiles}
            sources={sources}
            retryDefault={retryDefault}
            onApplied={(next) => {
              applyCfg(next);
              const online =
                typeof next.online === "boolean" ? next.online : linkOnline;
              if (typeof next.online === "boolean") setLinkOnline(next.online);
              publishLinkStatus(online, running, next.configured);
            }}
            toast={(msg, tone) => toast(msg, tone || "info")}
          />
        ) : null}
    </>
  );

  const overlays = (
    <>
      <AppCenterModal
        open={Boolean(statCodesOpen)}
        title={statCodesOpen?.title || "番号明细"}
        cardClassName={[
          "scrape-stat-codes-modal-card",
          statCodesOpen
            ? `scrape-stat-codes-modal-card--${statCodesOpen.tone}`
            : "",
        ]
          .filter(Boolean)
          .join(" ")}
        onClose={() => {
          if (statRescrapeBusy) return;
          setStatCodesOpen(null);
        }}
        footer={
          <div className="scrape-stat-codes-modal__foot">
            {statCodesOpen &&
            statCodesOpen.codes.length > 0 &&
            (statCodesOpen.tone === "ok" ||
              statCodesOpen.tone === "mute" ||
              statCodesOpen.tone === "err") ? (
              <button
                type="button"
                className="btn scrape-stat-codes-modal__rescrape-all"
                disabled={statRescrapeBusy}
                onClick={() =>
                  void onRescrapeCodes(statCodesOpen.codes)
                }
              >
                {statRescrapeBusy
                  ? "提交中…"
                  : `全部强制重刮 (${statCodesOpen.codes.length})`}
              </button>
            ) : null}
            <button
              type="button"
              className="btn scrape-stat-codes-modal__done"
              disabled={statRescrapeBusy}
              onClick={() => setStatCodesOpen(null)}
            >
              完成
            </button>
          </div>
        }
      >
        {statCodesOpen ? (
          <div className="scrape-stat-codes">
            <div className="scrape-stat-codes__toolbar">
              <span
                className={`scrape-stat-codes__badge scrape-stat-codes__badge--${statCodesOpen.tone}`}
              >
                {statCodesOpen.status}
              </span>
              <span className="scrape-stat-codes__meta mute">
                {statCodesOpen.codes.length
                  ? `${statCodesOpen.codes.length} 个番号`
                  : "暂无番号"}
              </span>
            </div>
            {statCodesOpen.codes.length > 0 ? (
              <ul className="scrape-stat-codes__list">
                {statCodesOpen.codes.map((code) => (
                  <li key={code} className="scrape-stat-codes__row">
                    <button
                      type="button"
                      className="scrape-stat-codes__item"
                      title={`查看 ${code} 详细数据`}
                      disabled={statRescrapeBusy}
                      onClick={() => {
                        setStatCodesOpen(null);
                        setFocusDetail({ code, nonce: Date.now() });
                        setStickCode(code);
                        setTab("progress");
                      }}
                    >
                      <span className="scrape-stat-codes__code">{code}</span>
                      <span className="scrape-stat-codes__chev" aria-hidden>
                        ›
                      </span>
                    </button>
                    {statCodesOpen.tone === "ok" ||
                    statCodesOpen.tone === "mute" ||
                    statCodesOpen.tone === "err" ? (
                      <button
                        type="button"
                        className="scrape-stat-codes__rescrape"
                        title={`强制重刮 ${code}`}
                        disabled={statRescrapeBusy}
                        onClick={() => void onRescrapeCodes([code])}
                      >
                        重刮
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="scrape-stat-codes__empty mute">还没有记录</p>
            )}
          </div>
        ) : null}
      </AppCenterModal>

      <AppCenterModal
        open={Boolean(confirmClear)}
        title={
          confirmClear
            ? `取消「${confirmClear.title}」？`
            : "取消任务？"
        }
        onClose={() => setConfirmClear(null)}
        footer={
          <div className="scrape-confirm-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setConfirmClear(null)}
            >
              返回
            </button>
            <button
              type="button"
              className="btn scrape-confirm-actions__danger"
              onClick={() => {
                void onConfirmStopTask();
              }}
            >
              取消任务
            </button>
          </div>
        }
      >
        <p className="mute" style={{ margin: 0, fontSize: 13, lineHeight: 1.45 }}>
          只停止这一张任务卡；其它正在排队的任务会继续。
        </p>
      </AppCenterModal>
    </>
  );

  return (
    <>
      <AppPush title="刮削端" onBack={onBack}>
        <div className="scrape-panel">
          {body}
          {overlays}
        </div>
      </AppPush>
      <ScrapeTaskModal
        key={editingTask?.id || (taskModalOpen ? "new" : "closed")}
        open={taskModalOpen}
        task={
          editingTask
            ? scrapeTasks.find((t) => t.id === editingTask.id) || editingTask
            : null
        }
        regions={regionList}
        busy={busy}
        onClose={() => {
          if (busy) return;
          setTaskModalOpen(false);
          setEditingTask(null);
        }}
        onSave={(draft) => void onSaveTask(draft)}
      />
    </>
  );
}
