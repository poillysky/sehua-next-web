/** FlareSolverr 客户端（对齐 mdc-ng；proxy 必须用 { url } 对象） */

import fs from "node:fs";
import path from "node:path";
import { Agent, fetch as undiciFetch } from "undici";
import { getActiveProxy } from "./proxy.js";
import { isScrapeCancelled } from "./scrapeCancel.js";

let activeFlareUrl = "";

/** FS 本机服务：直连，不走刮削代理 */
const directAgent = new Agent();

/**
 * 易 403/CF、且 access=proxy_flare 的站：直连失败后再过盾。
 * 不稳定过盾站（airav / avbase / 7mmtv / mgstage）走 adaptive，勿写死进 CF_HOST_RE。
 */
const CF_HOST_RE =
  /(?:^|\.)(javdb\.|javlibrary\.|missav|javten\.|fd2ppv\.|avmoo\.|avsox\.|tellme\.pw)/i;

/** 运行时登记的镜像域名（仅 proxy_flare / viaFlare:true / adaptive 源） */
const extraFlareHosts = new Set<string>();

/** 稳定代理直连源：禁止登记，避免探测与刮削被误吸入过盾通道。
 * airav/avbase/7mmtv 已改为 adaptive，允许登记。
 */
const NEVER_REGISTER_FLARE_RE =
  /(?:^|\.)(madouqu|madou\.club|theporndb|javbus|seejav|caribbeancom|jav321|freejavbt|libredmm|contents\.fc2|dmm\.co\.jp|xchina|iqq[0-9])/i;

export function registerFlareHost(hostOrUrl: string): void {
  try {
    const raw = String(hostOrUrl || "").trim();
    if (!raw) return;
    const host = (
      /^https?:\/\//i.test(raw) ? new URL(raw).hostname : raw
    )
      .toLowerCase()
      .replace(/\.$/, "");
    if (!host || NEVER_REGISTER_FLARE_RE.test(host)) return;
    extraFlareHosts.add(host);
  } catch {
    /* ignore */
  }
}

/** FlareSolverr 全局单飞（跨站也串行，保护 FS）。
 * 间隔压到很低：reuse 会话时多余 sleep 只会拉长排队、对保护帮助不大。
 */
let flareLock: Promise<void> = Promise.resolve();
let lastFlareFinishedAt = 0;
let flareQueueDepth = 0;
const FLARE_MIN_GAP_MS = 120;
const FLARE_BUSY_GAP_MS = 250;

/** 暂停/取消时递增：排队中的过盾直接放弃，进行中的 AbortController 中断 */
let flareAbortEpoch = 0;
const flareAbortControllers = new Set<AbortController>();

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, Math.max(0, ms)));
}

/** 打断所有进行中 / 排队中的 FlareSolverr 请求（暂停刮削用） */
export function abortAllFlareRequests(reason = "scrape-paused"): number {
  flareAbortEpoch += 1;
  const n = flareAbortControllers.size;
  for (const ac of [...flareAbortControllers]) {
    try {
      ac.abort(reason);
    } catch {
      /* ignore */
    }
  }
  flareAbortControllers.clear();
  if (n > 0) {
    console.log(`[scrape] flare abort in-flight=${n} epoch=${flareAbortEpoch}`);
  }
  return n;
}

