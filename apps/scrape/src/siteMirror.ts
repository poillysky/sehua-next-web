/**
 * 通用站点镜像自动切换。
 * - 磁盘缓存 meta/site-mirrors.json（按 sourceId）
 * - 种子列表 + 跟随跳转 + 内容校验
 * - airav_io / iqqtv 委托既有专用模块
 */

import fs from "node:fs";
import path from "node:path";
import { rememberAiravMirror } from "./airavMirror.js";
import { fetchPage } from "./download.js";
import {
  hostNeedsFlare,
  looksBlockedHtml,
  registerFlareHost,
} from "./flaresolverr.js";
import { rememberIqqtvMirror } from "./iqqtvMirror.js";
import { SOURCE_CATALOG } from "./sources.js";

const TTL_MS = 6 * 60 * 60 * 1000;

export type SiteMirrorProfile = {
  id: string;
  /** 探测/切换种子（完整 URL 或 origin） */
  seeds: string[];
  /** 规范化为刮削用基址 */
  normalize: (raw: string) => string;
  /** 落地 host 是否同族 */
  sameFamily?: (host: string) => boolean;
  /** HTML 像不像本站 */
  looksLike?: (html: string, finalUrl: string) => boolean;
  /** 强制 viaFlare；undefined = hostNeedsFlare */
  viaFlare?: boolean;
  /** 登记 Flare host，默认 true */
  registerFlare?: boolean;
  /** 探测路径，拼在 normalize 结果后 */
  probePath?: string;
  ttlMs?: number;
};

type MirrorEntry = {
  baseUrl: string;
  discoveredFrom?: string;
  updatedAt: string;
  expiresAt: number;
};

type StoreFile = {
  version: 1;
  mirrors: Record<string, MirrorEntry>;
};

let storePath = "";
const memory = new Map<string, MirrorEntry>();
const resolving = new Map<string, Promise<string>>();

function catalogDefault(id: string): string {
  return (
    SOURCE_CATALOG.find((s) => s.id === id)?.defaultUrl?.replace(/\/$/, "") ||
    ""
  );
}

