import fs from "node:fs";
import path from "node:path";
import { fetch as undiciFetch } from "undici";
import {
  fetchViaFlareSolverrFull,
  getCachedClearance,
  getFlareSolverrUrl,
  hasFlareSession,
  hostNeedsFlare,
  looksBlockedHtml,
  mergeCookieHeaders,
  clearCachedClearance,
} from "./flaresolverr.js";
import { getActiveProxy } from "./proxy.js";
import { cookieForUrl } from "./sourceCookies.js";
import { UA } from "./util.js";

/** 同 host 限流：快源可并行；过盾站仍单飞（先建 cookie 再复用）。 */
type HostSem = {
  max: number;
  active: number;
  wait: Array<() => void>;
};
const hostSems = new Map<string, HostSem>();

/** 直连刚被 CF 打回（403）的 host：短时跳过直连，少烧无效请求 */
const directSkipUntil = new Map<string, number>();
const DIRECT_SKIP_MS = 3 * 60 * 1000;

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase() || "default";
  } catch {
    return "default";
  }
}

function hostMaxParallel(host: string): number {
  const h = host || "default";
  // 过盾站：必须串行，否则多开会话/空打 CF
  try {
    if (hostNeedsFlare(`https://${h}/`)) return 1;
  } catch {
    /* ignore */
  }
  // javbus / freejavbt 等：并发 5 时真正吃满同站并行
  return 4;
}

function markDirectSkip(host: string): void {
  if (!host) return;
  directSkipUntil.set(host, Date.now() + DIRECT_SKIP_MS);
}

function shouldSkipDirect(host: string): boolean {
  const until = directSkipUntil.get(host) || 0;
  if (!until) return false;
  if (Date.now() >= until) {
    directSkipUntil.delete(host);
    return false;
  }
  return true;
}

async function withHostGate<T>(host: string, fn: () => Promise<T>): Promise<T> {
  const key = host || "default";
  let sem = hostSems.get(key);
  if (!sem) {
    sem = { max: hostMaxParallel(key), active: 0, wait: [] };
    hostSems.set(key, sem);
  } else {
    sem.max = hostMaxParallel(key);
  }
  if (sem.active >= sem.max) {
    await new Promise<void>((resolve) => {
      sem!.wait.push(resolve);
    });
  }
  sem.active += 1;
  try {
    return await fn();
  } finally {
    sem.active = Math.max(0, sem.active - 1);
    const next = sem.wait.shift();
    if (next) next();
  }
}

export async function downloadToFile(
  url: string,
  dest: string,
  opts?: { timeoutMs?: number },
): Promise<boolean> {
  const buf = await downloadBytes(url, opts);
  if (!buf) return false;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmp = `${dest}.tmp`;
  fs.writeFileSync(tmp, buf);
  fs.renameSync(tmp, dest);
  return true;
}

/** 下载图片到内存（用于按文件大小择优） */
export async function downloadBytes(
  url: string,
  opts?: { timeoutMs?: number },
): Promise<Buffer | null> {
  const timeoutMs = opts?.timeoutMs ?? 25000;
  if (!url || !/^https?:\/\//i.test(url)) return null;
  try {
    const res = await undiciFetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      headers: {
        "User-Agent": UA,
        Accept: "image/*,*/*;q=0.8",
        Referer: new URL(url).origin + "/",
      },
      redirect: "follow",
    });
    if (!res.ok) return null;
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length < 200) return null;
    return buf;
  } catch {
    return null;
  }
}