function withFlareLock<T>(fn: () => Promise<T>): Promise<T> {
  const enterEpoch = flareAbortEpoch;
  flareQueueDepth += 1;
  const run = flareLock.then(
    async () => {
      // 外层 scrape 已 deadline：排队中的过盾直接放弃，勿再占锁
      if (isScrapeCancelled()) {
        throw new Error("scrape aborted");
      }
      if (flareAbortEpoch !== enterEpoch) {
        throw new Error("flare aborted");
      }
      const gapMs =
        flareQueueDepth > 3 ? FLARE_BUSY_GAP_MS : FLARE_MIN_GAP_MS;
      const gap = lastFlareFinishedAt + gapMs - Date.now();
      if (gap > 0) await sleep(gap);
      if (isScrapeCancelled()) {
        throw new Error("scrape aborted");
      }
      if (flareAbortEpoch !== enterEpoch) {
        throw new Error("flare aborted");
      }
      try {
        return await fn();
      } finally {
        lastFlareFinishedAt = Date.now();
      }
    },
    async () => {
      if (isScrapeCancelled()) {
        throw new Error("scrape aborted");
      }
      if (flareAbortEpoch !== enterEpoch) {
        throw new Error("flare aborted");
      }
      const gapMs =
        flareQueueDepth > 3 ? FLARE_BUSY_GAP_MS : FLARE_MIN_GAP_MS;
      const gap = lastFlareFinishedAt + gapMs - Date.now();
      if (gap > 0) await sleep(gap);
      if (isScrapeCancelled()) {
        throw new Error("scrape aborted");
      }
      if (flareAbortEpoch !== enterEpoch) {
        throw new Error("flare aborted");
      }
      try {
        return await fn();
      } finally {
        lastFlareFinishedAt = Date.now();
      }
    },
  );
  flareLock = run.then(
    () => undefined,
    () => undefined,
  );
  return run.finally(() => {
    flareQueueDepth = Math.max(0, flareQueueDepth - 1);
  });
}

/**
 * 全局复用同一个 FS 浏览器会话（跨站）。
 * 按 host 各开一座会使 FlareSolverr 多开 Chrome，CPU/内存暴涨；
 * 单会话 + withFlareLock 串行 request.get 即可。
 */
type FlareSession = {
  id: string;
  proxyUrl: string;
  createdAt: number;
  lastUsedAt: number;
};
let sharedSession: FlareSession | null = null;
/** @deprecated 兼容旧调用；现统一走 sharedSession */
const sessionByHost = new Map<string, FlareSession>();
const SESSION_IDLE_MS = 25 * 60 * 1000;

/** 近窗流量：供监控判断过载 */
const LATENCY_WINDOW = 40;
const recentLatenciesMs: number[] = [];
let trafficOk = 0;
let trafficErr = 0;

export function noteFlareRequest(ms: number, ok: boolean): void {
  const n = Math.max(0, Math.floor(ms));
  recentLatenciesMs.push(n);
  while (recentLatenciesMs.length > LATENCY_WINDOW) recentLatenciesMs.shift();
  if (ok) trafficOk += 1;
  else trafficErr += 1;
  // 防止计数无限涨：按比例衰减
  if (trafficOk + trafficErr > 200) {
    trafficOk = Math.floor(trafficOk / 2);
    trafficErr = Math.floor(trafficErr / 2);
  }
}

export function getFlareTrafficStats(): {
  sample: number;
  avgMs: number;
  p95Ms: number;
  ok: number;
  err: number;
  errorRate: number;
} {
  const sample = recentLatenciesMs.length;
  if (!sample) {
    return { sample: 0, avgMs: 0, p95Ms: 0, ok: trafficOk, err: trafficErr, errorRate: 0 };
  }
  const sorted = [...recentLatenciesMs].sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);
  const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] || 0;
  const total = trafficOk + trafficErr;
  return {
    sample,
    avgMs: Math.round(sum / sample),
    p95Ms: p95,
    ok: trafficOk,
    err: trafficErr,
    errorRate: total ? trafficErr / total : 0,
  };
}

export function getSharedSessionId(): string | null {
  return sharedSession?.id || null;
}