function originOf(raw: string): string {
  try {
    const u = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}

function hostOf(raw: string): string {
  try {
    return new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`).hostname
      .toLowerCase()
      .replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** 仅保留 origin（无 path） */
export function normalizeOrigin(raw: string): string {
  return originOf(String(raw || "").trim()).replace(/\/$/, "");
}

function extractRedirectTargets(html: string, finalUrl: string): string[] {
  const out: string[] = [];
  const push = (raw: string | null | undefined) => {
    const o = originOf(String(raw || "").trim());
    if (o && !out.includes(o)) out.push(o);
  };
  push(finalUrl);
  const text = String(html || "");
  const patterns = [
    /http-equiv=["']refresh["'][^>]*content=["'][^"']*url=([^"'>\s]+)/i,
    /content=["'][^"']*url=([^"'>\s]+)["'][^>]*http-equiv=["']refresh["']/i,
    /(?:window\.)?location(?:\.href|\.replace)?\s*=\s*['"](https?:\/\/[^'"]+)['"]/i,
    /location\.replace\(\s*['"](https?:\/\/[^'"]+)['"]/i,
    /(?:window\.)?location\.assign\(\s*['"](https?:\/\/[^'"]+)['"]/i,
  ];
  for (const re of patterns) {
    const g = new RegExp(
      re.source,
      re.flags.includes("g") ? re.flags : `${re.flags}g`,
    );
    let m: RegExpExecArray | null;
    while ((m = g.exec(text)) !== null) push(m[1]);
  }
  return out;
}

function defaultLooksLike(html: string): boolean {
  if (!html || html.length < 600) return false;
  if (looksBlockedHtml(html) && html.length < 12000) return false;
  return true;
}

/** 各源镜像配置（官方稳定站也配 seeds，便于跟 301 换域） */
export const SITE_MIRROR_PROFILES: Record<string, SiteMirrorProfile> = {
  javbus: {
    id: "javbus",
    seeds: [
      "https://www.javbus.com",
      "https://www.seejav.me",
      "https://seejav.me",
    ],
    normalize: normalizeOrigin,
    sameFamily: (h) => /javbus|seejav/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/javbus|seejav|bigImage|磁力|女優|女优/i.test(html) || html.length > 4000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  miss_av: {
    id: "miss_av",
    seeds: [
      "https://missav123.com",
      "https://missav.com",
      "https://www.missav123.com",
      "https://missav.ws",
      "https://missav.live",
    ],
    normalize: normalizeOrigin,
    sameFamily: (h) => /missav/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/missav|og:title|space-y-2|女优|女優/i.test(html) || html.length > 8000),
    viaFlare: true,
    probePath: "/",
  },
  sevenmmtv: {
    id: "sevenmmtv",
    seeds: [
      "https://7mmtv.sx",
      "https://www.7mmtv.sx",
      "https://7mmtv.com",
      "https://7mm.tv",
    ],
    normalize: (raw) =>
      normalizeOrigin(raw).replace(/\/zh$/i, "") || normalizeOrigin(raw),
    sameFamily: (h) => /7mm/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/7mmtv|censored_content|searchall|search_keyword/i.test(html) ||
        html.length > 5000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/zh/",
  },
  avmoo: {
    id: "avmoo",
    seeds: ["https://avmoo.shop", "https://www.avmoo.shop"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /avmoo/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/avmoo|\/cn\/movies|q-page|女优|女優/i.test(html) || html.length > 2000),
    // Quasar SPA：Flare 用于渲染 JS，不是 CF 挑战
    viaFlare: true,
    probePath: "/cn",
  },
  avsox: {
    id: "avsox",
    seeds: ["https://avsox.click", "https://www.avsox.click"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /avsox/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/avsox|\/cn\/movies|q-page|女优|女優/i.test(html) || html.length > 2000),
    // 同 avmoo：SPA 渲染
    viaFlare: true,
    probePath: "/cn",
  },
  javdb: {
    id: "javdb",
    seeds: [
      "https://javdb.com",
      "https://www.javdb.com",
      "https://javdb368.com",
    ],
    normalize: normalizeOrigin,
    sameFamily: (h) => /javdb/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/javdb|movie-list|strong.uid|over18/i.test(html) || html.length > 5000),
    viaFlare: true,
    probePath: "/",
  },
  javlibrary: {
    id: "javlibrary",
    seeds: [
      "https://www.javlibrary.com/cn",
      "https://www.javlibrary.com",
      "https://www.b47w.com/cn",
    ],
    normalize: (raw) => {
      const o = normalizeOrigin(raw);
      if (!o) return "";
      return `${o}/cn`;
    },
    sameFamily: (h) => /javlibrary|b47w/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/javlibrary|videothumblist|idinfo/i.test(html) || html.length > 4000),
    viaFlare: true,
    probePath: "/",
  },
  avbase: {
    id: "avbase",
    seeds: ["https://www.avbase.net", "https://avbase.net"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /avbase/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/avbase|作品|女優|女优/i.test(html) || html.length > 8000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  fc2_hub: {
    id: "fc2_hub",
    seeds: ["https://javten.com", "https://www.javten.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /javten/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/javten|fc2|作品|\/en\/|\/cn\//i.test(html) || html.length > 5000),
    viaFlare: true,
    // CF 后常跳 /en；探测跟用户打开路径
    probePath: "/en",
  },
  fd2ppv: {
    id: "fd2ppv",
    seeds: ["https://fd2ppv.cc", "https://www.fd2ppv.cc"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /fd2ppv/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/fd2ppv|fc2|ppv/i.test(html) || html.length > 3000),
    viaFlare: true,
    probePath: "/",
  },
  freejavbt: {
    id: "freejavbt",
    seeds: ["https://freejavbt.com", "https://www.freejavbt.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /freejavbt/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/freejavbt|javbt/i.test(html) || html.length > 3000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  madou: {
    id: "madou",
    seeds: ["https://madou.club", "https://www.madou.club"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /madou\.club/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/madou|麻豆/i.test(html) || html.length > 3000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  madouqu: {
    id: "madouqu",
    seeds: ["https://madouqu.com", "https://www.madouqu.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /madouqu/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/madouqu|麻豆/i.test(html) || html.length > 3000),
    // 本机/代理通常无 CF；强制 Flare 反而慢且详情常缺封面图
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  xiao_huang_shu: {
    id: "xiao_huang_shu",
    seeds: ["https://xchina.co", "https://www.xchina.co"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /xchina/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/xchina|小黄书|写真/i.test(html) || html.length > 3000),
    // 本机/代理通常无 CF；强制 Flare 反而慢
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  jav321: {
    id: "jav321",
    seeds: ["https://www.jav321.com", "https://jav321.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /jav321/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/jav321|v\.php|search/i.test(html) || html.length > 2000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  dmm: {
    id: "dmm",
    seeds: ["https://www.dmm.co.jp"],
    normalize: (raw) => {
      const o = normalizeOrigin(raw);
      // 登录域不是业务站，禁止当成镜像落地
      if (/accounts\.dmm\.co\.jp/i.test(o)) return "https://www.dmm.co.jp";
      return o || "https://www.dmm.co.jp";
    },
    sameFamily: (h) =>
      /dmm\.co\.jp/i.test(h) && !/^accounts\./i.test(h.replace(/^www\./, "")),
    looksLike: (html, finalUrl) => {
      if (/accounts\.dmm\.co\.jp/i.test(finalUrl || "")) return false;
      const head = String(html || "").slice(0, 4000);
      if (/ログイン|アカウント|DMMアカウント/i.test(head) && head.length < 15000) {
        return false;
      }
      return String(html || "").length > 1000;
    },
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  mgstage: {
    id: "mgstage",
    seeds: ["https://www.mgstage.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /mgstage/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/mgstage|adc/i.test(html) || html.length > 2000),
    viaFlare: true,
    probePath: "/",
  },
  carib: {
    id: "carib",
    seeds: ["https://www.caribbeancom.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /caribbeancom/i.test(h),
    looksLike: (html) => html.length > 1000,
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  fc2: {
    id: "fc2",
    seeds: ["https://adult.contents.fc2.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /fc2\.com/i.test(h),
    looksLike: (html) => html.length > 1000,
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  libredmm: {
    id: "libredmm",
    seeds: ["https://www.libredmm.com"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /libredmm/i.test(h),
    looksLike: (html) => html.length > 400,
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
  airav: {
    id: "airav",
    seeds: ["https://www.airav.wiki", "https://airav.wiki"],
    normalize: normalizeOrigin,
    sameFamily: (h) => /airav\.wiki/i.test(h),
    looksLike: (html) =>
      defaultLooksLike(html) &&
      (/airav|wiki|video/i.test(html) || html.length > 2000),
    viaFlare: false,
    registerFlare: false,
    probePath: "/",
  },
};

export function getSiteMirrorProfile(
  id: string,
): SiteMirrorProfile | undefined {
  return SITE_MIRROR_PROFILES[String(id || "").trim().toLowerCase()];
}

export function listMirrorProfileIds(): string[] {
  return Object.keys(SITE_MIRROR_PROFILES);
}

export function setSiteMirrorStorePath(filePath: string): void {
  storePath = String(filePath || "").trim();
  memory.clear();
  loadFromDisk();
}

function loadFromDisk(): void {
  if (!storePath || !fs.existsSync(storePath)) return;
  try {
    const raw = JSON.parse(fs.readFileSync(storePath, "utf8")) as StoreFile;
    const now = Date.now();
    for (const [id, ent] of Object.entries(raw?.mirrors || {})) {
      if (!ent?.baseUrl || Number(ent.expiresAt) <= now) continue;
      memory.set(id, ent);
      const prof = SITE_MIRROR_PROFILES[id];
      if (prof?.viaFlare !== false && prof?.registerFlare !== false) {
        registerFlareHost(ent.baseUrl);
      }
    }
  } catch {
    /* ignore */
  }
}

function persistAll(): void {
  if (!storePath) return;
  try {
    const mirrors: Record<string, MirrorEntry> = {};
    for (const [id, ent] of memory.entries()) mirrors[id] = ent;
    fs.mkdirSync(path.dirname(storePath), { recursive: true });
    const payload: StoreFile = { version: 1, mirrors };
    fs.writeFileSync(storePath, JSON.stringify(payload, null, 2), "utf8");
  } catch (e) {
    console.warn(
      "[scrape] site-mirrors.json write failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

function persistOne(id: string, ent: MirrorEntry, log = true): void {
  memory.set(id, ent);
  const prof = SITE_MIRROR_PROFILES[id];
  if (prof?.viaFlare !== false && prof?.registerFlare !== false) {
    registerFlareHost(ent.baseUrl);
  }
  persistAll();
  if (log) console.log(`[scrape] ${id} mirror → ${ent.baseUrl}`);
}

export function rememberSiteMirror(
  id: string,
  baseUrl: string,
  from?: string,
): void {
  const sid = String(id || "").trim().toLowerCase();
  if (sid === "airav_io") {
    rememberAiravMirror(baseUrl, from);
    return;
  }
  if (sid === "iqqtv") {
    rememberIqqtvMirror(baseUrl, from);
    return;
  }
  const prof = SITE_MIRROR_PROFILES[sid];
  if (!prof) return;
  const n = prof.normalize(baseUrl);
  if (!n) return;
  const prev = memory.get(sid);
  if (prev?.baseUrl === n && prev.expiresAt > Date.now()) return;
  persistOne(sid, {
    baseUrl: n,
    discoveredFrom: from || prev?.discoveredFrom,
    updatedAt: new Date().toISOString(),
    expiresAt: Date.now() + (prof.ttlMs || TTL_MS),
  });
}

export function invalidateSiteMirror(id: string): void {
  const sid = String(id || "").trim().toLowerCase();
  memory.delete(sid);
  persistAll();
}

export function getCachedSiteMirror(id: string): string | null {
  const sid = String(id || "").trim().toLowerCase();
  const ent = memory.get(sid);
  if (!ent?.baseUrl || ent.expiresAt <= Date.now()) return null;
  return ent.baseUrl;
}

async function probeCandidate(
  prof: SiteMirrorProfile,
  seed: string,
): Promise<string | null> {
  const preferred = prof.normalize(seed) || seed.replace(/\/$/, "");
  if (!preferred) return null;
  const pathPart = prof.probePath || "/";
  const url = `${preferred.replace(/\/$/, "")}${
    pathPart === "/"
      ? "/"
      : pathPart.startsWith("/")
        ? pathPart
        : `/${pathPart}`
  }`;
  const viaFlare =
    prof.viaFlare !== undefined
      ? prof.viaFlare
      : hostNeedsFlare(url)
        ? true
        : undefined;
  // 代理直连源禁止登记过盾 host，否则后续探测会被 hostNeedsFlare 误吸进 Flare
  if (viaFlare !== false && prof.registerFlare !== false) {
    registerFlareHost(preferred);
  }

  const page = await fetchPage(url, {
    timeoutMs: viaFlare === true ? 55000 : 20000,
    sourceId: prof.id,
    viaFlare,
    referer: `${preferred}/`,
    strictTimeout: true,
  });
  if (!page?.html) return null;

  const targets = extractRedirectTargets(page.html, page.finalUrl || url)
    .map((t) => prof.normalize(t))
    .filter(Boolean);
  const self = prof.normalize(page.finalUrl || preferred) || preferred;
  const ordered = [...new Set([self, ...targets, preferred])];

  for (const cand of ordered) {
    const host = hostOf(cand);
    if (prof.sameFamily && host && !prof.sameFamily(host)) {
      continue;
    }
    const checkPath = prof.probePath || "/";
    const checkUrl = `${cand.replace(/\/$/, "")}${
      checkPath === "/"
        ? "/"
        : checkPath.startsWith("/")
          ? checkPath
          : `/${checkPath}`
    }`;
    let html = page.html;
    let finalUrl = page.finalUrl || url;
    if (prof.normalize(finalUrl) !== cand) {
      const again = await fetchPage(checkUrl, {
        timeoutMs: viaFlare === true ? 45000 : 16000,
        sourceId: prof.id,
        viaFlare,
        referer: `${cand}/`,
        strictTimeout: true,
      });
      if (!again?.html) continue;
      html = again.html;
      finalUrl = again.finalUrl || checkUrl;
    }
    const ok = prof.looksLike
      ? prof.looksLike(html, finalUrl)
      : defaultLooksLike(html);
    if (!ok) continue;
    return prof.normalize(finalUrl) || cand;
  }
  return null;
}

async function discoverOnce(
  prof: SiteMirrorProfile,
  preferred?: string,
): Promise<string> {
  const cached = memory.get(prof.id)?.baseUrl;
  const seeds = [
    preferred ? prof.normalize(preferred) : "",
    cached ? prof.normalize(cached) : "",
    ...prof.seeds.map((s) => prof.normalize(s) || s),
    catalogDefault(prof.id),
  ].filter(Boolean);
  const uniq = [...new Set(seeds)];

  for (const seed of uniq) {
    try {
      const hit = await probeCandidate(prof, seed);
      if (hit) {
        persistOne(prof.id, {
          baseUrl: hit,
          discoveredFrom: preferred || prof.seeds[0],
          updatedAt: new Date().toISOString(),
          expiresAt: Date.now() + (prof.ttlMs || TTL_MS),
        });
        return hit;
      }
    } catch {
      /* next */
    }
  }

  return (
    (preferred ? prof.normalize(preferred) : "") ||
    prof.normalize(prof.seeds[0] || "") ||
    catalogDefault(prof.id) ||
    prof.seeds[0] ||
    ""
  );
}

/**
 * 解析当前可用基址。airav_io / iqqtv 走专用模块。
 * skipDiscover：仅用缓存/preferred，不扫种子（连通探测用，避免每次重过盾）。
 */
export async function resolveSiteMirror(
  id: string,
  opts?: {
    preferred?: string;
    forceRefresh?: boolean;
    skipDiscover?: boolean;
  },
): Promise<string> {
  const sid = String(id || "").trim().toLowerCase();
  const preferred = String(opts?.preferred || "").trim();

  if (sid === "airav_io") {
    const { resolveAiravCnBase, getCachedAiravCnBase, normalizeAiravCnBase } =
      await import("./airavMirror.js");
    if (opts?.skipDiscover && !opts?.forceRefresh) {
      return (
        getCachedAiravCnBase() ||
        normalizeAiravCnBase(preferred) ||
        "https://airav.io/cn"
      );
    }
    return resolveAiravCnBase({
      preferred: opts?.preferred,
      forceRefresh: opts?.forceRefresh,
    });
  }
  if (sid === "iqqtv") {
    const { resolveIqqtvRoot, getCachedIqqtvRoot, normalizeIqqtvRoot } =
      await import("./iqqtvMirror.js");
    if (opts?.skipDiscover && !opts?.forceRefresh) {
      const root =
        getCachedIqqtvRoot() ||
        normalizeIqqtvRoot(preferred) ||
        "https://iqq5.xyz";
      return `${root}/cn`;
    }
    const root = await resolveIqqtvRoot({
      preferred: opts?.preferred,
      forceRefresh: opts?.forceRefresh,
    });
    return `${root}/cn`;
  }

  const prof = SITE_MIRROR_PROFILES[sid];
  if (!prof) {
    return String(opts?.preferred || catalogDefault(sid) || "").replace(
      /\/$/,
      "",
    );
  }

  if (!opts?.forceRefresh) {
    const hit = memory.get(sid);
    if (hit && hit.expiresAt > Date.now() && hit.baseUrl) {
      if (prof.viaFlare !== false && prof.registerFlare !== false) {
        registerFlareHost(hit.baseUrl);
      }
      return hit.baseUrl;
    }
  }

  if (opts?.skipDiscover) {
    return (
      (preferred ? prof.normalize(preferred) : "") ||
      prof.normalize(prof.seeds[0] || "") ||
      catalogDefault(sid) ||
      ""
    );
  }

  const existing = resolving.get(sid);
  if (existing) return existing;

  const p = discoverOnce(prof, opts?.preferred)
    .catch(
      () =>
        (opts?.preferred ? prof.normalize(opts.preferred) : "") ||
        prof.normalize(prof.seeds[0] || "") ||
        catalogDefault(sid),
    )
    .finally(() => {
      resolving.delete(sid);
    });
  resolving.set(sid, p);
  return p;
}

/** 刮削失败时：清缓存并强制重解析一次 */
export async function refreshSiteMirror(
  id: string,
  preferred?: string,
): Promise<string> {
  const sid = String(id || "").trim().toLowerCase();
  if (sid === "airav_io") {
    const { invalidateAiravMirror, resolveAiravCnBase } = await import(
      "./airavMirror.js"
    );
    invalidateAiravMirror();
    return resolveAiravCnBase({ preferred, forceRefresh: true });
  }
  if (sid === "iqqtv") {
    const { invalidateIqqtvMirror, resolveIqqtvRoot } = await import(
      "./iqqtvMirror.js"
    );
    invalidateIqqtvMirror();
    const root = await resolveIqqtvRoot({ preferred, forceRefresh: true });
    return `${root}/cn`;
  }
  invalidateSiteMirror(sid);
  return resolveSiteMirror(sid, { preferred, forceRefresh: true });
}

function hasMirrorFailover(id: string): boolean {
  const sid = String(id || "").trim().toLowerCase();
  if (sid === "airav_io" || sid === "iqqtv") return true;
  const seeds = SITE_MIRROR_PROFILES[sid]?.seeds || [];
  return seeds.length > 1;
}

/**
 * 刮削包装：先解析可用基址；失败且有多镜像时强制换站再试一次。
 * 成功时写入磁盘缓存（含跳转后的 host）。
 */
export async function withSiteMirrorBase<T>(
  id: string,
  preferred: string | undefined,
  run: (base: string) => Promise<T | null>,
): Promise<T | null> {
  const sid = String(id || "").trim().toLowerCase();
  const pref =
    String(preferred || "").trim() || catalogDefault(sid) || undefined;
  let base = await resolveSiteMirror(sid, { preferred: pref });
  if (!base) return null;
  let result = await run(base);
  if (result != null) {
    rememberSiteMirror(sid, base, pref);
    return result;
  }
  if (!hasMirrorFailover(sid)) return null;
  base = await refreshSiteMirror(sid, pref);
  if (!base) return null;
  result = await run(base);
  if (result != null) rememberSiteMirror(sid, base, pref);
  return result;
}