async function fetchDirect(
  url: string,
  opts: {
    timeoutMs: number;
    referer?: string;
    cookie?: string;
    userAgent?: string;
    /** 带着 cf_clearance 试直连时失败：勿封 3 分钟直连（否则会逼所有请求重回慢速 FS） */
    hadClearance?: boolean;
  },
): Promise<{ html: string; finalUrl: string } | null> {
  try {
    const headers: Record<string, string> = {
      "User-Agent": opts.userAgent || UA,
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "ja,zh-CN;q=0.9,zh;q=0.8,en;q=0.7",
    };
    if (opts.referer) headers.Referer = opts.referer;
    if (opts.cookie) headers.Cookie = opts.cookie;
    const res = await undiciFetch(url, {
      signal: AbortSignal.timeout(opts.timeoutMs),
      headers,
      redirect: "follow",
    });
    if (!res.ok) {
      if (
        (res.status === 403 || res.status === 503) &&
        !opts.hadClearance
      ) {
        markDirectSkip(hostOf(url));
      }
      console.log(
        `[scrape] cookie-direct fail host=${hostOf(url)} HTTP ${res.status}`,
      );
      return null;
    }
    const buf = Buffer.from(await res.arrayBuffer());
    const html = decodeHtmlBytes(buf, res.headers.get("content-type"));
    if (looksBlockedHtml(html)) {
      if (!opts.hadClearance) markDirectSkip(hostOf(url));
      console.log(
        `[scrape] cookie-direct fail host=${hostOf(url)} blocked/challenge ${html.length}b`,
      );
      return null;
    }
    return { html, finalUrl: String(res.url || url) };
  } catch (e) {
    console.log(
      `[scrape] cookie-direct fail host=${hostOf(url)} ${e instanceof Error ? e.message : "err"}`,
    );
    return null;
  }
}