async function flareApi(
  flare: string,
  body: Record<string, unknown>,
  timeoutMs: number,
): Promise<{
  status?: string;
  message?: string;
  session?: string;
  solution?: {
    response?: string;
    status?: number;
    url?: string;
    cookies?: FsCookie[];
    userAgent?: string;
  };
}> {
  const ac = new AbortController();
  flareAbortControllers.add(ac);
  const timer = setTimeout(() => {
    try {
      ac.abort("timeout");
    } catch {
      /* ignore */
    }
  }, Math.max(1000, timeoutMs));
  try {
    const res = await undiciFetch(flare, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      redirect: "follow",
      signal: ac.signal,
      dispatcher: directAgent,
    });
    const text = await res.text();
    // JSON 外壳 + HTML；默认约 6MB，可用 SCRAPE_MAX_HTML_BYTES 抬高（×2，封顶 12MB）
    const maxFlareJson = Math.max(
      2_000_000,
      Math.min(
        12_000_000,
        (Number(process.env.SCRAPE_MAX_HTML_BYTES || 3_000_000) || 3_000_000) *
          2,
      ),
    );
    if (text.length > maxFlareJson) {
      throw new Error(`flaresolverr response too large ${text.length}`);
    }
    let json: {
      status?: string;
      message?: string;
      session?: string;
      solution?: {
        response?: string;
        status?: number;
        url?: string;
        cookies?: FsCookie[];
        userAgent?: string;
      };
    };
    try {
      json = JSON.parse(text);
    } catch {
      throw new Error(`flaresolverr bad json HTTP ${res.status}`);
    }
    // 丢掉原始 JSON 字符串引用，只保留解析结果（过盾页常数 MB）
    const maxHtml =
      Number(process.env.SCRAPE_MAX_HTML_BYTES || 3_000_000) || 3_000_000;
    if (
      json.solution?.response &&
      json.solution.response.length > maxHtml
    ) {
      json.solution.response = json.solution.response.slice(0, maxHtml);
    }
    if (!res.ok || json.status !== "ok") {
      throw new Error(json.message || `flaresolverr failed HTTP ${res.status}`);
    }
    return json;
  } finally {
    clearTimeout(timer);
    flareAbortControllers.delete(ac);
  }
}

async function destroySession(flare: string, sessionId: string): Promise<void> {
  try {
    await flareApi(
      flare,
      { cmd: "sessions.destroy", session: sessionId },
      10000,
    );
  } catch {
    /* ignore */
  }
}

async function ensureHostSession(
  flare: string,
  host: string,
  proxyUrl: string,
): Promise<{ session: FlareSession; created: boolean }> {
  const now = Date.now();
  const hit = sharedSession;
  if (
    hit &&
    hit.proxyUrl === proxyUrl &&
    now - hit.lastUsedAt < SESSION_IDLE_MS
  ) {
    hit.lastUsedAt = now;
    return { session: hit, created: false };
  }
  if (hit) {
    sharedSession = null;
    sessionByHost.clear();
    await destroySession(flare, hit.id);
  }
  const created = await flareApi(flare, { cmd: "sessions.create" }, 20000);
  const id = String(created.session || "").trim();
  if (!id) throw new Error("flaresolverr sessions.create empty");
  const sess: FlareSession = {
    id,
    proxyUrl,
    createdAt: now,
    lastUsedAt: now,
  };
  sharedSession = sess;
  sessionByHost.set(host, sess);
  console.log(
    `[scrape] flare session create host=${host} session=${id.slice(0, 8)}… (shared)`,
  );
  return { session: sess, created: true };
}

export function hasFlareSession(url: string): boolean {
  const host = hostKey(url);
  if (!host) return false;
  const hit = sharedSession;
  if (!hit) return false;
  if (Date.now() - hit.lastUsedAt >= SESSION_IDLE_MS) return false;
  return true;
}

async function dropHostSession(_host: string): Promise<void> {
  const hit = sharedSession;
  if (!hit) return;
  sharedSession = null;
  sessionByHost.clear();
  const flare = getFlareSolverrUrl();
  if (flare) await destroySession(flare, hit.id);
}

export function normalizeFlareUrl(raw: string | null | undefined): string {
  let s = String(raw || "").trim();
  if (!s) return "";
  if (!/^https?:\/\//i.test(s)) s = `http://${s}`;
  s = s.replace(/\/+$/, "");
  if (!/\/v1$/i.test(s)) s = `${s}/v1`;
  return s;
}

export function applyFlareSolverr(url: string | null | undefined): void {
  const next = normalizeFlareUrl(url);
  const changed = next !== activeFlareUrl;
  activeFlareUrl = next;
  // 同 URL 反复同步（测试全部 / 定时探测）不得清 Cookie，否则无法复用
  if (changed) {
    clearCachedClearance();
    // 旧 FS 上的 session 作废
    const old = sharedSession;
    sharedSession = null;
    sessionByHost.clear();
    void (async () => {
      /* best-effort；新 URL 上 destroy 旧 session 无意义 */
      void old;
    })();
  }
  if (activeFlareUrl) {
    console.log(`[scrape] flaresolverr ${activeFlareUrl}`);
  } else {
    console.log("[scrape] flaresolverr cleared");
  }
}

export function getFlareSolverrUrl(): string {
  if (activeFlareUrl) return activeFlareUrl;
  return normalizeFlareUrl(process.env.FLARESOLVERR_URL || "");
}

export function hostNeedsFlare(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (CF_HOST_RE.test(host)) return true;
    if (extraFlareHosts.has(host)) return true;
    return false;
  } catch {
    return false;
  }
}

