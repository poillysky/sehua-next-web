/**
 * airav.io 常跳转到临时镜像（如 inggairav5.work）。
 * 从入口页识别 HTTP / meta / JS 跳转，缓存可用中文站基址，避免天天改代码。
 */

import fs from "node:fs";
import path from "node:path";
import { fetchPage } from "./download.js";
import { registerFlareHost } from "./flaresolverr.js";

const ENTRY_SEEDS = [
  "https://airav.io/cn",
  "https://airav.io/",
  "https://www.airav.io/cn",
];

/** 缓存有效期；到期或刮削失败时重新探测 */
const TTL_MS = 6 * 60 * 60 * 1000;

type MirrorCache = {
  baseUrl: string;
  discoveredFrom?: string;
  updatedAt: string;
  expiresAt: number;
};

let storePath = "";
let memory: MirrorCache | null = null;
let resolving: Promise<string> | null = null;

export function setAiravMirrorStorePath(filePath: string): void {
  storePath = String(filePath || "").trim();
  memory = null;
  loadFromDisk();
}

function loadFromDisk(): void {
  if (!storePath || !fs.existsSync(storePath)) return;
  try {
    const raw = JSON.parse(fs.readFileSync(storePath, "utf8")) as MirrorCache;
    if (raw?.baseUrl && Number(raw.expiresAt) > Date.now()) {
      memory = raw;
      registerFlareHost(raw.baseUrl);
    }
  } catch {
    /* ignore */
  }
}

