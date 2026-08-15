import fs from "node:fs";
import path from "node:path";
import {
  applyPosterCropConfig,
  readJpegSize,
  type PosterCropConfig,
} from "./coverCrop.js";
import { collectDmmCidsFromHits } from "./dmmCid.js";
import { downloadBytes, downloadToFile } from "./download.js";
import { scrapeDmm } from "./providers/more.js";
import { SOURCE_RUNNERS } from "./providers/runners.js";
import { assertScrapeNotCancelled } from "./scrapeCancel.js";
import {
  filterFieldPriorityByCaps,
  sanitizeHitBySourceCaps,
  sourceHasField,
  type SourceFieldCap,
} from "./sourceFields.js";
import {
  resolveOrders,
  type PartialFromSource,
  type SourceId,
} from "./sources.js";
import type {
  CoverDownloadStrategy,
  FieldPriority,
  ScrapeMeta,
  SourceRun,
} from "./types.js";
import {
  codeFileStem,
  isJunkCoverUrl,
  isJunkTitle,
  isLikelyChinese,
  isLikelyJapanese,
  isQualityChineseTitle,
  stdCode,
} from "./util.js";

export type Dirs = { coversDir: string; metaDir: string };

type CoverCandidate = {
  url: string;
  source: string;
  portrait: boolean;
};

function metaPath(dirs: Dirs, code: string): string {
  return path.join(dirs.metaDir, `${codeFileStem(code)}.json`);
}

function coverPath(dirs: Dirs, code: string): string {
  return path.join(dirs.coversDir, `${codeFileStem(code)}.jpg`);
}

function posterPath(dirs: Dirs, code: string): string {
  return path.join(dirs.coversDir, `${codeFileStem(code)}.poster.jpg`);
}

function portraitWorkPath(dirs: Dirs, code: string): string {
  return path.join(dirs.coversDir, `${codeFileStem(code)}.portrait.jpg`);
}

function readCached(dirs: Dirs, code: string): ScrapeMeta | null {
  const p = metaPath(dirs, code);
  if (!fs.existsSync(p)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as ScrapeMeta;
    if (!data?.code) return null;
    const cover = coverPath(dirs, code);
    if (fs.existsSync(cover)) data.coverLocal = cover;
    const poster = posterPath(dirs, code);
    if (fs.existsSync(poster)) data.posterLocal = poster;
    return data;
  } catch {
    return null;
  }
}