/** CF / 边缘封锁 / 空壳页 / 站方封 IP */
export function looksBlockedHtml(html: string | null | undefined): boolean {
  const s = String(html || "");
  if (s.length < 400) return true;
  return /Just a moment|cf-browser-verification|Attention Required|Edge IP Restricted|Cloudflare has blocked|403 ERROR|The request could not be satisfied|Access Denied|Please enable cookies|banned your access|禁止了你的訪問|異常行為|Web server is returning an unknown error|520:\s*Web server/i.test(
    s.slice(0, 4000),
  );
}

type FsCookie = {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  expires?: number;
};

type HostClearance = {
  cookieHeader: string;
  userAgent: string;
  /** ms epoch；过期后强制重过盾 */
  expiresAt: number;
};

/** 按 hostname 缓存过盾 Cookie（cf_clearance 等），避免每个番号都走 FS */
const clearanceByHost = new Map<string, HostClearance>();

/** 无 expires 时默认缓存 45 分钟 */
const DEFAULT_CLEARANCE_TTL_MS = 45 * 60 * 1000;

/** 落盘路径：定时探测 / 手动测试写入后，刮削进程重启也能复用 */
let clearanceStorePath = "";
let persistTimer: ReturnType<typeof setTimeout> | null = null;

export function setClearanceStorePath(filePath: string): void {
  clearanceStorePath = String(filePath || "").trim();
  loadClearanceFromDisk();
}

function hostKey(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function cookiesToHeader(cookies: FsCookie[]): string {
  const map = new Map<string, string>();
  for (const c of cookies) {
    const name = String(c.name || "").trim();
    if (!name) continue;
    map.set(name, String(c.value ?? ""));
  }
  return [...map.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
}

function clearanceExpiry(cookies: FsCookie[]): number {
  const now = Date.now();
  let soonest = now + DEFAULT_CLEARANCE_TTL_MS;
  for (const c of cookies) {
    const exp = Number(c.expires);
    if (!Number.isFinite(exp) || exp <= 0) continue;
    // FlareSolverr 常用 unix 秒
    const ms = exp > 1e12 ? exp : exp * 1000;
    if (ms <= now) continue;
    soonest = Math.min(soonest, ms);
  }
  // 提前 2 分钟失效，留余量
  return Math.max(now + 60_000, soonest - 120_000);
}

function schedulePersistClearance(): void {
  if (!clearanceStorePath) return;
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    persistClearanceToDisk();
  }, 250);
}

