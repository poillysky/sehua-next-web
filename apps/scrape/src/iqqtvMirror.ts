/**
 * iQQTV 入口常 301 到新镜像（如 iqq5.xyz → iqqk4.quest）。
 * 跟随跳转并缓存可用基址；探测与刮削共用。
 */

import fs from "node:fs";
import path from "node:path";
import { fetchPage } from "./download.js";
import { looksBlockedHtml } from "./flaresolverr.js";

const ENTRY_SEEDS = [
  "https://iqq5.xyz/cn",
  "https://www.iqq5.xyz/cn",
  "https://iqqk4.quest/cn",
  "https://www.iqqk4.quest/cn",
  "https://iqq6.xyz/cn",
];

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

export function setIqqtvMirrorStorePath(filePath: string): void {
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
    }
  } catch {
    /* ignore */
  }
}

function persist(cache: MirrorCache): void {
  memory = cache;
  if (!storePath) return;
  try {
    fs.mkdirSync(path.dirname(storePath), { recursive: true });
    fs.writeFileSync(storePath, JSON.stringify(cache, null, 2), "utf8");
    console.log(`[scrape] iqqtv mirror → ${cache.baseUrl}`);
  } catch (e) {
    console.warn(
      "[scrape] iqqtv-mirror.json write failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

export function invalidateIqqtvMirror(): void {
  memory = null;
  if (storePath && fs.existsSync(storePath)) {
    try {
      fs.unlinkSync(storePath);
    } catch {
      /* ignore */
    }
  }
}

/** 规范化为 https://host （不含 /cn；刮削侧再拼 /cn） */
export function normalizeIqqtvRoot(raw: string): string {
  let b = String(raw || "")
    .trim()
    .replace(/\/$/, "");
  if (!b) return "";
  if (!/^https?:\/\//i.test(b)) b = `https://${b}`;
  try {
    const u = new URL(b);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    if (!host) return "";
    return `https://${host}`;
  } catch {
    return "";
  }
}

export function rememberIqqtvMirror(baseUrl: string, from?: string): void {
  const n = normalizeIqqtvRoot(baseUrl);
  if (!n) return;
  if (memory?.baseUrl === n && memory.expiresAt > Date.now()) return;
  persist({
    baseUrl: n,
    discoveredFrom: from || memory?.discoveredFrom,
    updatedAt: new Date().toISOString(),
    expiresAt: Date.now() + TTL_MS,
  });
}

/** 仅读缓存，不触发网络发现（连通探测用） */
export function getCachedIqqtvRoot(): string | null {
  if (memory?.baseUrl && memory.expiresAt > Date.now()) return memory.baseUrl;
  loadFromDisk();
  if (memory?.baseUrl && memory.expiresAt > Date.now()) return memory.baseUrl;
  return null;
}

function looksLikeIqqtv(html: string): boolean {
  if (!html || html.length < 800) return false;
  if (looksBlockedHtml(html) && html.length < 8000) return false;
  return /iqq|player\.php|search\.php|ga_name|tag-info/i.test(html);
}

async function probeRoot(root: string): Promise<string | null> {
  const cn = `${root}/cn`;
  const page = await fetchPage(`${cn}/`, {
    timeoutMs: 18000,
    referer: `${cn}/`,
    sourceId: "iqqtv",
    viaFlare: false,
    strictTimeout: true,
  });
  if (!page?.html || !looksLikeIqqtv(page.html)) return null;
  const landed = normalizeIqqtvRoot(page.finalUrl) || root;
  if (landed === root) return landed;
  // 入口已跳到新镜像，再确认落地站可用
  const again = await fetchPage(`${landed}/cn/`, {
    timeoutMs: 15000,
    referer: `${landed}/cn/`,
    sourceId: "iqqtv",
    viaFlare: false,
    strictTimeout: true,
  });
  if (again?.html && looksLikeIqqtv(again.html)) {
    return normalizeIqqtvRoot(again.finalUrl) || landed;
  }
  return landed;
}

async function discoverOnce(preferred?: string): Promise<string> {
  const seeds = [
    normalizeIqqtvRoot(preferred || ""),
    memory?.baseUrl ? normalizeIqqtvRoot(memory.baseUrl) : "",
    ...ENTRY_SEEDS.map(normalizeIqqtvRoot),
  ].filter(Boolean);
  const uniq = [...new Set(seeds)];

  for (const seed of uniq) {
    try {
      const hit = await probeRoot(seed);
      if (hit) {
        persist({
          baseUrl: hit,
          discoveredFrom: preferred || ENTRY_SEEDS[0],
          updatedAt: new Date().toISOString(),
          expiresAt: Date.now() + TTL_MS,
        });
        return hit;
      }
    } catch {
      /* try next */
    }
  }

  return (
    normalizeIqqtvRoot(preferred || "") ||
    normalizeIqqtvRoot(ENTRY_SEEDS[0]!) ||
    "https://iqq5.xyz"
  );
}

/** 解析当前可用 iQQTV 根域名（自动跟 301 镜像，带磁盘缓存）。 */
export async function resolveIqqtvRoot(opts?: {
  preferred?: string;
  forceRefresh?: boolean;
}): Promise<string> {
  if (!opts?.forceRefresh && memory && memory.expiresAt > Date.now()) {
    return memory.baseUrl;
  }
  if (resolving) return resolving;
  resolving = discoverOnce(opts?.preferred)
    .catch(
      () =>
        normalizeIqqtvRoot(opts?.preferred || "") ||
        normalizeIqqtvRoot(ENTRY_SEEDS[0]!) ||
        "https://iqq5.xyz",
    )
    .finally(() => {
      resolving = null;
    });
  return resolving;
}
