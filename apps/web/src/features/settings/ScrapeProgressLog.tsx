"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, ScanSearch, Trash2 } from 'lucide-react';
import {
  scrapeExportImageUrl,
  fetchScrapeExportDetail,
  type ScrapeExportDetail,
  type ScrapeExportEvent,
  type ScrapeExportStatus,
} from '@/lib/api';
import { CroppedCoverImg } from '@/components/cover/CroppedCoverImg';
import {
  cropModeForRegion,
  ensurePosterCropLoaded,
  frameAspectForCropMode,
  getPosterCropCached,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';

const PHASE_LABEL: Record<string, string> = {
  job: "任务",
  parse: "解析番号",
  scrape: "刮削数据",
  cover: "下载图片",
  nfo: "写入元数据",
  write: "写入目录",
};

type FieldRow = {
  key: string;
  label: string;
  value: string;
  source?: string;
  multiline?: boolean;
  image?: boolean;
};

function phaseOf(ev: ScrapeExportEvent): string {
  return ev.phase || "job";
}

function groupEvents(events: ScrapeExportEvent[]) {
  const groups: Array<{
    key: string;
    phase: string;
    code: string;
    items: ScrapeExportEvent[];
    level: string;
  }> = [];
  for (const ev of events) {
    const phase = phaseOf(ev);
    const code = ev.code || "";
    const key = `${code}::${phase}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.items.push(ev);
      if (ev.level === "error") last.level = "error";
      else if (ev.level === "warn" && last.level !== "error") last.level = "warn";
      else if (ev.level === "ok" && last.level === "info") last.level = "ok";
    } else {
      groups.push({
        key,
        phase,
        code,
        items: [ev],
        level: ev.level || "info",
      });
    }
  }
  return groups;
}

function srcOf(detail: ScrapeExportDetail, key: string): string | undefined {
  const ft = timingOf(detail, key);
  if (ft?.id) return ft.id;
  const fs = detail.fieldSources || {};
  if (key === "plot" || key === "outline")
    return fs.plot || fs.outline || undefined;
  if (key === "poster" || key === "cover")
    return fs.cover || fs.poster || undefined;
  if (key === "tags" || key === "genres")
    return fs.tags || fs.genres || undefined;
  return fs[key] || undefined;
}

/** 字段最终来源 + 实测耗时（优先于 sourceRuns 反推） */
function timingOf(
  detail: ScrapeExportDetail,
  key: string,
):
  | { id: string; ms: number; ok: boolean; mode?: string }
  | undefined {
  const ft = detail.fieldTimings || {};
  if (key === "plot" || key === "outline")
    return ft.outline || ft.plot || undefined;
  if (key === "poster" || key === "cover")
    return ft.cover || ft.poster || undefined;
  if (key === "tags" || key === "genres")
    return ft.tags || ft.genres || undefined;
  return ft[key] || undefined;
}

function badgeRunFromTiming(
  t: { id: string; ms: number; ok: boolean; mode?: string } | undefined,
): { id: string; ok: boolean; ms: number; mode?: string } | null {
  if (!t?.id) return null;
  return { id: t.id, ok: t.ok !== false, ms: t.ms || 0, mode: t.mode };
}

function posterSrcOf(detail: ScrapeExportDetail): string {
  if (detail.posterLocal) {
    return scrapeExportImageUrl({ rel: detail.posterLocal });
  }
  const remote = String(detail.poster || '').trim();
  if (!remote) return '';
  return scrapeExportImageUrl({
    code: detail.code || undefined,
    url: remote,
  });
}

function isChineseTitle(s: string | null | undefined): boolean {
  const t = String(s || "").trim();
  if (!t) return false;
  const han = (t.match(/[\u4e00-\u9fff]/g) || []).length;
  const kana = (t.match(/[\u3040-\u30ff]/g) || []).length;
  return han >= 2 && han >= kana;
}

function isLocalTitleZhSource(src: string | null | undefined): boolean {
  const s = String(src || "").trim().toLowerCase();
  return (
    !s ||
    s === "index" ||
    s === "forum" ||
    s === "maker-fs" ||
    s === "seed" ||
    s === "local"
  );
}

function detailRows(
  detail: ScrapeExportDetail | null | undefined,
  pending: boolean,
): FieldRow[] {
  if (!detail?.code) return [];
  // 详情页始终展示完整元数据字段；无数据则空着。
  // 任务「字段配置」只控制参不参与刮削/落盘，不在这里藏行。
  const actors = (detail.actors || []).filter(Boolean).join("、");
  const wait = "抓取中…";
  const codeU = String(detail.code || "")
    .trim()
    .toUpperCase();
  const titleZhRaw = String(detail.titleZh || "").trim();
  const titleZhSrc = srcOf(detail, "titleZh");
  const titleZhOk =
    Boolean(titleZhRaw) &&
    (!isLocalTitleZhSource(titleZhSrc) || isChineseTitle(titleZhRaw));
  // 无合格中文标题时回退网络日文原题（javbus originalTitle / title）
  const jaRaw =
    [detail.originalTitle, detail.title]
      .map((x) => String(x || "").trim())
      .find((t) => t && t.toUpperCase() !== codeU) || "";
  const jaSrc =
    srcOf(detail, "originalTitle") || srcOf(detail, "title") || undefined;
  const titleText = titleZhOk ? titleZhRaw : jaRaw;
  const titleSrc = titleZhOk ? titleZhSrc : jaSrc;
  const titleLabel = titleZhOk ? "中文标题" : jaRaw ? "标题" : "中文标题";
  const outlineVal = detail.plot || "";
  const studioVal = detail.studio || "";
  const actorVal = actors;
  const tagsVal = (detail.genres || []).filter(Boolean).join("、");
  const seriesVal = String(detail.series || "").trim();
  const cell = (v: string, src?: string) => ({
    // 空值也占行（用 —），避免「字段被裁掉」的错觉
    value: v || (pending ? wait : "—"),
    source: v ? src : undefined,
  });

  const title = cell(titleText, titleSrc);
  const outline = cell(
    outlineVal,
    srcOf(detail, "outline") || srcOf(detail, "plot"),
  );
  const studio = cell(studioVal, srcOf(detail, "studio"));
  const actor = cell(actorVal, srcOf(detail, "actors"));
  const tags = cell(tagsVal, srcOf(detail, "tags"));
  const series = cell(seriesVal, srcOf(detail, "series"));

  // 短字段靠前：标签/系列紧跟女优，避免长简介把首屏占满后误以为「没有标签」
  return [
    {
      key: "titleZh",
      label: titleLabel,
      value: title.value,
      source: title.source,
      multiline: true,
    },
    {
      key: "actors",
      label: "女优",
      value: actor.value,
      source: actor.source,
    },
    {
      key: "tags",
      label: "标签",
      value: tags.value,
      source: tags.source,
      multiline: true,
    },
    {
      key: "series",
      label: "系列",
      value: series.value,
      source: series.source,
    },
    {
      key: "studio",
      label: "制片方",
      value: studio.value,
      source: studio.source,
    },
    {
      key: "outline",
      label: "简介",
      value: outline.value,
      source: outline.source,
      multiline: true,
    },
    {
      key: "path",
      label: "目录",
      value: detail.path || "—",
      multiline: true,
    },
  ];
}

function runForSource(
  runs: ScrapeExportDetail["sourceRuns"],
  source?: string,
) {
  if (!source?.trim() || !runs?.length) return null;
  const matched = runs.filter((r) => r.id === source);
  if (!matched.length) return null;
  const wave = matched.find(
    (r) => String((r as { detail?: string }).detail || "") !== "cid-retry",
  );
  return wave || matched[0];
}

function runForCover(
  runs: ScrapeExportDetail["sourceRuns"],
  coverSrc?: string,
) {
  const bySrc = runForSource(runs, coverSrc);
  if (bySrc) return bySrc;
  if (!runs?.length) return null;
  const coverMode = runs.find(
    (r) => String(r.mode || "").toLowerCase() === "cover" && r.ok,
  );
  if (coverMode) return coverMode;
  return null;
}

function isIndexSourceId(id: string | undefined | null): boolean {
  const s = String(id || "").trim().toLowerCase();
  return s === "index" || s === "local" || s === "maker-fs" || s === "seed";
}

function sourceMetaLabel(id: string | undefined | null, ok: boolean, ms?: number, error?: string): string {
  if (!ok) return error || "失败";
  const s = String(id || "").trim().toLowerCase();
  if (s === "forum") return "种子";
  if (isIndexSourceId(s)) return "索引物化";
  return `${((ms || 0) / 1000).toFixed(2)}s`;
}

function SourceRunBadge({
  run,
}: {
  run: NonNullable<ReturnType<typeof runForSource>>;
}) {
  const displayId = isIndexSourceId(run.id) ? "index" : run.id;
  const meta = sourceMetaLabel(run.id, Boolean(run.ok), run.ms, run.error);
  return (
    <span
      className={`scrape-detail-run scrape-detail-run--${
        run.ok ? "ok" : "fail"
      } scrape-detail-row__run`}
    >
      <span className="scrape-detail-run__id">{displayId}</span>
      <span className="scrape-detail-run__meta mute">{meta}</span>
    </span>
  );
}

function DetailImage({
  src,
  alt,
  region,
}: {
  src: string;
  alt: string;
  region?: string | null;
}) {
  const [cropTick, setCropTick] = useState(0);
  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setCropTick((n) => n + 1));
  }, []);
  const aspect = (() => {
    void cropTick;
    const mode = region ? cropModeForRegion(region) : undefined;
    return frameAspectForCropMode(mode, getPosterCropCached().ratio);
  })();

  return (
    <div className="scrape-detail-cover__media" style={{ aspectRatio: aspect }}>
      <CroppedCoverImg
        src={src}
        region={region}
        alt={alt}
        className="scrape-detail-img"
        emptyClassName="mute scrape-detail-img__fallback"
        emptyLabel="暂无图片"
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

function phaseBadge(detail: ScrapeExportDetail | null | undefined, running: boolean) {
  const phase = detail?.phase || "";
  const phaseLabel =
    phase === "scrape"
      ? "刮削中"
      : phase === "empty"
        ? "空号"
        : phase === "skipped"
          ? "空号"
          : phase === "failed"
            ? "失败"
            : phase === "done" || phase === "write"
              ? "已写入"
              : running
                ? "进行中"
                : "完成";
  const phaseTone =
    phase === "empty" || phase === "skipped"
      ? "idle"
      : phase === "failed"
        ? "err"
        : running || phase === "scrape"
          ? "run"
          : "ok";
  return { phaseLabel, phaseTone };
}

function ScrapeDetailPane({
  detail,
  running,
}: {
  detail: ScrapeExportDetail | null | undefined;
  running: boolean;
}) {
  const phase = detail?.phase || "";
  const hasMeta =
    Boolean(String(detail?.titleZh || detail?.title || "").trim()) ||
    Boolean(detail?.actors && detail.actors.length) ||
    Boolean(String(detail?.plot || "").trim()) ||
    Boolean(String(detail?.studio || "").trim()) ||
    Boolean(detail?.genres && detail.genres.length) ||
    Boolean(String(detail?.series || "").trim());
  const pending =
    running &&
    (phase === "scrape" || phase === "parse" || phase === "") &&
    !hasMeta;
  const rows = useMemo(
    () => detailRows(detail, pending),
    [detail, pending],
  );
  const runs = detail?.sourceRuns || [];
  const poster = detail ? posterSrcOf(detail) : "";
  // 封面：优先 fieldTimings.cover（实际贡献源+耗时），勿用裁剪图源冒充
  const coverTiming = detail ? timingOf(detail, "cover") : undefined;
  const coverSrc = detail
    ? coverTiming?.id || srcOf(detail, "cover")
    : undefined;
  const coverRun =
    badgeRunFromTiming(coverTiming) || runForCover(runs, coverSrc);
  const { phaseLabel, phaseTone } = phaseBadge(detail, running);

  if (!detail?.code) {
    return (
      <div className="scrape-detail-empty mute">
        {running
          ? "正在解析，详细数据稍后出现…"
          : "开始任务后，这里显示刮削字段与封面"}
      </div>
    );
  }

  return (
    <div className="scrape-detail">
      <header className="scrape-detail__head scrape-detail__head--compact">
        <div className="scrape-detail__head-row">
          <p className="scrape-detail__code">{detail.code}</p>
          <span
            className={`scrape-detail__status scrape-log-badge scrape-log-badge--${phaseTone}`}
          >
            {phaseLabel}
          </span>
        </div>
      </header>

      <div className="scrape-detail-scroll">
        <div className="scrape-detail-cover">
          <div className="scrape-detail-cover__frame">
            <DetailImage
              src={poster}
              alt={`${detail.code} 封面`}
              region={detail.region}
            />
          </div>
          <div className="scrape-detail-cover__run-col">
            {coverRun ? (
              <SourceRunBadge run={coverRun} />
            ) : coverSrc ? (
              <span
                className="scrape-detail-run scrape-detail-run--ok scrape-detail-row__run"
              >
                <span className="scrape-detail-run__id">{coverSrc}</span>
              </span>
            ) : null}
          </div>
        </div>

        {pending && runs.length === 0 ? (
          <p className="scrape-detail-wait mute">正在抓取各站点真实数据…</p>
        ) : null}

        <dl className="scrape-detail-fields">
          <p className="scrape-detail-sec">元数据</p>
          {rows.map((row) => {
            const timing = detail ? timingOf(detail, row.key) : undefined;
            const run =
              badgeRunFromTiming(timing) ||
              runForSource(runs, timing?.id || row.source);
            const srcLabel = timing?.id || row.source;
            return (
              <div key={row.key} className="scrape-detail-row">
                <dt>
                  <span>{row.label}</span>
                </dt>
                <dd
                  className={
                    row.multiline
                      ? "scrape-detail-row__val scrape-detail-row__val--multi"
                      : "scrape-detail-row__val"
                  }
                  data-empty={
                    !row.value ||
                    row.value === "—" ||
                    row.value === "抓取中…"
                      ? "1"
                      : "0"
                  }
                >
                  {row.value}
                </dd>
                <div className="scrape-detail-row__run-col">
                  {run ? (
                    <SourceRunBadge run={run} />
                  ) : srcLabel ? (
                    <span
                      className="scrape-detail-run scrape-detail-run--ok scrape-detail-row__run"
                    >
                      <span className="scrape-detail-run__id">
                        {isIndexSourceId(srcLabel) ? "index" : srcLabel}
                      </span>
                      <span className="scrape-detail-run__meta mute">
                        {sourceMetaLabel(srcLabel, true)}
                      </span>
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </dl>
      </div>
    </div>
  );
}

function ScrapeLogPane({
  events,
  running,
  code,
}: {
  events: ScrapeExportEvent[];
  running: boolean;
  code?: string;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const groups = useMemo(() => groupEvents(events), [events]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || !running) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length, running, code]);

  return (
    <div className="scrape-log-pane">
      <div className="scrape-log-pane-meta mute">
        {code ? (
          <span className="scrape-log-pane-meta__code">{code}</span>
        ) : null}
        <span>
          {running && !code
            ? "实时覆盖"
            : groups.length
              ? `${groups.length} 步`
              : "暂无"}
        </span>
      </div>
      <div className="scrape-log-timeline" ref={listRef}>
        {groups.length === 0 ? (
          <p className="mute scrape-log-empty">
            {code
              ? "该番号暂无保留的刮削日志（需在本轮任务中刮过；重启后仍保留最近归档）"
              : "等待日志…"}
          </p>
        ) : (
          groups.map((g, gi) => (
            <section
              key={`${gi}-${g.key}-${g.items[0]?.ts || ""}-${g.items.length}`}
              className={`scrape-log-step scrape-log-step--${g.level}${
                g.phase === "scrape" ? " scrape-log-step--scrape" : ""
              }`}
            >
              <div className="scrape-log-step__rail" aria-hidden>
                <span className="scrape-log-step__dot" />
              </div>
              <div className="scrape-log-step__body">
                <header className="scrape-log-step__head">
                  <span className="scrape-log-step__title">
                    {PHASE_LABEL[g.phase] || g.phase}
                  </span>
                  {g.code ? (
                    <span className="scrape-log-step__code mute">{g.code}</span>
                  ) : null}
                </header>
                <ul className="scrape-log-lines">
                  {g.items.map((ev, i) => (
                    <li
                      key={`${ev.ts}-${i}-${ev.text}`}
                      className={`scrape-log-line scrape-log-line--${ev.level || "info"}`}
                    >
                      {ev.source ? (
                        <span className="scrape-log-line__src">{ev.source}</span>
                      ) : null}
                      <span className="scrape-log-line__text">{ev.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ))
        )}
      </div>
    </div>
  );
}

function statusTitle(
  progress: ScrapeExportStatus | null,
  running: boolean,
  taskName?: string,
) {
  const name = (taskName || "").trim();
  const code = progress?.current || "";
  if (progress?.message === "cancelling") {
    return name
      ? `${name} · 取消中`
      : `取消中 · ${code || "…"}`;
  }
  if (progress?.paused && running) {
    return name
      ? `${name} · 已暂停`
      : `已暂停 · ${code || "…"}`;
  }
  if (running) {
    return name
      ? `${name} · ${code || "进行中"}`
      : `进行中 · ${code || "…"}`;
  }
  if (progress?.message === "cancelled") {
    return name ? `${name} · 已取消` : "已取消";
  }
  if (progress?.message === "interrupted") {
    return name ? `${name} · 已中断` : "已中断";
  }
  if (name) return name;
  return "最近一次任务";
}

function statusSub(
  progress: ScrapeExportStatus | null,
  taskMeta?: string,
) {
  const msg = progress?.message || "";
  if (msg === "paused") return "暂停中，当前番号完成后停住";
  if (msg === "cancelling") return "正在停止…";
  if (msg === "cancelled") return taskMeta || "任务已取消";
  if (msg === "interrupted") {
    return taskMeta ? `${taskMeta} · 服务重启后已中断` : "服务重启后已中断";
  }
  if (msg === "scraping" || msg === "building" || msg === "queued") {
    const tip = msg === "building" ? "准备中…" : "刮削中";
    return taskMeta ? `${taskMeta} · ${tip}` : tip;
  }
  if (msg === "ok") return taskMeta || "已完成";
  return taskMeta || msg || "等待开始刮削";
}

export function ScrapeProgressSummary({
  progress,
  exporting,
  taskName,
  taskMeta,
  controlBusy,
  onPause,
  onResume,
  onDelete,
}: {
  progress: ScrapeExportStatus | null;
  exporting?: boolean;
  taskName?: string;
  taskMeta?: string;
  controlBusy?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onDelete?: () => void;
}) {
  const running = Boolean(progress?.running || exporting);
  const paused = Boolean(progress?.paused);
  const cancelling = progress?.message === "cancelling";
  const pct =
    progress && progress.total
      ? Math.min(
          100,
          Math.round(
            (((progress.done || 0) +
              (progress.empty || 0) +
              (progress.skipped || 0) +
              (progress.failed || 0)) /
              progress.total) *
              100,
          ),
        )
      : 0;
  const processed =
    (progress?.done || 0) +
    (progress?.empty || 0) +
    (progress?.skipped || 0) +
    (progress?.failed || 0);

  return (
    <div className="scrape-pane-card scrape-prog-card">
      <div className="scrape-prog-status">
        <span className="scrape-prog-status__icon" aria-hidden>
          <ScanSearch size={16} strokeWidth={2} />
        </span>
        <span className="scrape-prog-status__main">
          <span className="scrape-prog-status__title">
            {statusTitle(progress, running, taskName)}
          </span>
          <span className="scrape-prog-status__sub mute">
            {statusSub(progress, taskMeta)}
          </span>
        </span>
        <div className="scrape-prog-actions">
          {running && !cancelling ? (
            <button
              type="button"
              className="scrape-prog-action"
              disabled={controlBusy}
              aria-label={paused ? "继续" : "暂停"}
              title={paused ? "继续" : "暂停"}
              onClick={() => (paused ? onResume?.() : onPause?.())}
            >
              {paused ? (
                <Play size={14} strokeWidth={2.2} />
              ) : (
                <Pause size={14} strokeWidth={2.2} />
              )}
            </button>
          ) : null}
          <button
            type="button"
            className="scrape-prog-action scrape-prog-action--danger"
            disabled={controlBusy || cancelling}
            aria-label="删除"
            title="删除"
            onClick={() => onDelete?.()}
          >
            <Trash2 size={14} strokeWidth={2.2} />
          </button>
        </div>
      </div>

      <div className="scrape-prog-stats">
        {(
          [
            ["成功", progress?.done ?? 0, "ok"],
            ["空号", progress?.empty ?? 0, "mute"],
            ["数据不全", progress?.failed ?? 0, "err"],
            ["合计", progress?.total ?? 0, "total"],
          ] as const
        ).map(([label, n, tone]) => (
          <div
            key={label}
            className={`scrape-prog-stat scrape-prog-stat--${tone}`}
          >
            <span className="scrape-prog-stat__n">{n}</span>
            <span className="scrape-prog-stat__l mute">{label}</span>
          </div>
        ))}
      </div>

      <div className="scrape-progress-bar" aria-hidden>
        <div
          className="scrape-progress-bar__fill"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="scrape-progress-meta mute">
        {processed}
        {progress?.total ? ` / ${progress.total}` : ""}
        {pct ? ` · ${pct}%` : ""}
        {progress?.region ? ` · ${progress.region}` : ""}
      </p>
    </div>
  );
}

export function ScrapeProgressLog({
  progress,
  exporting,
  focusCode,
  focusNonce,
  refreshNonce,
  stickCode,
  onStickCode,
}: {
  progress: ScrapeExportStatus | null;
  exporting?: boolean;
  /** 从任务卡番号列表点进来时，固定展示该番号详细数据 */
  focusCode?: string | null;
  /** 同番号再次点击时递增，强制重新钉住并拉取 */
  focusNonce?: number | null;
  /** 点「刷新」时递增：重拉当前展示番号的完整详情+日志 */
  refreshNonce?: number | null;
  /** 进度页钉住的番号（不自动跟下一片）；空=跟当前刮削 */
  stickCode?: string | null;
  onStickCode?: (code: string | null) => void;
}) {
  const [tab, setTab] = useState<"detail" | "log">("detail");
  const [pinnedCode, setPinnedCode] = useState("");
  const [pinnedDetail, setPinnedDetail] = useState<ScrapeExportDetail | null>(
    null,
  );
  const [pinnedLoading, setPinnedLoading] = useState(false);
  const [pinnedError, setPinnedError] = useState("");
  const [pinnedEvents, setPinnedEvents] = useState<ScrapeExportEvent[]>([]);
  const liveDetail = progress?.currentDetail;
  const running = Boolean(progress?.running || exporting);
  const liveCode = (liveDetail?.code || progress?.current || "").trim();
  const externalPin = String(focusCode || stickCode || "").trim();
  const currentCode = (pinnedCode || externalPin || liveCode).trim();
  const viewingLive =
    !currentCode ||
    !liveCode ||
    currentCode.toUpperCase() === liveCode.toUpperCase();

  const events = useMemo(() => {
    const norm = (c: string) => c.trim().toUpperCase();
    const want = currentCode ? norm(currentCode) : "";
    const fromLive = (progress?.events || []).filter(
      (ev) => !want || !ev.code || norm(ev.code) === want,
    );
    if (!pinnedCode) return fromLive;
    if (!pinnedEvents.length) return fromLive;
    if (!fromLive.length) return pinnedEvents;
    const seen = new Set(
      pinnedEvents.map(
        (e) => `${e.ts}|${e.phase}|${e.text}|${e.source || ""}`,
      ),
    );
    const extra = fromLive.filter(
      (e) => !seen.has(`${e.ts}|${e.phase}|${e.text}|${e.source || ""}`),
    );
    return extra.length ? [...pinnedEvents, ...extra] : pinnedEvents;
  }, [progress?.events, currentCode, pinnedCode, pinnedEvents]);

  // 首次出现刮削番号时钉住；换片不自动跟（除非 stickCode 被清空=回到当前）
  useEffect(() => {
    if (focusCode) return;
    if (!liveCode) return;
    if (stickCode) return;
    onStickCode?.(liveCode);
  }, [liveCode, focusCode, stickCode, onStickCode]);

  useEffect(() => {
    const code = String(focusCode || stickCode || "").trim();
    if (!code) {
      setPinnedCode("");
      setPinnedDetail(null);
      setPinnedEvents([]);
      setPinnedError("");
      setPinnedLoading(false);
      return;
    }
    setPinnedCode(code);
    setTab("detail");
    setPinnedError("");
    let cancelled = false;
    setPinnedLoading(true);
    // 先露出与实时刮削相同的字段模板（空值），避免「换了一套页」的感觉
    setPinnedDetail((prev) => {
      if (
        prev?.code &&
        prev.code.toUpperCase() === code.toUpperCase()
      ) {
        return prev;
      }
      if (
        liveDetail?.code &&
        liveDetail.code.toUpperCase() === code.toUpperCase()
      ) {
        return liveDetail;
      }
      return {
        code,
        phase: "done",
        title: "",
        titleZh: "",
        plot: "",
        actors: [],
        genres: [],
        studio: "",
        series: "",
        path: "",
        poster: "",
        posterLocal: "",
        sourceRuns: [],
        fieldSources: {},
        fieldTimings: {},
      };
    });
    // 实时流里若还有该番号日志，先秒开
    const warm = (progress?.events || []).filter(
      (ev) =>
        ev.code &&
        ev.code.toUpperCase() === code.toUpperCase(),
    );
    setPinnedEvents(warm);
    void fetchScrapeExportDetail(code)
      .then((d) => {
        if (cancelled) return;
        setPinnedDetail(d);
        const fromDetail = Array.isArray(d.events) ? d.events : [];
        setPinnedEvents(fromDetail.length ? fromDetail : warm);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setPinnedError(e instanceof Error ? e.message : "加载详情失败");
      })
      .finally(() => {
        if (!cancelled) setPinnedLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // focusNonce / refreshNonce 强制重拉；liveDetail 只作瞬时预填
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusCode, focusNonce, stickCode, refreshNonce]);

  // 钉住期间：同番号实时详情合并进来，但不要用缺字段的 live 盖掉已拉取的标签/系列
  useEffect(() => {
    if (!pinnedCode || !liveDetail?.code) return;
    if (liveDetail.code.toUpperCase() !== pinnedCode.toUpperCase()) return;
    setPinnedDetail((prev) => {
      if (!prev) return liveDetail;
      const liveGenres = liveDetail.genres || [];
      const prevGenres = prev.genres || [];
      return {
        ...prev,
        ...liveDetail,
        genres: liveGenres.length ? liveGenres : prevGenres,
        series: String(liveDetail.series || "").trim()
          ? liveDetail.series
          : prev.series,
        titleZh: String(liveDetail.titleZh || "").trim()
          ? liveDetail.titleZh
          : prev.titleZh,
        title: String(liveDetail.title || "").trim()
          ? liveDetail.title
          : prev.title,
        originalTitle: String(liveDetail.originalTitle || "").trim()
          ? liveDetail.originalTitle
          : prev.originalTitle,
        plot: String(liveDetail.plot || "").trim()
          ? liveDetail.plot
          : prev.plot,
        actors:
          liveDetail.actors && liveDetail.actors.length
            ? liveDetail.actors
            : prev.actors,
        studio: String(liveDetail.studio || "").trim()
          ? liveDetail.studio
          : prev.studio,
        poster: String(liveDetail.poster || "").trim()
          ? liveDetail.poster
          : prev.poster,
        posterLocal: String(liveDetail.posterLocal || "").trim()
          ? liveDetail.posterLocal
          : prev.posterLocal,
        fieldSources: {
          ...(prev.fieldSources || {}),
          ...(liveDetail.fieldSources || {}),
        },
        fieldTimings: {
          ...(prev.fieldTimings || {}),
          ...(liveDetail.fieldTimings || {}),
        },
        exportFields:
          (liveDetail.exportFields && liveDetail.exportFields.length
            ? liveDetail.exportFields
            : prev.exportFields) || [],
        sourceRuns:
          liveDetail.sourceRuns && liveDetail.sourceRuns.length
            ? liveDetail.sourceRuns
            : prev.sourceRuns,
      };
    });
  }, [liveDetail, pinnedCode]);

  const detail = pinnedCode ? pinnedDetail : liveDetail;

  if (!progress && !exporting && !pinnedCode) {
    return (
      <div className="scrape-log-empty mute">
        开始任务后，可在「详细数据 / 刮削日志」标签间切换查看当前片子。
      </div>
    );
  }

  return (
    <div className="scrape-view-tabs">
      <div className="scrape-view-tabs__bar" role="tablist" aria-label="刮削视图">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "detail"}
          className={`scrape-view-tabs__btn${tab === "detail" ? " is-active" : ""}`}
          onClick={() => setTab("detail")}
        >
          详细数据
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "log"}
          className={`scrape-view-tabs__btn${tab === "log" ? " is-active" : ""}`}
          onClick={() => setTab("log")}
        >
          刮削日志
        </button>
      </div>
      <div className="scrape-view-tabs__panel" role="tabpanel">
        {tab === "detail" ? (
          pinnedLoading && !detail?.code ? (
            <div className="scrape-detail-empty mute">加载 {pinnedCode} 详情…</div>
          ) : pinnedError && !detail?.code ? (
            <div className="scrape-detail-empty mute">{pinnedError}</div>
          ) : (
            <ScrapeDetailPane
              detail={detail}
              running={running && viewingLive}
            />
          )
        ) : (
          <ScrapeLogPane
            events={events}
            running={running && viewingLive}
            code={currentCode || undefined}
          />
        )}
      </div>
    </div>
  );
}