function persistClearanceToDisk(): void {
  if (!clearanceStorePath) return;
  try {
    const now = Date.now();
    const hosts: Record<string, HostClearance> = {};
    for (const [host, hit] of clearanceByHost) {
      if (hit.expiresAt > now) hosts[host] = hit;
    }
    const dir = path.dirname(clearanceStorePath);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      clearanceStorePath,
      JSON.stringify({ updatedAt: new Date().toISOString(), hosts }, null, 2),
      "utf8",
    );
  } catch (e) {
    console.warn(
      "[scrape] cf-clearance persist failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

function loadClearanceFromDisk(): void {
  if (!clearanceStorePath || !fs.existsSync(clearanceStorePath)) return;
  try {
    const raw = JSON.parse(fs.readFileSync(clearanceStorePath, "utf8")) as {
      hosts?: Record<string, HostClearance>;
    };
    const now = Date.now();
    let n = 0;
    for (const [host, hit] of Object.entries(raw.hosts || {})) {
      if (!hit?.cookieHeader || !hit.expiresAt || hit.expiresAt <= now) continue;
      clearanceByHost.set(host.toLowerCase(), {
        cookieHeader: String(hit.cookieHeader),
        userAgent: String(hit.userAgent || ""),
        expiresAt: Number(hit.expiresAt),
      });
      n += 1;
    }
    if (n) console.log(`[scrape] loaded ${n} cf-clearance host(s) from disk`);
  } catch (e) {
    console.warn(
      "[scrape] cf-clearance load failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

export function getCachedClearance(
  url: string,
): { cookieHeader: string; userAgent: string } | null {
  const key = hostKey(url);
  if (!key) return null;
  const hit = clearanceByHost.get(key);
  if (!hit) return null;
  if (Date.now() >= hit.expiresAt) {
    clearanceByHost.delete(key);
    schedulePersistClearance();
    return null;
  }
  return { cookieHeader: hit.cookieHeader, userAgent: hit.userAgent };
}

export function clearCachedClearance(urlOrHost?: string): void {
  if (!urlOrHost) {
    clearanceByHost.clear();
    schedulePersistClearance();
    return;
  }
  const key = hostKey(
    /^https?:\/\//i.test(urlOrHost) ? urlOrHost : `https://${urlOrHost}/`,
  );
  if (key) {
    clearanceByHost.delete(key);
    schedulePersistClearance();
  }
}

function rememberClearance(
  url: string,
  cookies: FsCookie[],
  userAgent: string,
): void {
  const key = hostKey(url);
  const header = cookiesToHeader(cookies);
  if (!key || !header) return;
  clearanceByHost.set(key, {
    cookieHeader: header,
    userAgent: userAgent || "",
    expiresAt: clearanceExpiry(cookies),
  });
  schedulePersistClearance();
}

function mergeCookieHeaders(...parts: Array<string | undefined>): string {
  const map = new Map<string, string>();
  for (const raw of parts) {
    for (const part of String(raw || "").split(";")) {
      const idx = part.indexOf("=");
      if (idx <= 0) continue;
      const name = part.slice(0, idx).trim();
      const value = part.slice(idx + 1).trim();
      if (name) map.set(name, value);
    }
  }
  return [...map.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
}

/** 给 FlareSolverr 注入 Cookie 用的可注册域（mgstage 年龄门需 .mgstage.com） */
function cookieDomainForUrl(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase().replace(/\.$/, "");
    if (!host) return "";
    if (/\.(co|com|ne|or|go|ac)\.[a-z]{2}$/i.test(host)) {
      const m = host.match(/([^.]+\.(?:co|com|ne|or|go|ac)\.[a-z]{2})$/i);
      return m ? `.${m[1]}` : `.${host}`;
    }
    const parts = host.split(".");
    if (parts.length >= 2) return `.${parts.slice(-2).join(".")}`;
    return host;
  } catch {
    return "";
  }
}

function cookieHeaderToFsCookies(
  cookieHeader: string | undefined,
  targetUrl?: string,
): Array<{ name: string; value: string; domain?: string; path?: string }> | undefined {
  const raw = String(cookieHeader || "").trim();
  if (!raw) return undefined;
  const domain = targetUrl ? cookieDomainForUrl(targetUrl) : "";
  const out: Array<{ name: string; value: string; domain?: string; path?: string }> = [];
  for (const part of raw.split(";")) {
    const idx = part.indexOf("=");
    if (idx <= 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (!name) continue;
    const c: { name: string; value: string; domain?: string; path?: string } = {
      name,
      value,
    };
    if (domain) {
      c.domain = domain;
      c.path = "/";
    }
    out.push(c);
  }
  return out.length ? out : undefined;
}

export type FlareFetchResult = {
  html: string;
  cookieHeader: string;
  userAgent: string;
  /** 过盾后浏览器实际落地 URL（跟跳转后） */
  finalUrl?: string;
};

export async function fetchViaFlareSolverr(
  targetUrl: string,
  opts?: {
    timeoutMs?: number;
    cookie?: string;
    useProxy?: boolean;
    waitInSeconds?: number;
  },
): Promise<string> {
  const r = await fetchViaFlareSolverrFull(targetUrl, opts);
  return r.html;
}

/** 过盾：同 host 复用 FS session，避免每个 URL 都重新解 Cloudflare */
export async function fetchViaFlareSolverrFull(
  targetUrl: string,
  opts?: {
    timeoutMs?: number;
    cookie?: string;
    useProxy?: boolean;
    /** SPA 站内跳转后等渲染（FlareSolverr waitInSeconds） */
    waitInSeconds?: number;
    /** 探测：session 失效也不重建重试，避免超时翻倍 */
    noSessionRetry?: boolean;
  },
): Promise<FlareFetchResult> {
  return withFlareLock(() => fetchViaFlareSolverrUnlocked(targetUrl, opts));
}

async function fetchViaFlareSolverrUnlocked(
  targetUrl: string,
  opts?: {
    timeoutMs?: number;
    cookie?: string;
    useProxy?: boolean;
    waitInSeconds?: number;
    noSessionRetry?: boolean;
  },
): Promise<FlareFetchResult> {
  const flare = getFlareSolverrUrl();
  if (!flare) throw new Error("flaresolverr not configured");

  const maxTimeout =
    opts?.timeoutMs != null
      ? Math.max(3000, Math.floor(opts.timeoutMs))
      : 60000;
  const useProxy = opts?.useProxy !== false;
  const proxy = useProxy ? getActiveProxy() : "";
  const host = hostKey(targetUrl) || "default";
  const waitInSeconds =
    opts?.waitInSeconds != null && opts.waitInSeconds > 0
      ? Math.min(30, Math.floor(opts.waitInSeconds))
      : 0;
  // 探测：客户端超时贴近 FS maxTimeout；刮削仍留缓冲
  const httpTimeoutPad = opts?.noSessionRetry
    ? Math.min(4000, Math.max(1500, Math.floor(maxTimeout * 0.15)))
    : Math.min(15000, Math.max(3000, maxTimeout));

  const runOnce = async (sessionId: string | null, reused: boolean) => {
    const body: Record<string, unknown> = {
      cmd: "request.get",
      url: targetUrl,
      maxTimeout,
    };
    if (sessionId) body.session = sessionId;
    if (proxy) body.proxy = { url: proxy };
    if (waitInSeconds > 0) body.waitInSeconds = waitInSeconds;
    // 站方年龄门 Cookie（如 mgstage adc=1）必须带 domain；每次请求都注入，避免 session 复用丢门禁
    const cookies = cookieHeaderToFsCookies(opts?.cookie, targetUrl);
    if (cookies) body.cookies = cookies;
    const t0 = Date.now();
    try {
      const json = await flareApi(flare, body, maxTimeout + httpTimeoutPad);
      const html = json.solution?.response;
      if (!html) throw new Error("flaresolverr empty response");
      const st = json.solution?.status;
      if (st && st >= 400) {
        throw new Error(`flaresolverr target HTTP ${st}`);
      }
      const solCookies = Array.isArray(json.solution?.cookies)
        ? json.solution!.cookies!
        : [];
      const ua = String(json.solution?.userAgent || "").trim();
      const finalUrl = String(json.solution?.url || targetUrl || "").trim();
      rememberClearance(finalUrl || targetUrl, solCookies, ua);
      if (finalUrl) registerFlareHost(finalUrl);
      const ms = Date.now() - t0;
      noteFlareRequest(ms, true);
      console.log(
        `[scrape] flare ${reused ? "reuse" : "fresh"} host=${host}${waitInSeconds ? ` wait=${waitInSeconds}s` : ""} ${ms}ms`,
      );
      return {
        html,
        cookieHeader: cookiesToHeader(solCookies),
        userAgent: ua,
        finalUrl: finalUrl || targetUrl,
      } satisfies FlareFetchResult;
    } catch (e) {
      noteFlareRequest(Date.now() - t0, false);
      throw e;
    }
  };

  // 探测：复用已有 shared session，绝不 sessions.create（可卡 20s）
  if (opts?.noSessionRetry) {
    const hit = sharedSession;
    if (
      hit &&
      hit.proxyUrl === proxy &&
      Date.now() - hit.lastUsedAt < SESSION_IDLE_MS
    ) {
      hit.lastUsedAt = Date.now();
      try {
        return await runOnce(hit.id, true);
      } catch {
        /* fall through to session-less */
      }
    }
    return await runOnce(null, false);
  }

  // 1) 有会话：直接复用（不再重新过盾）
  try {
    const ensured = await ensureHostSession(flare, host, proxy);
    try {
      return await runOnce(ensured.session.id, !ensured.created);
    } catch (e) {
      // session 失效 → 丢掉重建一次
      await dropHostSession(host);
      const again = await ensureHostSession(flare, host, proxy);
      return await runOnce(again.session.id, false);
    }
  } catch {
    // sessions API 不可用时回落无 session
    return await runOnce(null, false);
  }
}

export { mergeCookieHeaders };

/** 列出远端 FS 会话 id；不可达时抛错 */
export async function listFlareSessions(): Promise<string[]> {
  const flare = getFlareSolverrUrl();
  if (!flare) return [];
  const json = await flareApi(flare, { cmd: "sessions.list" }, 10000);
  const sessions = (json as { sessions?: unknown }).sessions;
  if (!Array.isArray(sessions)) return [];
  return sessions.map((s) => String(s || "").trim()).filter(Boolean);
}

/**
 * 回收 FS 浏览器会话：销毁孤儿 + 本进程 shared session。
 * 这是降内存的首选（每个 session ≈ 一座 Chrome），通常无需整容器重启。
 */
export async function recycleFlareSessions(opts?: {
  keepOwned?: boolean;
}): Promise<{ destroyed: number; kept: string | null; sessionsBefore: number }> {
  return withFlareLock(async () => {
    const flare = getFlareSolverrUrl();
    if (!flare) {
      return { destroyed: 0, kept: null, sessionsBefore: 0 };
    }
    const keepOwned = opts?.keepOwned === true;
    const owned = sharedSession?.id || null;
    let remote: string[] = [];
    try {
      remote = await listFlareSessions();
    } catch {
      remote = owned ? [owned] : [];
    }
    let destroyed = 0;
    for (const id of remote) {
      if (keepOwned && owned && id === owned) continue;
      await destroySession(flare, id);
      destroyed += 1;
    }
    if (!keepOwned) {
      sharedSession = null;
      sessionByHost.clear();
    } else if (owned && !remote.includes(owned)) {
      // 远端已无 owned，本地作废
      sharedSession = null;
      sessionByHost.clear();
    }
    console.log(
      `[scrape] flare recycle destroyed=${destroyed} keepOwned=${keepOwned} owned=${owned ? owned.slice(0, 8) : "-"}`,
    );
    return {
      destroyed,
      kept: keepOwned ? owned : null,
      sessionsBefore: remote.length,
    };
  });
}

/** 探测 FS 自身 + 可选抽样站（javdb） */
export async function probeFlareSolverr(sampleUrl?: string): Promise<{
  ok: boolean;
  flareSolverrUrl: string;
  message: string;
  sampleOk?: boolean;
  sampleError?: string;
}> {
  const flare = getFlareSolverrUrl();
  if (!flare) {
    return { ok: false, flareSolverrUrl: "", message: "未配置 FlareSolverr" };
  }
  try {
    const res = await undiciFetch(flare, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cmd: "request.get",
        url: "https://httpbin.org/get",
        maxTimeout: 20000,
      }),
      signal: AbortSignal.timeout(35000),
      dispatcher: directAgent,
    });
    const text = await res.text();
    let json: { status?: string; message?: string };
    try {
      json = JSON.parse(text);
    } catch {
      return {
        ok: false,
        flareSolverrUrl: flare,
        message: `FS 返回非 JSON HTTP ${res.status}`,
      };
    }
    if (!res.ok || json.status !== "ok") {
      return {
        ok: false,
        flareSolverrUrl: flare,
        message: json.message || `FS 失败 HTTP ${res.status}`,
      };
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const hint =
      /fetch failed|ECONNREFUSED|ENOTFOUND|timed out|abort/i.test(msg)
        ? `无法连接 FlareSolverr（${flare}）。请确认端口（常见 8191）与局域网可达`
        : msg;
    return {
      ok: false,
      flareSolverrUrl: flare,
      message: hint,
    };
  }

  const sample = (sampleUrl || "https://javdb.com/").trim();
  try {
    const html = await fetchViaFlareSolverr(sample, { timeoutMs: 60000 });
    const ok = !looksBlockedHtml(html);
    return {
      ok: true,
      flareSolverrUrl: flare,
      message: ok ? "过盾正常" : "FS 可达，但抽样站仍像挑战页",
      sampleOk: ok,
      sampleError: ok ? undefined : "challenge-like html",
    };
  } catch (e) {
    return {
      ok: true,
      flareSolverrUrl: flare,
      message: "FS 可达，抽样站失败",
      sampleOk: false,
      sampleError: e instanceof Error ? e.message : String(e),
    };
  }
}