function persist(cache: MirrorCache): void {
  memory = cache;
  registerFlareHost(cache.baseUrl);
  if (!storePath) return;
  try {
    fs.mkdirSync(path.dirname(storePath), { recursive: true });
    fs.writeFileSync(storePath, JSON.stringify(cache, null, 2), "utf8");
    console.log(`[scrape] airav mirror → ${cache.baseUrl}`);
  } catch (e) {
    console.warn(
      "[scrape] airav-mirror.json write failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

export function invalidateAiravMirror(): void {
  memory = null;
  if (storePath && fs.existsSync(storePath)) {
    try {
      fs.unlinkSync(storePath);
    } catch {
      /* ignore */
    }
  }
}

/** 刮削过程中跟到新域名时立刻记下来 */
export function rememberAiravMirror(baseUrl: string, from?: string): void {
  const n = normalizeAiravCnBase(baseUrl);
  if (!n) return;
  if (memory?.baseUrl === n && memory.expiresAt > Date.now()) return;
  persist({
    baseUrl: n,
    discoveredFrom: from || memory?.discoveredFrom,
    updatedAt: new Date().toISOString(),
    expiresAt: Date.now() + TTL_MS,
  });
}

/** 规范化为 https://host/cn （airav 中文站） */
export function normalizeAiravCnBase(raw: string): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  try {
    const u = new URL(/^https?:\/\//i.test(s) ? s : `https://${s}`);
    const host = u.hostname.toLowerCase();
    if (!host) return "";
    const pathPart = u.pathname.replace(/\/+$/, "") || "";
    const cn = /\/cn(\/|$)/i.test(pathPart) || pathPart === "/cn";
    return `https://${host}${cn || !pathPart || pathPart === "/" ? "/cn" : pathPart}`;
  } catch {
    return "";
  }
}

function sameSiteFamily(a: string, b: string): boolean {
  try {
    const ha = new URL(a).hostname.replace(/^www\./, "").toLowerCase();
    const hb = new URL(b).hostname.replace(/^www\./, "").toLowerCase();
    if (ha === hb) return true;
    // airav.io ↔ *.airav.* / *airav*
    if (/airav/i.test(ha) && /airav/i.test(hb)) return true;
    return false;
  } catch {
    return false;
  }
}

/** 从 HTML / 落地 URL 抽出可能的镜像入口 */
export function extractAiravRedirectTargets(
  html: string,
  finalUrl: string,
  entryUrl: string,
): string[] {
  const out: string[] = [];
  const push = (raw: string | null | undefined) => {
    const n = normalizeAiravCnBase(String(raw || "").trim());
    if (!n || out.includes(n)) return;
    // 同站内相对跳转不需要当镜像
    if (sameSiteFamily(n, entryUrl) && sameSiteFamily(n, finalUrl)) {
      // 仍记录 finalUrl 的 host（可能从 / 跳到 /cn）
      if (!out.includes(n)) out.push(n);
      return;
    }
    out.push(n);
  };

  push(finalUrl);

  const text = String(html || "");
  const patterns = [
    /http-equiv=["']refresh["'][^>]*content=["'][^"']*url=([^"'>\s]+)/i,
    /content=["'][^"']*url=([^"'>\s]+)["'][^>]*http-equiv=["']refresh["']/i,
    /(?:window\.)?location(?:\.href|\.replace)?\s*=\s*['"](https?:\/\/[^'"]+)['"]/i,
    /location\.replace\(\s*['"](https?:\/\/[^'"]+)['"]/i,
    /(?:window\.)?location\.assign\(\s*['"](https?:\/\/[^'"]+)['"]/i,
    /href=["'](https?:\/\/[^"']*airav[^"']*)["']/i,
    /href=["'](https?:\/\/ingg[^"']+)["']/i,
  ];
  for (const re of patterns) {
    const flags = re.flags.includes("g") ? re.flags : `${re.flags}g`;
    const g = new RegExp(re.source, flags);
    let m: RegExpExecArray | null;
    while ((m = g.exec(text)) !== null) {
      push(m[1]);
    }
  }

  // 入口是 airav.io，落地却是别的 host → 就是浏览器跟到的镜像
  try {
    const entryHost = new URL(entryUrl).hostname.replace(/^www\./, "");
    const finalHost = new URL(finalUrl).hostname.replace(/^www\./, "");
    if (
      /airav\.io$/i.test(entryHost) &&
      finalHost &&
      finalHost.toLowerCase() !== entryHost.toLowerCase()
    ) {
      push(finalUrl);
    }
  } catch {
    /* ignore */
  }

  return out;
}

async function looksLikeAiravSite(base: string): Promise<boolean> {
  const b = normalizeAiravCnBase(base);
  if (!b) return false;
  const page = await fetchPage(b, {
    timeoutMs: 18000,
    referer: `${b}/`,
    sourceId: "airav_io",
    strictTimeout: true,
  });
  if (!page?.html) return false;
  // 跟跳后可能又换了域名
  const landed = normalizeAiravCnBase(page.finalUrl) || b;
  const html = page.html;
  const ok =
    /airav|瘋AV|疯AV|oneVideo|search_result|女优|女優/i.test(html) &&
    html.length > 2000 &&
    !/Just a moment|cf-browser-verification/i.test(html.slice(0, 2500));
  if (ok && landed !== b) {
    // 探测页自己又跳了一次
    registerFlareHost(landed);
  }
  return ok;
}

async function discoverOnce(preferred?: string): Promise<string> {
  const seeds = [
    normalizeAiravCnBase(preferred || ""),
    memory?.baseUrl ? normalizeAiravCnBase(memory.baseUrl) : "",
    ...ENTRY_SEEDS.map(normalizeAiravCnBase),
  ].filter(Boolean);
  const uniq = [...new Set(seeds)];

  const candidates: string[] = [];
  for (const seed of uniq) {
    const page = await fetchPage(seed, {
      timeoutMs: 22000,
      referer: seed.endsWith("/") ? seed : `${seed}/`,
      sourceId: "airav_io",
      strictTimeout: true,
    });
    if (!page) continue;
    const targets = extractAiravRedirectTargets(page.html, page.finalUrl, seed);
    for (const t of targets) {
      if (!candidates.includes(t)) candidates.push(t);
    }
    // 种子本身若可访问也留下
    const self = normalizeAiravCnBase(page.finalUrl) || seed;
    if (!candidates.includes(self)) candidates.push(self);
  }

  // 优先非 airav.io 的镜像（浏览器跳转目标），再回落官方
  const ranked = [
    ...candidates.filter((u) => !/airav\.io/i.test(u)),
    ...candidates.filter((u) => /airav\.io/i.test(u)),
  ];

  for (const cand of ranked) {
    if (await looksLikeAiravSite(cand)) {
      const page = await fetchPage(cand, {
        timeoutMs: 15000,
        sourceId: "airav_io",
        strictTimeout: true,
      });
      const finalBase =
        normalizeAiravCnBase(page?.finalUrl || cand) || cand;
      persist({
        baseUrl: finalBase,
        discoveredFrom: preferred || ENTRY_SEEDS[0],
        updatedAt: new Date().toISOString(),
        expiresAt: Date.now() + TTL_MS,
      });
      return finalBase;
    }
  }

  // 全失败：仍返回首选/官方，让后续报错可见
  return normalizeAiravCnBase(preferred || "") || ENTRY_SEEDS[0]!;
}

/**
 * 解析当前可用的 airav 中文站基址（自动跟镜像，带磁盘缓存）。
 */
export async function resolveAiravCnBase(opts?: {
  preferred?: string;
  forceRefresh?: boolean;
}): Promise<string> {
  if (!opts?.forceRefresh && memory && memory.expiresAt > Date.now()) {
    registerFlareHost(memory.baseUrl);
    return memory.baseUrl;
  }
  if (resolving) return resolving;
  resolving = discoverOnce(opts?.preferred)
    .catch(() => normalizeAiravCnBase(opts?.preferred || "") || ENTRY_SEEDS[0]!)
    .finally(() => {
      resolving = null;
    });
  return resolving;
}