/** 按 Content-Type / meta charset 解码（カリビアンコム等为 EUC-JP） */
function decodeHtmlBytes(
  buf: Buffer,
  contentType: string | null | undefined,
): string {
  const ct = String(contentType || "");
  let charset =
    ct.match(/charset\s*=\s*["']?([^\s;"']+)/i)?.[1]?.trim() || "";
  if (!charset) {
    const head = buf.subarray(0, Math.min(buf.length, 8192)).toString("latin1");
    charset =
      head.match(
        /<meta[^>]+charset\s*=\s*["']?([^\s"'/>]+)/i,
      )?.[1]?.trim() ||
      head.match(
        /content=["'][^"']*charset\s*=\s*([^\s"';]+)/i,
      )?.[1]?.trim() ||
      "";
  }
  const key = charset.toLowerCase().replace(/_/g, "-");
  const enc =
    key === "euc-jp" || key === "eucjp" || key === "x-euc-jp"
      ? "euc-jp"
      : key === "shift-jis" ||
          key === "shiftjis" ||
          key === "sjis" ||
          key === "windows-31j" ||
          key === "cp932"
        ? "shift_jis"
        : key === "iso-2022-jp"
          ? "iso-2022-jp"
          : "utf-8";
  try {
    return new TextDecoder(enc).decode(buf);
  } catch {
    try {
      return buf.toString("utf8");
    } catch {
      return buf.toString("latin1");
    }
  }
}

export type FetchPageResult = { html: string; finalUrl: string };

/**
 * 抓取页面并带回最终落地 URL（用于识别镜像跳转）。
 * 同 host 串行：第一个请求完成并写入 clearance 后，后续才复用，避免并发同时过盾。
 */
export async function fetchPage(
  url: string,
  opts?: {
    timeoutMs?: number;
    referer?: string;
    cookie?: string;
    sourceId?: string;
    viaFlare?: boolean;
    strictTimeout?: boolean;
    /** SPA 站内跳转后等渲染（传给 FlareSolverr） */
    waitInSeconds?: number;
  },
): Promise<FetchPageResult | null> {
  const host = hostOf(url);
  return withHostGate(host, () => fetchPageUnlocked(url, opts));
}

async function fetchPageUnlocked(
  url: string,
  opts?: {
    timeoutMs?: number;
    referer?: string;
    cookie?: string;
    sourceId?: string;
    viaFlare?: boolean;
    strictTimeout?: boolean;
    waitInSeconds?: number;
  },
): Promise<FetchPageResult | null> {
  const timeoutMs = opts?.timeoutMs ?? 20000;
  const flareTimeoutMs = opts?.strictTimeout
    ? timeoutMs
    : Math.max(timeoutMs, 45000);
  const baseCookie =
    String(opts?.cookie || "").trim() || cookieForUrl(url, opts?.sourceId);
  const flareOn = Boolean(getFlareSolverrUrl()) && opts?.viaFlare !== false;
  const waitInSeconds = opts?.waitInSeconds;
  // 进闸后再读缓存：前面同站请求可能刚写好 cf_clearance / session
  const cached = getCachedClearance(url);
  const liveSession = flareOn && hasFlareSession(url);
  const cookie = mergeCookieHeaders(baseCookie, cached?.cookieHeader);
  const userAgent = cached?.userAgent || undefined;
  const host = hostOf(url);

  // viaFlare:true 仅表示「这站可能要过盾/渲染」，不再等于「永远跳过直连」。
  // 已有 cf_clearance → 一律先 Cookie 直连；只有无 clearance 时才首包直走 FS / 尊重直连冷却。
  // 重要：directSkip 只能在「还能走 Flare」时生效。iqqtv 等 viaFlare:false 的源若也跳过直连，
  // 会 0 次请求就返回 null（~百毫秒假「未找到详情页」），而连通性探测仍正常。
  const hasClearance = Boolean(cached?.cookieHeader);
  const skipDirectFirst =
    (flareOn && opts?.viaFlare === true && !hasClearance) ||
    (flareOn && shouldSkipDirect(host) && !hasClearance);

  if (!skipDirectFirst) {
    const directTimeout = hasClearance
      ? Math.max(timeoutMs, 12000)
      : getActiveProxy() && hostNeedsFlare(url)
        ? Math.max(timeoutMs, 15000)
        : liveSession
          ? Math.min(timeoutMs, 8000)
          : timeoutMs;
    const direct = await fetchDirect(url, {
      timeoutMs: directTimeout,
      referer: opts?.referer,
      cookie,
      userAgent,
      hadClearance: hasClearance,
    });
    // SPA 源要求 wait 时，直连结果太短/空壳则视为未渲染，回退 FS
    const minBytes = waitInSeconds && waitInSeconds > 0 ? 2000 : 500;
    if (direct && direct.html.length >= minBytes) {
      // 直连恢复：清掉该 host 的短时 skip，避免后续误伤
      directSkipUntil.delete(host);
      console.log(
        `[scrape] cookie-direct host=${host} ${direct.html.length}b proxy=${getActiveProxy() ? "on" : "off"} clearance=${hasClearance ? "yes" : "no"}`,
      );
      return direct;
    }
    if (direct && direct.html.length < minBytes) {
      console.log(
        `[scrape] cookie-direct thin host=${host} ${direct.html.length}b < ${minBytes} → flare`,
      );
    }
    // clearance 过期/失效：丢掉缓存，后面走 FS 重建，勿再盲信旧 Cookie
    if (hasClearance && !direct) {
      clearCachedClearance(url);
    }
  }

  if (
    flareOn &&
    (opts?.viaFlare === true ||
      hostNeedsFlare(url) ||
      hasClearance ||
      liveSession ||
      skipDirectFirst)
  ) {
    try {
      // 把 clearance 也带进 FS，session 重建时少打一轮挑战
      const hit = await fetchViaFlareSolverrFull(url, {
        timeoutMs: flareTimeoutMs,
        cookie: cookie || baseCookie || undefined,
        waitInSeconds,
      });
      if (hit.html && !looksBlockedHtml(hit.html)) {
        return {
          html: hit.html,
          finalUrl: hit.finalUrl || url,
        };
      }
    } catch {
      /* fall through */
    }
  } else if (flareOn) {
    try {
      const hit = await fetchViaFlareSolverrFull(url, {
        timeoutMs: flareTimeoutMs,
        cookie: cookie || baseCookie || undefined,
        waitInSeconds,
      });
      if (hit.html && !looksBlockedHtml(hit.html)) {
        return {
          html: hit.html,
          finalUrl: hit.finalUrl || url,
        };
      }
    } catch {
      /* ignore */
    }
  }
  return null;
}

export async function fetchText(
  url: string,
  opts?: {
    timeoutMs?: number;
    referer?: string;
    cookie?: string;
    sourceId?: string;
    /** true=强制走 FS；false=禁用；默认遇挑战再过盾 */
    viaFlare?: boolean;
    /** true=过盾也遵守 timeoutMs，不抬到 45s（连通性探测） */
    strictTimeout?: boolean;
    waitInSeconds?: number;
  },
): Promise<string | null> {
  const page = await fetchPage(url, opts);
  return page?.html || null;
}

/** JSON API（LibreDMM 等）；走全局代理，不过盾 */
export async function fetchJson(
  url: string,
  opts?: { timeoutMs?: number; referer?: string },
): Promise<unknown | null> {
  const timeoutMs = opts?.timeoutMs ?? 20000;
  try {
    const headers: Record<string, string> = {
      "User-Agent": UA,
      Accept: "application/json",
      "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    };
    if (opts?.referer) headers.Referer = opts.referer;
    const res = await undiciFetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      headers,
      redirect: "follow",
    });
    if (!res.ok && res.status !== 202) return null;
    const text = await res.text();
    if (!text) return null;
    const ct = String(res.headers.get("content-type") || "").toLowerCase();
    // JSON 短包（err=processing / not_found）勿当 CF 壳页丢掉
    if (!ct.includes("json") && looksBlockedHtml(text)) return null;
    if (ct.includes("html") || /^\s*</.test(text)) return null;
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

export async function fetchPostForm(
  url: string,
  body: string,
  opts?: {
    timeoutMs?: number;
    referer?: string;
    cookie?: string;
    sourceId?: string;
  },
): Promise<string | null> {
  const timeoutMs = opts?.timeoutMs ?? 15000;
  const cookie =
    String(opts?.cookie || "").trim() || cookieForUrl(url, opts?.sourceId);
  try {
    const headers: Record<string, string> = {
      "User-Agent": UA,
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "text/html",
      Referer: opts?.referer || new URL(url).origin + "/",
    };
    if (cookie) headers.Cookie = cookie;
    const res = await undiciFetch(url, {
      method: "POST",
      signal: AbortSignal.timeout(timeoutMs),
      headers,
      body,
      redirect: "follow",
    });
    if (!res.ok) return null;
    const html = await res.text();
    if (looksBlockedHtml(html)) return null;
    return html;
  } catch {
    return null;
  }
}

/** HEAD/range 探测图片是否可用（DMM 占位图过滤） */
export async function probeImageUrl(
  url: string,
  opts?: { timeoutMs?: number; referer?: string },
): Promise<{ ok: boolean; finalUrl: string; sizeHint: number }> {
  const timeoutMs = opts?.timeoutMs ?? 8000;
  try {
    const res = await undiciFetch(url, {
      method: "GET",
      signal: AbortSignal.timeout(timeoutMs),
      headers: {
        "User-Agent": UA,
        Referer: opts?.referer || new URL(url).origin + "/",
        Range: "bytes=0-2047",
      },
      redirect: "follow",
    });
    if (!res.ok && res.status !== 206) {
      return { ok: false, finalUrl: url, sizeHint: 0 };
    }
    const finalUrl = String(res.url || url);
    const cl = Number(res.headers.get("content-length") || 0);
    const rangeTotal = Number(
      (res.headers.get("content-range") || "").split("/")[1] || 0,
    );
    return { ok: true, finalUrl, sizeHint: rangeTotal || cl };
  } catch {
    return { ok: false, finalUrl: url, sizeHint: 0 };
  }
}