function writeMeta(dirs: Dirs, meta: ScrapeMeta): void {
  fs.mkdirSync(dirs.metaDir, { recursive: true });
  const p = metaPath(dirs, meta.code);
  const tmp = `${p}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(meta, null, 2), "utf8");
  fs.renameSync(tmp, p);
}

export function getMeta(dirs: Dirs, code: string): ScrapeMeta | null {
  return readCached(dirs, stdCode(code));
}

function prependOrder(pref: unknown, base: SourceId[]): SourceId[] {
  const out: SourceId[] = [];
  const seen = new Set<string>();
  for (const item of [...(Array.isArray(pref) ? pref : []), ...base]) {
    const id = String(item || "")
      .trim()
      .toLowerCase() as SourceId;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out.length ? out : base;
}

function hitHasUsefulFields(hit: PartialFromSource): boolean {
  return Boolean(
    hit.title ||
      hit.poster ||
      hit.plot ||
      (hit.actors && hit.actors.length) ||
      (hit as { publisher?: string }).publisher ||
      hit.studio ||
      hit.premiered ||
      hit.productId,
  );
}

function dmmFieldScore(hit: PartialFromSource | null | undefined): number {
  if (!hit) return 0;
  let n = 0;
  if (hit.title) n += 2;
  if (hit.plot) n += 3;
  if (hit.actors?.length) n += 2;
  if (hit.studio) n += 1;
  if (hit.premiered) n += 1;
  if (hit.runtime) n += 1;
  if (hit.director) n += 1;
  if (hit.series) n += 1;
  if (hit.userRating) n += 1;
  if (hit.poster) n += 1;
  return n;
}

function pickBySourceOrder<T>(
  hits: PartialFromSource[],
  order: string[] | undefined,
  globalOrder: SourceId[],
  get: (h: PartialFromSource) => T | null | undefined,
  ok: (v: T) => boolean,
  opts?: { strict?: boolean; field?: SourceFieldCap },
): { value: T; source: string } | null {
  const strict = Boolean(opts?.strict);
  const field = opts?.field;
  const allowed = (sid: string) =>
    !field || sourceHasField(sid, field);
  const chain = strict
    ? (Array.isArray(order) ? order : [])
    : prependOrder(order?.length ? order : undefined, globalOrder);
  for (const sid of chain) {
    if (!allowed(sid)) continue;
    const hit = hits.find((h) => h.source === sid);
    if (!hit) continue;
    const v = get(hit);
    if (v != null && ok(v)) return { value: v, source: sid };
  }
  if (strict) return null;
  for (const hit of hits) {
    if (!allowed(hit.source)) continue;
    const v = get(hit);
    if (v != null && ok(v)) return { value: v, source: hit.source };
  }
  return null;
}

/**
 * 字段取值：① 严格按该字段配置源；② 配置源都无值时，才复用「已经打过」的其它源结果。
 * 不会暗示去新请求未配置源（例如封面没配 airav 就绝不单独跑 airav）。
 */
function pickConfiguredThenReuse<T>(
  hits: PartialFromSource[],
  configured: string[] | undefined,
  get: (h: PartialFromSource) => T | null | undefined,
  ok: (v: T) => boolean,
  field?: SourceFieldCap,
): { value: T; source: string } | null {
  const conf = (Array.isArray(configured) ? configured : [])
    .map((x) => String(x || "").trim().toLowerCase())
    .filter(Boolean);
  const primary = pickBySourceOrder(hits, conf, [], get, ok, {
    strict: true,
    field,
  });
  if (primary) return primary;
  // 未配置该字段源 → 不填（由任务裁剪 / preferLocal 负责）
  if (!conf.length) return null;
  const seen = new Set(conf);
  for (const hit of hits) {
    const sid = String(hit.source || "").trim().toLowerCase();
    if (!sid || seen.has(sid) || sid === "index" || sid === "forum") continue;
    if (field && !sourceHasField(sid, field)) continue;
    const v = get(hit);
    if (v != null && ok(v)) return { value: v, source: sid };
  }
  return null;
}

function deriveCollectOrder(
  fp: FieldPriority | undefined,
  fallback: SourceId[],
): SourceId[] {
  const out: SourceId[] = [];
  const seen = new Set<string>();
  for (const key of [
    "titleZh",
    "outline",
    "studio",
    "actors",
    "tags",
    "series",
    "cover",
  ] as const) {
    for (const item of fp?.[key] || []) {
      const id = String(item || "")
        .trim()
        .toLowerCase() as SourceId;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out.length ? out : fallback;
}

type CollectPlan = {
  runForumFirst: boolean;
  /** 厂牌 + 封面源（可与 title/actors 兜底源重叠，如 javbus） */
  coreOrder: SourceId[];
  titleZhFallback: SourceId[];
  actorsFallback: SourceId[];
};

function listFieldSources(
  fp: FieldPriority | undefined,
  key:
    | "titleZh"
    | "outline"
    | "publisher"
    | "studio"
    | "actors"
    | "cover"
    | "tags"
    | "series",
): SourceId[] {
  const out: SourceId[] = [];
  const seen = new Set<string>();
  for (const item of fp?.[key] || []) {
    const id = String(item || "")
      .trim()
      .toLowerCase() as SourceId;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

/** 网络源分波并行；色花堂不进源链（maker-fs 种子仅作刮后兜底） */
function deriveCollectPlan(
  fp: FieldPriority | undefined,
  fallback: SourceId[],
): CollectPlan {
  const titleZh = listFieldSources(fp, "titleZh");
  const outline = listFieldSources(fp, "outline");
  const studio = listFieldSources(fp, "studio");
  const actors = listFieldSources(fp, "actors");
  const cover = listFieldSources(fp, "cover");
  const tags = listFieldSources(fp, "tags");
  const series = listFieldSources(fp, "series");
  if (
    !titleZh.length &&
    !outline.length &&
    !studio.length &&
    !actors.length &&
    !cover.length &&
    !tags.length &&
    !series.length
  ) {
    const fb = [...fallback].filter((id) => id !== "forum");
    return {
      runForumFirst: false,
      coreOrder: fb,
      titleZhFallback: [],
      actorsFallback: [],
    };
  }
  const coreOrder: SourceId[] = [];
  const seen = new Set<string>();
  // 快源（封面/系列/制片/标签）靠前，保证系列在早停前已被抓到；
  // 中文标题/简介/女优随后（过盾源垫后）
  for (const id of [
    ...cover,
    ...series,
    ...studio,
    ...tags,
    ...actors,
    ...titleZh,
    ...outline,
  ]) {
    if (id === "forum" || seen.has(id)) continue;
    seen.add(id);
    coreOrder.push(id);
  }
  return {
    runForumFirst: false,
    coreOrder,
    titleZhFallback: [],
    actorsFallback: [],
  };
}

function usablePublisher(
  v: string | null | undefined,
  hit?: PartialFromSource,
): boolean {
  const s = String(v || "").trim();
  if (!s) return false;
  if (/^[-—–－ー・.\s]+$/.test(s)) return false;
  if (/^(?:なし|無|无|none|n\/a|null)$/i.test(s)) return false;
  const studio = String(hit?.studio || hit?.makers?.[0] || "").trim();
  const series = String(hit?.series || "").trim();
  if (series && (s === series || s.replace(/り$/u, "") === series.replace(/り$/u, ""))) {
    return false;
  }
  // JavBus 常把系列/企划名（如 おっぱい祭り）误填进发行商
  if (hit?.source === "javbus" && /祭/u.test(s) && studio && s !== studio) {
    return false;
  }
  return true;
}

/** 本地/索引源：仍走质量门。网络源带回的字段原样用，不做语种/长度清洗。 */
const LOCAL_FIELD_SOURCES = new Set([
  "index",
  "forum",
  "maker-fs",
  "seed",
  "local",
]);

function isLocalFieldSource(source: string | null | undefined): boolean {
  const s = String(source || "").trim().toLowerCase();
  return !s || LOCAL_FIELD_SOURCES.has(s);
}

function isNetworkFieldSource(source: string | null | undefined): boolean {
  return !isLocalFieldSource(source);
}

/** 本地 preferTitle 仍用质量门；网络命中见 pickTitleZhFromHit */
function usableTitleZh(title: string | null | undefined): boolean {
  return isQualityChineseTitle(title);
}

function pickTitleZhFromHit(hit: PartialFromSource): string | null {
  const zh = String((hit as { titleZh?: string }).titleZh || "").trim();
  const t = String(hit.title || "").trim();
  // 网络源：titleZh 原样采用；不再做语种/长度识别
  if (isNetworkFieldSource(hit.source)) {
    if (zh) return zh;
    // 中文站常用 title 即译名，亦原样用
    if (
      ["airav_io", "airav", "sevenmmtv", "iqqtv"].includes(
        String(hit.source || "").trim().toLowerCase(),
      ) &&
      t
    ) {
      return t;
    }
    return null;
  }
  if (usableTitleZh(zh)) return zh;
  if (usableTitleZh(t)) return t;
  return null;
}

function usableTitleJa(title: string | null | undefined): boolean {
  return isLikelyJapanese(title);
}

function pickTitleJaFromHit(hit: PartialFromSource): string | null {
  const ot = String(hit.originalTitle || "").trim();
  const t = String(hit.title || "").trim();
  const zh = String((hit as { titleZh?: string }).titleZh || "").trim();
  if (usableTitleJa(ot)) return ot;
  if (usableTitleJa(t)) return t;
  if (usableTitleJa(zh)) return zh;
  return null;
}

function forumTitleReady(
  preferTitle: string | undefined,
  hit: PartialFromSource | undefined,
): boolean {
  if (usableTitleZh(preferTitle)) return true;
  if (!hit) return false;
  return pickTitleZhFromHit(hit) !== null;
}

function forumActorsReady(
  preferActors: string[] | undefined,
  hit: PartialFromSource | undefined,
): boolean {
  const seeded = (preferActors || [])
    .map((a) => String(a || "").trim())
    .filter(Boolean);
  if (seeded.length) return true;
  return Boolean(hit?.actors?.length);
}

function hitHasTitleZh(hits: PartialFromSource[]): boolean {
  return hits.some((h) => pickTitleZhFromHit(h) !== null);
}

function hitHasActors(hits: PartialFromSource[]): boolean {
  return hits.some((h) => (h.actors?.length || 0) > 0);
}

function hasUsablePublisher(hits: PartialFromSource[]): boolean {
  return hits.some((h) => {
    const pub = String((h as { publisher?: string }).publisher || "").trim();
    return usablePublisher(pub, h);
  });
}

function hasUsableStudio(hits: PartialFromSource[]): boolean {
  return hits.some((h) => {
    const maker =
      String(h.studio || "").trim() ||
      String(h.makers?.[0] || "").trim();
    return Boolean(maker);
  });
}

function usablePlot(plot: string | null | undefined): boolean {
  const s = String(plot || "").trim();
  if (!s) return false;
  // 仅拦明确错误页；网络简介不再做长度/壳题清洗
  if (
    /under the age of\s*18|adult site that handles|strictly prohibited|access by anyone under/i.test(
      s,
    )
  ) {
    return false;
  }
  return true;
}

function hitHasOutline(hits: PartialFromSource[]): boolean {
  return hits.some((h) => usablePlot(h.plot));
}

function hitHasCover(hits: PartialFromSource[]): boolean {
  return hits.some(
    (h) =>
      Boolean(String(h.poster || "").trim()) ||
      Boolean(String(h.portrait || "").trim()),
  );
}

function hitHasTags(hits: PartialFromSource[]): boolean {
  return hits.some((h) => (h.genres?.length || 0) > 0);
}

function hitHasSeries(hits: PartialFromSource[]): boolean {
  return hits.some((h) => Boolean(String(h.series || "").trim()));
}

/** 某字段已齐，或该字段优先级里的源都试过（允许最终仍空） */
function fieldDoneOrExhausted(
  filled: boolean,
  srcs: SourceId[],
  triedSet: Set<string>,
): boolean {
  if (filled) return true;
  if (!srcs.length) return true;
  return srcs.every((id) => triedSet.has(id));
}

/**
 * 早停：配置了的字段必须「有值」或「该字段源链已跑完」。
 * 同一源一次请求会带回该站全部字段，缺的字段只再打尚未试过的源。
 */
function hitEnoughForCore(
  hits: PartialFromSource[],
  fp?: FieldPriority,
  preferTitle?: string,
  preferActors?: string[],
  tried?: string[],
): boolean {
  const cover = listFieldSources(fp, "cover");
  const titleZh = listFieldSources(fp, "titleZh");
  const outline = listFieldSources(fp, "outline");
  const actors = listFieldSources(fp, "actors");
  const tags = listFieldSources(fp, "tags");
  const studio = listFieldSources(fp, "studio");
  const pub = listFieldSources(fp, "publisher");
  // series 白名单：不参与早停强制
  const triedSet = new Set(tried || []);

  if (
    !cover.length &&
    !titleZh.length &&
    !outline.length &&
    !actors.length &&
    !tags.length &&
    !studio.length &&
    !pub.length &&
    !listFieldSources(fp, "series").length
  ) {
    return hits.some(
      (h) =>
        Boolean(String(h.title || "").trim()) ||
        Boolean(String(h.poster || "").trim()),
    );
  }

  if (
    !fieldDoneOrExhausted(hitHasCover(hits), cover, triedSet)
  ) {
    return false;
  }
  if (
    !fieldDoneOrExhausted(
      hitHasTitleZh(hits) || usableTitleZh(preferTitle),
      titleZh,
      triedSet,
    )
  ) {
    return false;
  }
  if (!fieldDoneOrExhausted(hitHasOutline(hits), outline, triedSet)) {
    return false;
  }
  if (
    !fieldDoneOrExhausted(
      hitHasActors(hits) || forumActorsReady(preferActors, undefined),
      actors,
      triedSet,
    )
  ) {
    return false;
  }
  if (!fieldDoneOrExhausted(hitHasTags(hits), tags, triedSet)) {
    return false;
  }
  if (!fieldDoneOrExhausted(hasUsableStudio(hits), studio, triedSet)) {
    return false;
  }
  if (!fieldDoneOrExhausted(hasUsablePublisher(hits), pub, triedSet)) {
    return false;
  }
  // 系列：白名单，不强制有值，也不为等系列源拖慢早停
  return true;
}

function appendCollectRun(
  acc: { hits: PartialFromSource[]; tried: string[]; runs: SourceRun[] },
  run: { hits: PartialFromSource[]; tried: string[]; runs: SourceRun[] },
): void {
  for (const raw of run.hits) {
    const h = sanitizeHitBySourceCaps(raw);
    const i = acc.hits.findIndex((x) => x.source === h.source);
    if (i >= 0) acc.hits[i] = { ...acc.hits[i], ...h };
    else acc.hits.push(h);
  }
  for (const t of run.tried) {
    if (!acc.tried.includes(t)) acc.tried.push(t);
  }
  acc.runs.push(...run.runs);
}

function mergeByFieldPriority(
  hits: PartialFromSource[],
  fp: FieldPriority | undefined,
  _metaOrder: SourceId[],
  coverOrder: SourceId[],
): { partial: PartialFromSource; fieldSources: Record<string, string> } | null {
  if (!hits.length) return null;
  const nonEmpty = (s: string | null | undefined) => Boolean(s && String(s).trim());
  const usableTitle = (s: string | null | undefined) =>
    nonEmpty(s) && !isJunkTitle(s);
  const usableCover = (s: string | null | undefined) =>
    nonEmpty(s) && !isJunkCoverUrl(s);
  const nonEmptyArr = (a: unknown) => Array.isArray(a) && a.length > 0;
  const fieldSources: Record<string, string> = {};

  // ① 该字段配置源优先 ② 无值才复用已跑过的其它源（不新发请求）
  const union = deriveCollectOrder(fp, []);
  const pick = <T>(
    order: string[] | undefined,
    get: (h: PartialFromSource) => T | null | undefined,
    ok: (v: T) => boolean,
    field?: SourceFieldCap,
  ) => pickConfiguredThenReuse(hits, order, get, ok, field);

  const titleZhPick = pick(
    listFieldSources(fp, "titleZh"),
    pickTitleZhFromHit,
    (v) => Boolean(v),
    "titleZh",
  );
  const titleZh = titleZhPick?.value || "";
  if (titleZhPick) fieldSources.titleZh = titleZhPick.source;

  // 日文/原文：优先并集内源，再复用已跑 hits
  const originalPick = pick(
    union,
    (h) => {
      const ot = String(h.originalTitle || "").trim();
      if (usableTitle(ot) && !isLikelyChinese(ot)) return ot;
      const t = String(h.title || "").trim();
      if (usableTitle(t) && !isLikelyChinese(t)) return t;
      return null;
    },
    usableTitle,
    "titleJa",
  );
  const originalTitle = originalPick?.value || "";
  if (originalPick) fieldSources.originalTitle = originalPick.source;

  const titleRawPick = pick(
    union,
    (h) => {
      const t = String(h.title || "").trim();
      return usableTitle(t) ? t : null;
    },
    usableTitle,
    "titleJa",
  );
  const titleRaw = titleRawPick?.value || "";
  if (titleRawPick) fieldSources.title = titleRawPick.source;

  const title = titleZh || titleRaw || originalTitle;
  if (titleZh && fieldSources.titleZh && !fieldSources.title) {
    fieldSources.title = fieldSources.titleZh;
  }

  const plotPick = pick(
    listFieldSources(fp, "outline"),
    (h) => h.plot,
    usablePlot,
    "outline",
  );
  const plot = plotPick?.value || "";
  if (plotPick) fieldSources.outline = plotPick.source;

  const coverSrcs = listFieldSources(fp, "cover");
  const coverChain = coverSrcs.length ? coverSrcs : coverOrder;
  const posterPick = pick(coverChain, (h) => h.poster, usableCover, "cover");
  const poster = posterPick?.value || null;
  if (posterPick) fieldSources.cover = posterPick.source;

  const portraitPick = pick(
    coverChain,
    (h) => h.portrait || null,
    usableCover,
    "cover",
  );
  const portrait = portraitPick?.value || null;
  if (portraitPick) fieldSources.poster = portraitPick.source;

  const fanartPick = pick(coverChain, (h) => h.fanart, nonEmptyArr, "cover");
  const fanart = fanartPick?.value || [];
  if (fanartPick) fieldSources.extraFanart = fanartPick.source;

  const genresPick = pick(
    listFieldSources(fp, "tags"),
    (h) => h.genres,
    nonEmptyArr,
    "tags",
  );
  const genres = genresPick?.value || [];
  if (genresPick) fieldSources.tags = genresPick.source;

  const actorsPick = pick(
    listFieldSources(fp, "actors"),
    (h) => h.actors,
    nonEmptyArr,
    "actors",
  );
  const actors = actorsPick?.value || [];
  if (actorsPick) fieldSources.actors = actorsPick.source;

  const publisherPick = pick(
    listFieldSources(fp, "publisher"),
    (h) => {
      const pub = String((h as { publisher?: string }).publisher || "").trim();
      return usablePublisher(pub, h) ? pub : null;
    },
    nonEmpty,
    "publisher",
  );
  const publisher = publisherPick?.value || "";
  if (publisherPick) fieldSources.publisher = publisherPick.source;

  const studioPick = pick(
    listFieldSources(fp, "studio"),
    (h) => {
      const maker = String(h.studio || "").trim();
      if (maker) return maker;
      return h.makers?.[0] || null;
    },
    nonEmpty,
    "studio",
  );
  const studio = studioPick?.value || "";
  if (studioPick) fieldSources.studio = studioPick.source;

  // 附带字段：并集优先，再复用已跑 hits
  const premieredPick = pick(union, (h) => h.premiered, nonEmpty);
  const premiered = premieredPick?.value || "";
  if (premieredPick) fieldSources.premiered = premieredPick.source;

  const runtimePick = pick(
    union,
    (h) => h.runtime,
    (v) => v != null && Number(v) > 0,
  );
  const runtime = runtimePick?.value ?? null;
  if (runtimePick) fieldSources.runtime = runtimePick.source;

  const ratingPick = pick(
    union,
    (h) => h.userRating,
    (v) => v != null && Number(v) > 0,
  );
  const userRating = ratingPick?.value ?? null;
  if (ratingPick) fieldSources.userRating = ratingPick.source;

  const directorPick = pick(union, (h) => h.director, nonEmpty);
  const director = directorPick?.value || "";
  if (directorPick) fieldSources.director = directorPick.source;

  const seriesPick = pick(
    listFieldSources(fp, "series"),
    (h) => h.series,
    nonEmpty,
    "series",
  );
  const series = seriesPick?.value || "";
  if (seriesPick) fieldSources.series = seriesPick.source;

  const productPick = pick(union, (h) => h.productId, nonEmpty);
  const productId = productPick?.value || "";
  if (productPick) fieldSources.productId = productPick.source;

  const titleHit =
    (titleZhPick && hits.find((h) => h.source === titleZhPick.source)) ||
    (titleRawPick && hits.find((h) => h.source === titleRawPick.source)) ||
    (originalPick && hits.find((h) => h.source === originalPick.source)) ||
    hits.find((h) => union.includes(h.source as SourceId)) ||
    hits[0]!;

  // 制片 makers：配置源优先；无则复用已跑 studio 能力源
  const studioSrcs = listFieldSources(fp, "studio");
  let makersOut: string[] = [];
  if (studioSrcs.length) {
    const fromConf = hits
      .filter((h) => studioSrcs.includes(h.source as SourceId))
      .flatMap((h) => h.makers || [])
      .filter(Boolean);
    makersOut = fromConf.length
      ? fromConf
      : hits
          .filter((h) => h.source !== "index" && sourceHasField(h.source, "studio"))
          .flatMap((h) => h.makers || [])
          .filter(Boolean);
  }

  return {
    partial: {
      code: titleHit.code,
      title,
      titleZh: titleZh || undefined,
      originalTitle,
      plot,
      premiered,
      publisher: publisher || undefined,
      studio: studio || undefined,
      makers: makersOut,
      actors,
      genres,
      runtime,
      userRating,
      director,
      series,
      productId,
      poster,
      portrait: portrait || undefined,
      fanart,
      source:
        titleZhPick?.source ||
        titleRawPick?.source ||
        originalPick?.source ||
        titleHit.source,
    },
    fieldSources,
  };
}

/** 强制/高概率走 FlareSolverr 的源（与 sources.access=proxy_flare 对齐） */
const FLARE_HEAVY_SOURCES = new Set<string>([
  "javdb",
  "javlibrary",
  "miss_av",
  "avmoo",
  "avsox",
  "mgstage",
  "fd2ppv",
  "fc2_hub",
]);

function sourceLikelyNeedsFlare(id: string): boolean {
  return FLARE_HEAVY_SOURCES.has(String(id || "").trim());
}

/** 快源「无详情」错误（可直接判空号，不必再耗时走慢源） */
function isNoDetailRunError(err: string): boolean {
  const s = String(err || "").trim().toLowerCase();
  if (!s) return false;
  if (s === "not_found" || s === "notfound") return true;
  return (
    s.includes("未找到详情") ||
    s.includes("详情页不存在") ||
    s.includes("not found") ||
    s.includes("no detail") ||
    s.includes("detail not found") ||
    s.includes("无有效字段")
  );
}

/** 判空主探源：这些确认无详情即可不等 iqqtv 等次级源 */
const EMPTY_PROBE_SOURCES = new Set<string>([
  "javbus",
  "jav321",
  "libredmm",
  "freejavbt",
]);

function runIsNoDetail(run: SourceRun): boolean {
  if (Boolean(run.ok)) return false;
  return isNoDetailRunError(String(run.error || ""));
}

/**
 * 快通道已跑过的 meta 源是否全部「无详情」。
 * 有任一成功 / 非无详情错误 → false（仍可交慢源补）。
 */
function allFastMetaRunsNoDetail(runs: SourceRun[]): boolean {
  const meta = runs.filter(
    (r) =>
      String(r.mode || "") === "meta" &&
      !sourceLikelyNeedsFlare(String(r.id || "")),
  );
  if (!meta.length) return false;
  if (meta.some((r) => Boolean(r.ok))) return false;
  return meta.every((r) => isNoDetailRunError(String(r.error || "")));
}

/** 主探源是否已全部返回无详情（可提前结束同波等待） */
function emptyProbeSourcesAllNoDetail(
  wave: SourceId[],
  runs: SourceRun[],
  mode: "meta" | "cover",
): boolean {
  const primary = wave.filter((id) => EMPTY_PROBE_SOURCES.has(id));
  if (!primary.length) return false;
  const metaRuns = runs.filter((r) => String(r.mode || "") === mode);
  return primary.every((id) => {
    const r = metaRuns.find((x) => String(x.id || "") === id);
    return Boolean(r && runIsNoDetail(r));
  });
}

/** 快通道：只跑不过盾源；过盾源留给慢通道补刮。 */
function splitOrderByChannel(
  order: SourceId[],
  channel?: string,
): { use: SourceId[]; deferredFlare: SourceId[] } {
  const use: SourceId[] = [];
  const deferredFlare: SourceId[] = [];
  const seen = new Set<string>();
  for (const id of order) {
    const sid = String(id || "").trim() as SourceId;
    if (!sid || seen.has(sid)) continue;
    seen.add(sid);
    if (String(channel || "").trim().toLowerCase() === "fast" && sourceLikelyNeedsFlare(sid)) {
      deferredFlare.push(sid);
    } else {
      use.push(sid);
    }
  }
  return { use, deferredFlare };
}

/**
 * 分波策略（用户约定）：
 * - 不过盾源：全部同一波并发请求
 * - 过盾源：每个单独一波，再加 Flare 全局单飞锁，一个一个来
 */
function buildSourceWaves(order: SourceId[]): SourceId[][] {
  const fast: SourceId[] = [];
  const slow: SourceId[] = [];
  const seen = new Set<string>();
  for (const id of order) {
    const sid = String(id || "").trim() as SourceId;
    if (!sid || seen.has(sid)) continue;
    seen.add(sid);
    if (sourceLikelyNeedsFlare(sid)) slow.push(sid);
    else fast.push(sid);
  }
  const waves: SourceId[][] = [];
  if (fast.length) waves.push(fast);
  for (const id of slow) waves.push([id]);
  return waves;
}

function hitEnoughForMode(
  mode: "meta" | "cover",
  hits: PartialFromSource[],
): boolean {
  if (mode === "cover") {
    return hits.some((h) => Boolean(h.poster));
  }
  const hasZh = hits.some((h) => pickTitleZhFromHit(h) !== null);
  const hasTitle = hits.some((h) => Boolean(String(h.title || "").trim()));
  const hasPublisher = hits.some((h) =>
    Boolean(String((h as { publisher?: string }).publisher || "").trim()),
  );
  const hasStudio = hits.some((h) =>
    Boolean(String(h.studio || "").trim() || String(h.makers?.[0] || "").trim()),
  );
  const hasActors = hits.some((h) => (h.actors?.length || 0) > 0);
  // 中文标题 + 发行/制片/女优齐了即可停
  if (hasZh && (hasPublisher || hasStudio || hasActors)) return true;
  if (hasTitle && hasStudio && hasActors) return true;
  return false;
}

/** 分波请求：不过盾整波并发等齐；过盾逐个排队。够用则不再进后续过盾波。
 * runnerCache：同一番号刮削内同站只请求一次，封面补抓/回退链复用详情里已拿全的字段。
 */
async function collectHits(
  code: string,
  order: SourceId[],
  preferCoverUrl: string | undefined,
  mode: "meta" | "cover",
  preferTitle?: string,
  preferActors?: string[],
  opts?: {
    stopWhen?: (hits: PartialFromSource[], tried: string[]) => boolean;
    runnerCache?: Map<string, Promise<PartialFromSource | null>>;
  },
): Promise<{ hits: PartialFromSource[]; tried: string[]; runs: SourceRun[] }> {
  const forumTitle = String(preferTitle || "").trim();
  const forumActors = (preferActors || [])
    .map((a) => String(a || "").trim())
    .filter(Boolean);
  const hits: PartialFromSource[] = [];
  const runs: SourceRun[] = [];
  const tried: string[] = [];
  const runnerCache = opts?.runnerCache;

  const runNetwork = (id: SourceId): Promise<PartialFromSource | null> => {
    const runner = SOURCE_RUNNERS[id];
    if (!runner) return Promise.resolve(null);
    if (!runnerCache) return runner(code);
    const hit = runnerCache.get(id);
    if (hit) return hit;
    const p = runner(code).catch(() => null);
    runnerCache.set(id, p);
    return p;
  };

  const runOne = async (id: SourceId) => {
    const t0 = Date.now();
    try {
      assertScrapeNotCancelled();
      if (id === "forum") {
      if (preferCoverUrl || forumTitle || forumActors.length) {
        // 色花堂为主源：preferTitle 直接作为中文标题（多帖优选已在 API 侧完成）
        const zh = usableTitleZh(forumTitle) ? forumTitle : "";
        return {
          hit: {
            code,
            title: forumTitle || "",
            titleZh: zh || undefined,
            actors: forumActors.length ? forumActors : undefined,
            poster: preferCoverUrl || null,
            source: "forum",
          } as PartialFromSource,
          run: {
            id,
            ok: true,
            ms: Date.now() - t0,
            mode,
            detail: forumTitle
              ? "wave+title"
              : forumActors.length
                ? "wave+actors"
                : "wave",
          } as SourceRun,
        };
      }
      return {
        hit: null,
        run: {
          id,
          ok: false,
          ms: Date.now() - t0,
          mode,
          error: "无论坛封面/标题/女优",
          detail: "wave",
        } as SourceRun,
      };
    }
    if (!SOURCE_RUNNERS[id]) {
      return {
        hit: null,
        run: {
          id,
          ok: false,
          ms: Date.now() - t0,
          mode,
          error: "未注册源",
          detail: "wave",
        } as SourceRun,
      };
    }
      const hit = await runNetwork(id);
      assertScrapeNotCancelled();
      const ms = Date.now() - t0;
      if (!hit) {
        return {
          hit: null,
          run: {
            id,
            ok: false,
            ms,
            mode,
            error: "未找到详情页",
            detail: "wave",
          } as SourceRun,
        };
      }
      if (mode === "meta") {
        if (hitHasUsefulFields(hit)) {
          const regionMsg = String(
            (hit as { message?: string }).message || "",
          );
          const regionBlocked = regionMsg.includes("地域限制");
          const hasMeta = Boolean(hit.title || hit.plot);
          return {
            hit,
            run: {
              id,
              ok: regionBlocked ? hasMeta : hitHasUsefulFields(hit),
              ms,
              mode,
              detail: "wave",
              error: regionBlocked
                ? regionMsg
                : !hasMeta && hit.poster
                  ? "仅封面/CID"
                  : undefined,
            } as SourceRun,
          };
        }
        return {
          hit: null,
          run: {
            id,
            ok: false,
            ms,
            mode,
            error: "无有效字段",
            detail: "wave",
          } as SourceRun,
        };
      }
      if (hit.poster) {
        return {
          hit,
          run: {
            id,
            ok: true,
            ms,
            mode,
            detail: "wave",
          } as SourceRun,
        };
      }
      return {
        hit: null,
        run: {
          id,
          ok: false,
          ms,
          mode,
          error: "无封面",
          detail: "wave",
        } as SourceRun,
      };
    } catch (e) {
      const err = e instanceof Error ? e.message : "请求失败";
      // deadline 取消：向上抛，立刻结束 scrapeOne，释放队列/锁
      if (/scrape-deadline|scrape aborted|flare aborted/i.test(err)) {
        throw e instanceof Error ? e : new Error(err);
      }
      return {
        hit: null,
        run: {
          id,
          ok: false,
          ms: Date.now() - t0,
          mode,
          error: err,
          detail: "wave",
        } as SourceRun,
      };
    }
  };

  const mergeHit = (hit: PartialFromSource) => {
    const i = hits.findIndex((x) => x.source === hit.source);
    if (i >= 0) hits[i] = { ...hits[i], ...hit };
    else hits.push(hit);
  };

  const stopWhen =
    opts?.stopWhen ||
    ((h: PartialFromSource[]) => hitEnoughForMode(mode, h));

  for (const wave of buildSourceWaves(order)) {
    tried.push(...wave);
    // 同波全部一起发出；不过盾波可在字段已够时提前收束（后台请求仍走 runnerCache）
    let pending = wave.map((id) => runOne(id).then((result) => ({ id, result })));
    let enough = false;
    while (pending.length > 0) {
      const settled = await Promise.race(
        pending.map((p, idx) => p.then((v) => ({ idx, v }))),
      );
      pending = pending.filter((_, idx) => idx !== settled.idx);
      runs.push(settled.v.result.run);
      if (settled.v.result.hit) mergeHit(settled.v.result.hit);
      // 过盾一波一个：跑完即检查；快源同波：够用就不等最慢那个
      if (
        stopWhen(
          hits,
          runs.filter((r) => r.mode === mode).map((r) => r.id),
        )
      ) {
        pending = [];
        enough = true;
        break;
      }
      // 无数据：主探源（javbus/jav321/libredmm/freejavbt）全无详情
      // → 立刻结束本波，不等 iqqtv 等次级源拖满超时
      if (
        mode === "meta" &&
        hits.length === 0 &&
        emptyProbeSourcesAllNoDetail(wave, runs, mode)
      ) {
        pending = [];
        break;
      }
    }
    if (enough || stopWhen(hits, tried)) break;
    // 本波已确认空号主探：不再进后续过盾波
    if (
      mode === "meta" &&
      hits.length === 0 &&
      emptyProbeSourcesAllNoDetail(wave, runs, mode)
    ) {
      break;
    }
  }

  return { hits, tried, runs };
}

async function maybeRetryDmmWithCid(
  code: string,
  hits: PartialFromSource[],
  sourceRuns: SourceRun[],
): Promise<{ hits: PartialFromSource[]; sourceRuns: SourceRun[] }> {
  const cids = collectDmmCidsFromHits(hits);
  if (!cids.length) return { hits, sourceRuns };

  const dmmHit = hits.find((h) => h.source === "dmm");
  const dmmRun = sourceRuns.find((r) => r.id === "dmm" && r.mode === "meta");
  const regionFailed = Boolean(
    dmmRun?.error?.includes("地域限制") ||
      String((dmmHit as { message?: string } | undefined)?.message || "").includes(
        "地域限制",
      ),
  );
  const weakDmm = dmmFieldScore(dmmHit) < 6;
  const dmmCid = String(dmmHit?.productId || "").toLowerCase();
  const foreignCid = cids.find((c) => c && c !== dmmCid);

  // 需要对齐 mdc-ng 的场景：无 DMM / 地域限制 / 字段弱 / 他源给出不同 CID
  const shouldRetry =
    !dmmHit || regionFailed || weakDmm || Boolean(foreignCid);
  if (!shouldRetry) return { hits, sourceRuns };

  const preferCids = [
    ...(foreignCid ? [foreignCid] : []),
    ...cids,
    ...(dmmCid ? [dmmCid] : []),
  ].filter((c, i, arr) => c && arr.indexOf(c) === i);

  const t0 = Date.now();
  try {
    const retry = await scrapeDmm(code, {
      preferCids,
      cidRetry: true,
    });
    const ms = Date.now() - t0;
    if (!retry) {
      sourceRuns.push({
        id: "dmm",
        ok: false,
        ms,
        mode: "meta",
        error: "CID 再次查询失败",
        detail: "cid-retry",
      });
      return { hits, sourceRuns };
    }
    const better = dmmFieldScore(retry) >= dmmFieldScore(dmmHit);
    if (!better && dmmHit) {
      sourceRuns.push({
        id: "dmm",
        ok: Boolean(retry.title || retry.poster),
        ms,
        mode: "meta",
        detail: "cid-retry",
        error: "CID 再次查询无更优结果",
      });
      return { hits, sourceRuns };
    }

    const nextHits = hits.filter((h) => h.source !== "dmm");
    nextHits.push(retry);
    const regionMsg = String((retry as { message?: string }).message || "");
    sourceRuns.push({
      id: "dmm",
      ok: Boolean(retry.title || retry.poster || retry.plot),
      ms,
      mode: "meta",
      detail: "cid-retry",
      error: regionMsg.includes("地域限制") ? regionMsg : undefined,
    });
    return { hits: nextHits, sourceRuns };
  } catch (e) {
    sourceRuns.push({
      id: "dmm",
      ok: false,
      ms: Date.now() - t0,
      mode: "meta",
      error: e instanceof Error ? e.message : "CID 再次查询失败",
      detail: "cid-retry",
    });
    return { hits, sourceRuns };
  }
}

async function downloadBestCover(
  hits: PartialFromSource[],
  coverOrder: SourceId[],
  preferCoverUrl: string | undefined,
  coverDest: string,
  allowForum: boolean,
  strategy: CoverDownloadStrategy,
): Promise<{
  ok: boolean;
  url: string | null;
  usedPortrait: boolean;
  source: string | null;
}> {
  const candidates = collectCoverCandidates(
    hits,
    coverOrder,
    preferCoverUrl,
    allowForum,
  );
  if (!candidates.length) {
    return { ok: false, url: null, usedPortrait: false, source: null };
  }

  fs.mkdirSync(path.dirname(coverDest), { recursive: true });

  if (strategy === "size") {
    let best: { cand: CoverCandidate; buf: Buffer } | null = null;
    for (const cand of candidates) {
      const buf = await downloadBytes(cand.url);
      if (!buf) continue;
      if (!best || buf.length > best.buf.length) {
        // 立刻丢掉次优缓冲，避免多候选叠内存
        best = { cand, buf };
      }
      // 显式丢掉未入选的 buf（best 已换引用）
    }
    if (!best) {
      return { ok: false, url: null, usedPortrait: false, source: null };
    }
    const tmp = `${coverDest}.tmp`;
    fs.writeFileSync(tmp, best.buf);
    fs.renameSync(tmp, coverDest);
    const out = {
      ok: true as const,
      url: best.cand.url,
      usedPortrait: best.cand.portrait,
      source: best.cand.source,
    };
    best = null;
    return out;
  }

  // priority：按数据源优先级依次尝试，成功即停
  for (const c of candidates) {
    if (!(await downloadToFile(c.url, coverDest))) continue;
    if (c.portrait) {
      const size = readJpegSize(coverDest);
      const landscape = candidates.find(
        (x) => x.source === c.source && !x.portrait && x.url !== c.url,
      );
      if (size && size.height < 300 && landscape) {
        if (await downloadToFile(landscape.url, coverDest)) {
          return {
            ok: true,
            url: landscape.url,
            usedPortrait: false,
            source: landscape.source,
          };
        }
      }
    }
    return {
      ok: true,
      url: c.url,
      usedPortrait: c.portrait,
      source: c.source,
    };
  }
  return { ok: false, url: null, usedPortrait: false, source: null };
}

function collectCoverCandidates(
  hits: PartialFromSource[],
  coverOrder: SourceId[],
  preferCoverUrl: string | undefined,
  allowForum: boolean,
): CoverCandidate[] {
  const usable = (s: string | null | undefined) =>
    Boolean(s && String(s).trim() && !isJunkCoverUrl(s));
  const out: CoverCandidate[] = [];
  const seen = new Set<string>();
  const push = (
    url: string | null | undefined,
    source: string,
    portrait: boolean,
  ) => {
    const u = String(url || "").trim();
    if (!usable(u) || !/^https?:\/\//i.test(u)) return;
    if (seen.has(u)) return;
    seen.add(u);
    out.push({ url: u, source, portrait });
  };

  const bySource = new Map(hits.map((h) => [h.source, h]));
  const orderedIds: string[] = [];
  for (const id of coverOrder) {
    if (!orderedIds.includes(id)) orderedIds.push(id);
  }
  // 配置源在前；其后才挂「已跑过」其它源作兜底（不因此新请求 airav/7mm）
  if (orderedIds.length) {
    for (const h of hits) {
      const sid = String(h.source || "");
      if (!sid || sid === "index" || sid === "forum") continue;
      if (!orderedIds.includes(sid)) orderedIds.push(sid);
    }
  } else {
    for (const h of hits) {
      if (!orderedIds.includes(h.source)) orderedIds.push(h.source);
    }
  }
  if (allowForum && preferCoverUrl && !orderedIds.includes("forum")) {
    orderedIds.push("forum");
  }

  for (const id of orderedIds) {
    if (id === "forum" && allowForum) {
      push(preferCoverUrl, "forum", false);
    }
    const hit = bySource.get(id);
    if (!hit) continue;
    // 搜索网格偏横版 pl；竖版 ps 作补充候选
    push(hit.poster, hit.source, false);
    push(hit.portrait, hit.source, true);
  }
  return out;
}

function buildLocalSeedHit(opts: {
  preferTitle?: string;
  preferActors?: string[];
  preferLocal?: {
    titleZh?: string;
    actors?: string[];
    outline?: string;
    tags?: string[];
    studio?: string;
    series?: string;
  };
}): PartialFromSource | null {
  const pl = opts.preferLocal || {};
  const titleZh = usableTitleZh(opts.preferTitle)
    ? String(opts.preferTitle || "").trim()
    : usableTitleZh(pl.titleZh)
      ? String(pl.titleZh || "").trim()
      : "";
  const actors = (
    Array.isArray(opts.preferActors) && opts.preferActors.length
      ? opts.preferActors
      : Array.isArray(pl.actors)
        ? pl.actors
        : []
  )
    .map((a) => String(a || "").trim())
    .filter(Boolean);
  const outline = String(pl.outline || "").trim();
  const tags = (Array.isArray(pl.tags) ? pl.tags : [])
    .map((t) => String(t || "").trim())
    .filter(Boolean);
  const studio = String(pl.studio || "").trim();
  const series = String(pl.series || "").trim();
  // 封面不走本地种子，poster 一律网络下载
  if (
    !titleZh &&
    !actors.length &&
    outline.length < 20 &&
    !tags.length &&
    !studio &&
    !series
  ) {
    return null;
  }
  return {
    source: "index",
    title: titleZh || undefined,
    titleZh: titleZh || undefined,
    actors: actors.length ? actors : undefined,
    plot: outline.length >= 20 ? outline : undefined,
    genres: tags.length ? tags : undefined,
    studio: studio || undefined,
    series: series || undefined,
  };
}

export async function scrapeOne(
  dirs: Dirs,
  codeRaw: string,
  opts?: {
    preferCoverUrl?: string;
    preferTitle?: string;
    preferActors?: string[];
    preferLocal?: {
      titleZh?: string;
      actors?: string[];
      outline?: string;
      tags?: string[];
      studio?: string;
      series?: string;
    };
    force?: boolean;
    kind?: string;
    region?: string;
    metaSources?: string[];
    coverSources?: string[];
    fieldPriority?: FieldPriority;
    coverDownloadStrategy?: CoverDownloadStrategy;
    posterCrop?: PosterCropConfig;
    /** fast：跳过过盾源；不够时 message=needs_flare 交慢通道 */
    channel?: string;
  },
): Promise<ScrapeMeta> {
  const code = stdCode(codeRaw);
  if (!code) {
    return {
      code: "",
      title: "",
      source: "none",
      scrapedAt: new Date().toISOString(),
      ok: false,
      message: "empty code",
    };
  }

  if (!opts?.force) {
    const hit = readCached(dirs, code);
    if (hit?.ok && (hit.coverLocal || fs.existsSync(coverPath(dirs, code)))) {
      return { ...hit, ok: true, message: "cache" };
    }
  }

  const orders = resolveOrders({
    kind: opts?.kind,
    region: opts?.region,
    code,
    metaSources: opts?.metaSources,
    coverSources: opts?.coverSources,
  });

  const fp = filterFieldPriorityByCaps(opts?.fieldPriority);
  const plan = deriveCollectPlan(fp, orders.meta);
  const channel = String(opts?.channel || "").trim().toLowerCase();
  const deferredFlare: SourceId[] = [];
  const takeOrder = (order: SourceId[]): SourceId[] => {
    const { use, deferredFlare: d } = splitOrderByChannel(order, channel);
    for (const id of d) {
      if (!deferredFlare.includes(id)) deferredFlare.push(id);
    }
    return use;
  };
  const coverOrder = takeOrder(
    (Array.isArray(fp?.cover) ? fp.cover : []).filter(
      (id) => id !== "forum",
    ) as SourceId[],
  );
  const coreOrder = takeOrder(
    plan.coreOrder.filter((id) => id !== "forum") as SourceId[],
  );
  const titleZhFallback = takeOrder(
    plan.titleZhFallback.filter((id) => id !== "forum") as SourceId[],
  );
  const actorsFallback = takeOrder(
    plan.actorsFallback.filter((id) => id !== "forum") as SourceId[],
  );

  const preferTitle =
    String(opts?.preferTitle || opts?.preferLocal?.titleZh || "").trim() ||
    undefined;
  const preferActors = (
    Array.isArray(opts?.preferActors) && opts.preferActors.length
      ? opts.preferActors
      : Array.isArray(opts?.preferLocal?.actors)
        ? opts.preferLocal.actors
        : []
  )
    .map((a) => String(a || "").trim())
    .filter(Boolean);

  // 网络优先：不再用本地种子抢先入 hits / 早停；本地合并由 API 事后按中文规则处理。
  // preferTitle/preferActors 仍可供 stopWhen 参考（论坛直传时），但不钉死字段。
  let hits: PartialFromSource[] = [];
  const tried: string[] = [];
  let sourceRuns: SourceRun[] = [];
  const acc = { hits, tried, runs: sourceRuns };
  // 同站只打一次详情：封面补抓 / 回退链复用，避免 javbus 封面再请求一遍
  const runnerCache = new Map<string, Promise<PartialFromSource | null>>();

  const localEnough = false;

  // 索引种子已够（字段优先级被裁空时）则不再打网络 meta
  if (!localEnough && coreOrder.length) {
    appendCollectRun(
      acc,
      await collectHits(
        code,
        coreOrder.filter((id) => !tried.includes(id)),
        undefined,
        "meta",
        preferTitle,
        preferActors,
        {
          stopWhen: (h, triedIds) =>
            hitEnoughForCore(h, fp, preferTitle, preferActors, triedIds),
          runnerCache,
        },
      ),
    );
  }

  // 快源主探已确认无详情 → 立即空号（不再跑中文/女优回退、封面、慢源）
  const fastEmptyNow = () =>
    channel === "fast" &&
    allFastMetaRunsNoDetail(sourceRuns) &&
    !hitEnoughForCore(hits, fp, preferTitle, preferActors, tried);

  if (fastEmptyNow()) {
    return {
      code,
      title: "",
      source: "none",
      scrapeKind: orders.kind,
      sourcesTried: tried,
      sourceRuns,
      scrapedAt: new Date().toISOString(),
      ok: false,
      message: "not_found",
    };
  }

  if (!localEnough && titleZhFallback.length) {
    appendCollectRun(
      acc,
      await collectHits(
        code,
        titleZhFallback.filter((id) => !tried.includes(id)),
        undefined,
        "meta",
        preferTitle,
        preferActors,
        { stopWhen: hitHasTitleZh, runnerCache },
      ),
    );
  }

  if (!localEnough && actorsFallback.length) {
    appendCollectRun(
      acc,
      await collectHits(
        code,
        actorsFallback.filter((id) => !tried.includes(id)),
        undefined,
        "meta",
        preferTitle,
        preferActors,
        { stopWhen: hitHasActors, runnerCache },
      ),
    );
  }

  // 回退后再次检查：快源仍全无详情 → 空号
  if (fastEmptyNow()) {
    return {
      code,
      title: "",
      source: "none",
      scrapeKind: orders.kind,
      sourcesTried: tried,
      sourceRuns,
      scrapedAt: new Date().toISOString(),
      ok: false,
      message: "not_found",
    };
  }

  // 仅当设置页/任务字段源序里明确挂了 dmm 才 CID 补抓。
  // 勿看 orders.meta 出厂兜底（里面常有 dmm），否则每号空耗 10–40s 地域限制。
  const wantDmm =
    coreOrder.includes("dmm") || coverOrder.includes("dmm");
  const retried = wantDmm
    ? await maybeRetryDmmWithCid(code, hits, sourceRuns)
    : { hits, sourceRuns };
  hits = retried.hits;
  sourceRuns = retried.sourceRuns;

  const hasPoster = hits.some((h) => h.poster);
  if (!hasPoster) {
    const coverRun = await collectHits(
      code,
      coverOrder.filter((id) => !tried.includes(id)),
      undefined,
      "cover",
      undefined,
      undefined,
      { runnerCache },
    );
    for (const h of coverRun.hits) {
      const clean = sanitizeHitBySourceCaps(h);
      if (!hits.some((x) => x.source === clean.source && x.poster === clean.poster)) {
        hits = [...hits, clean];
      }
    }
    for (const t of coverRun.tried) {
      if (!tried.includes(t)) tried.push(t);
    }
    for (const r of coverRun.runs) {
      if (!sourceRuns.some((x) => x.id === r.id && x.mode === r.mode)) {
        sourceRuns.push(r);
      }
    }
  }

  // 快通道：不过盾源已跑完仍缺核心字段，且还有过盾源可补 → 交慢通道
  if (
    channel === "fast" &&
    deferredFlare.length > 0 &&
    !hitEnoughForCore(hits, fp, preferTitle, preferActors, tried)
  ) {
    // 快源全员确认无详情：立即空号，不再 needs_flare 耗时走慢源
    if (allFastMetaRunsNoDetail(sourceRuns)) {
      return {
        code,
        title: "",
        source: "none",
        scrapeKind: orders.kind,
        sourcesTried: tried,
        sourceRuns,
        scrapedAt: new Date().toISOString(),
        ok: false,
        message: "not_found",
      };
    }
    return {
      code,
      title: "",
      source: "none",
      scrapeKind: orders.kind,
      sourcesTried: tried,
      sourceRuns,
      scrapedAt: new Date().toISOString(),
      ok: false,
      message: "needs_flare",
    };
  }

  const merged = mergeByFieldPriority(hits, fp, orders.meta, coverOrder);
  let partial: PartialFromSource | null = merged?.partial
    ? { ...merged.partial }
    : null;
  const fieldSources = { ...(merged?.fieldSources || {}) };

  // 网络优先：不再把 preferLocal / preferTitle 钉死盖掉网络结果。
  // 本地索引中文替换由 API 导出侧事后合并。

  const coverDest = coverPath(dirs, code);
  fs.mkdirSync(dirs.coversDir, { recursive: true });

  // 封面：仅网络源
  const allowForum = false;
  const strategy: CoverDownloadStrategy =
    opts?.coverDownloadStrategy === "size" ? "size" : "priority";
  const dl = await downloadBestCover(
    hits,
    coverOrder,
    undefined,
    coverDest,
    allowForum,
    strategy,
  );
  const gotCover = dl.ok;
  const oneCover = dl.url;
  if (gotCover && dl.source) {
    fieldSources.cover = dl.source;
  }

  // 海报竖图：配置源优先；也可复用已跑源（fieldSources.poster 已按此规则选出）
  let posterLocal: string | null = null;
  if (gotCover) {
    const pDest = posterPath(dirs, code);
    let portraitFile: string | null = null;
    const portraitUrl = String(partial?.portrait || "").trim();
    const portraitOk = Boolean(fieldSources.poster || !coverOrder.length);
    if (
      portraitOk &&
      portraitUrl &&
      !isJunkCoverUrl(portraitUrl) &&
      /^https?:\/\//i.test(portraitUrl) &&
      portraitUrl !== oneCover
    ) {
      const pWork = portraitWorkPath(dirs, code);
      if (await downloadToFile(portraitUrl, pWork)) {
        const sz = readJpegSize(pWork);
        const bytes = fs.existsSync(pWork) ? fs.statSync(pWork).size : 0;
        // 占位图通常极小；真竖版一般 ≥200×280 且 >12KB
        if (bytes >= 12_000 && sz && sz.width >= 200 && sz.height >= 280) {
          portraitFile = pWork;
        } else {
          try {
            fs.unlinkSync(pWork);
          } catch {
            /* ignore */
          }
        }
      }
    }
    const crop = await applyPosterCropConfig(coverDest, pDest, {
      kind: orders.kind,
      config: opts?.posterCrop,
      portraitSrc: portraitFile,
    });
    if (crop.ok && fs.existsSync(pDest)) {
      posterLocal = pDest;
    } else {
      posterLocal = coverDest;
    }
    if (portraitFile && portraitFile !== posterLocal) {
      try {
        fs.unlinkSync(portraitFile);
      } catch {
        /* ignore */
      }
    }
  }

  const source =
    partial?.source || (gotCover ? fieldSources.cover || "none" : "none");
  const now = new Date().toISOString();
  const titleZhSrc = String(fieldSources.titleZh || "").trim();
  const titleZhRaw = String(partial?.titleZh || "").trim();
  const titleRawForZh = String(partial?.title || "").trim();
  // 网络源 titleZh 原样落盘；仅本地/未知来源才做语种判断
  const titleZhFinal = isNetworkFieldSource(titleZhSrc)
    ? titleZhRaw || ""
    : (titleZhRaw && isLikelyChinese(titleZhRaw) ? titleZhRaw : "") ||
      (isLikelyChinese(titleRawForZh) ? titleRawForZh : "") ||
      "";
  if (!titleZhFinal && fieldSources.titleZh) delete fieldSources.titleZh;

  const fieldTimings: Record<
    string,
    { id: string; ms: number; ok: boolean; mode?: string }
  > = {};
  const timingFor = (field: string, src?: string) => {
    const id = String(src || fieldSources[field] || "").trim();
    if (!id) return;
    const matched = sourceRuns.filter((r) => r.id === id);
    const run =
      matched.find((r) => String(r.detail || "") !== "cid-retry") ||
      matched[0];
    fieldTimings[field] = {
      id,
      ms: run?.ms ?? 0,
      ok: run ? Boolean(run.ok) : true,
      mode: run?.mode,
    };
  };
  if (titleZhFinal) timingFor("titleZh");
  if (partial?.plot) timingFor("outline");
  if (partial?.studio) timingFor("studio");
  if (partial?.actors?.length) timingFor("actors");
  if (partial?.genres?.length) timingFor("tags");
  if (partial?.series) timingFor("series");
  if (gotCover && fieldSources.cover) timingFor("cover");

  // 允许写出：配置了网络源的字段
  const fromIndex = (key: string) =>
    String(fieldSources[key] || "").trim() === "index";
  const allowStudio =
    listFieldSources(fp, "studio").length > 0 || fromIndex("studio");
  const allowSeries =
    listFieldSources(fp, "series").length > 0 || fromIndex("series");
  const allowOutline =
    listFieldSources(fp, "outline").length > 0 ||
    fromIndex("outline") ||
    fromIndex("plot");
  const allowActors =
    listFieldSources(fp, "actors").length > 0 || fromIndex("actors");
  const allowTags =
    listFieldSources(fp, "tags").length > 0 ||
    fromIndex("tags") ||
    fromIndex("genres");
  const allowTitleZh =
    listFieldSources(fp, "titleZh").length > 0 || fromIndex("titleZh");

  if (!allowTitleZh) {
    delete fieldSources.titleZh;
    delete fieldSources.title;
  }
  if (!allowOutline) {
    delete fieldSources.outline;
    delete fieldSources.plot;
  }
  if (!allowStudio) {
    delete fieldSources.studio;
    delete fieldSources.publisher;
  }
  if (!allowActors) delete fieldSources.actors;
  if (!allowTags) {
    delete fieldSources.tags;
    delete fieldSources.genres;
  }
  if (!allowSeries) delete fieldSources.series;

  const allMetaNoDetail = (() => {
    const metaRuns = sourceRuns.filter(
      (r) => String(r.mode || "") === "meta" || !r.mode,
    );
    const use = metaRuns.length ? metaRuns : sourceRuns;
    if (!use.length) return false;
    if (use.some((r) => Boolean(r.ok))) return false;
    return use.every((r) => isNoDetailRunError(String(r.error || "")));
  })();

  const meta: ScrapeMeta = {
    code,
    // 无详情时不要用番号冒充 title，避免上游误判「元数据成功」
    title: allowTitleZh
      ? partial?.title || ""
      : partial?.title && !isLikelyChinese(partial.title)
        ? partial.title
        : "",
    titleZh: allowTitleZh ? titleZhFinal : "",
    originalTitle: partial?.originalTitle || partial?.title || "",
    plot: allowOutline ? partial?.plot || "" : "",
    premiered: partial?.premiered || "",
    publisher: "",
    studio: allowStudio ? partial?.studio || "" : "",
    makers: allowStudio ? partial?.makers || [] : [],
    actors: allowActors ? partial?.actors || [] : [],
    genres: allowTags ? partial?.genres || [] : [],
    runtime: partial?.runtime ?? null,
    userRating: partial?.userRating ?? null,
    director: partial?.director || "",
    series: allowSeries ? partial?.series || "" : "",
    productId: partial?.productId || "",
    poster: oneCover || null,
    portrait: partial?.portrait || null,
    fanart: partial?.fanart || [],
    source,
    scrapeKind: orders.kind,
    sourcesTried: tried,
    sourceRuns,
    fieldSources,
    fieldTimings,
    scrapedAt: now,
    coverLocal: gotCover ? coverDest : null,
    posterLocal,
    ok: Boolean(partial?.title || gotCover),
    // not_found 仅当全部源确认无详情；否则 no_meta 交给上游记失败重试
    message: partial?.title
      ? gotCover
        ? "ok"
        : "meta_ok_cover_fail"
      : gotCover
        ? "cover_fallback"
        : allMetaNoDetail
          ? "not_found"
          : "no_meta",
  };

  writeMeta(dirs, meta);
  return meta;
}

export function createQueue(concurrency: number) {
  let active = 0;
  const waiters: Array<() => void> = [];
  const acquire = (): Promise<void> =>
    new Promise((resolve) => {
      if (active < concurrency) {
        active += 1;
        resolve();
        return;
      }
      waiters.push(() => {
        active += 1;
        resolve();
      });
    });
  const release = () => {
    active -= 1;
    const next = waiters.shift();
    if (next) next();
  };
  return async function run<T>(fn: () => Promise<T>): Promise<T> {
    await acquire();
    try {
      return await fn();
    } finally {
      release();
    }
  };
}
