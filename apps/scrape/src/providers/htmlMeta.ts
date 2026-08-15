import * as cheerio from "cheerio";
import { fetchPage, fetchText } from "../download.js";
import { looksBlockedHtml, registerFlareHost } from "../flaresolverr.js";
import {
  rememberSiteMirror,
  withSiteMirrorBase,
} from "../siteMirror.js";
import type { PartialFromSource } from "../sources.js";
import { isJunkCoverUrl, isJunkTitle, isLikelyChinese, stdCode } from "../util.js";

function stripTags(s: string): string {
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function absUrl(href: string | undefined, base: string): string | null {
  if (!href) return null;
  try {
    if (href.startsWith("//")) return `https:${href}`;
    return new URL(href, base).href;
  } catch {
    return null;
  }
}

function originOf(url: string | undefined | null): string {
  try {
    const u = new URL(String(url || "").trim());
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}

function pickOgTitle(html: string): string {
  const m =
    html.match(/property=["']og:title["']\s+content=["']([^"']+)["']/i) ||
    html.match(/content=["']([^"']+)["']\s+property=["']og:title["']/i);
  return m?.[1] ? stripTags(m[1]) : "";
}

function pickOgImage(html: string): string | null {
  const m =
    html.match(/property=["']og:image["']\s+content=["']([^"']+)["']/i) ||
    html.match(/content=["']([^"']+)["']\s+property=["']og:image["']/i);
  return m?.[1] || null;
}

function cleanTitle(raw: string | null | undefined, code: string): string {
  let t = stripTags(String(raw || ""));
  if (!t) return "";
  t = t.replace(new RegExp(`^${code}\\s*[-–—:]?\\s*`, "i"), "").trim() || t;
  return t;
}

function collectByRe(html: string, re: RegExp): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  const r = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  while ((m = r.exec(html)) !== null) {
    const n = stripTags(m[1] || "");
    if (!n || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

function pageMentionsCode(html: string, code: string): boolean {
  const c = code.replace(/-/g, "[-_]?");
  return new RegExp(c, "i").test(html.slice(0, 8000));
}

function codeKey(s: string): string {
  return String(s || "")
    .replace(/[-_\s]/g, "")
    .toUpperCase();
}

/** tellme.pw/jav 上的 avmoo / avsox 入口常变；短暂缓存可用镜像 */
let avmooBaseCache: { base: string; expiresAt: number } | null = null;
let avsoxBaseCache: { base: string; expiresAt: number } | null = null;
const AVMOO_TTL_MS = 6 * 60 * 60 * 1000;
const AVMOO_SEEDS = [
  "https://avmoo.shop",
  "https://www.avmoo.shop",
];
const AVSOX_SEEDS = [
  "https://avsox.click",
  "https://www.avsox.click",
];
const AVMOO_TELLME = "https://tellme.pw/jav";

function looksLikeAvFamily(html: string): boolean {
  if (!html || html.length < 800) return false;
  if (/Just a moment|cf-browser-verification/i.test(html.slice(0, 2500))) {
    return false;
  }
  return /\/cn\/movies\/|movie-card|识别码|識別碼|AVMOO|AVSOX|\/cn\/search\//i.test(
    html,
  );
}

/** Quasar 空壳：代理/curl 常见 ~1.5KB；有 movies 链则已渲染 */
function isAvSpaShell(html: string): boolean {
  if (!html) return true;
  if (/\/cn\/movies\/|movie-card|识别码|識別碼/i.test(html)) return false;
  return (
    html.length < 4000 ||
    /q-loading-bar|q-page-container/i.test(html)
  );
}

/**
 * avmoo/avsox 走 FlareSolverr 的原因：站点是 Quasar SPA，需要浏览器跑 JS。
 * 不是 Cloudflare 挑战页；等待秒数宜短，靠 session 复用而不是反复拉长 wait。
 */
const AV_SPA_WAIT_S = 2;
const AV_SPA_RETRY_WAIT_S = 3;

function extractAvmooMirrors(html: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const m of html.matchAll(/https?:\\\/\\\/(?:www\.)?avmoo\.[a-z0-9.-]+/gi)) {
    const raw = m[0].replace(/\\\//g, "/");
    const base = originOf(raw);
    if (!base || /tellme\.pw/i.test(base) || seen.has(base)) continue;
    seen.add(base);
    out.push(base);
  }
  for (const m of html.matchAll(/https?:\/\/(?:www\.)?avmoo\.[a-z0-9.-]+/gi)) {
    const base = originOf(m[0]);
    if (!base || /tellme\.pw/i.test(base) || seen.has(base)) continue;
    seen.add(base);
    out.push(base);
  }
  return out;
}

function extractAvsoxMirrors(html: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  // tellme JSON: "javu":"https:\/\/avsox.click"
  for (const m of html.matchAll(
    /https?:\\\/\\\/(?:www\.)?avsox\.[a-z0-9.-]+/gi,
  )) {
    const raw = m[0].replace(/\\\//g, "/");
    const base = originOf(raw);
    if (!base || seen.has(base)) continue;
    seen.add(base);
    out.push(base);
  }
  for (const m of html.matchAll(/https?:\/\/(?:www\.)?avsox\.[a-z0-9.-]+/gi)) {
    const base = originOf(m[0]);
    if (!base || seen.has(base)) continue;
    seen.add(base);
    out.push(base);
  }
  const javu = html.match(/"javu"\s*:\s*"([^"]+)"/i)?.[1];
  if (javu) {
    const base = originOf(javu.replace(/\\\//g, "/"));
    if (base && !seen.has(base)) {
      seen.add(base);
      out.push(base);
    }
  }
  return out;
}

async function resolveAvmooBase(preferred?: string): Promise<string> {
  const now = Date.now();
  if (avmooBaseCache && avmooBaseCache.expiresAt > now) {
    registerFlareHost(avmooBaseCache.base);
    return avmooBaseCache.base;
  }
  // 已知可用镜像：直接用，避免先打开 /cn 再搜导致 SPA 二次跳转空壳
  const pref = originOf(preferred) || String(preferred || "").replace(/\/$/, "");
  if (/avmoo\.shop$/i.test(pref.replace(/^https?:\/\//i, "").split("/")[0] || "")) {
    registerFlareHost(pref);
    avmooBaseCache = { base: pref, expiresAt: now + AVMOO_TTL_MS };
    return pref;
  }
  const seeds = [pref, ...AVMOO_SEEDS].filter(Boolean);
  const uniq = [...new Set(seeds)];
  const tryBase = async (base: string): Promise<string | null> => {
    const b = base.replace(/\/$/, "");
    if (!b || /tellme\.pw/i.test(b)) return null;
    // 仅未知镜像才探测；已知 avmoo.shop 已在上方短路，避免多余 Flare
    const page = await fetchPage(`${b}/cn/search/SONE-001`, {
      referer: `${b}/cn`,
      sourceId: "avmoo",
      timeoutMs: 28000,
      strictTimeout: true,
      viaFlare: true,
      // SPA 渲染等待（非 CF 过盾）
      waitInSeconds: AV_SPA_WAIT_S,
    });
    if (!page?.html) return null;
    const landed = originOf(page.finalUrl) || b;
    if (/tellme\.pw/i.test(landed)) {
      return null;
    }
    if (!looksLikeAvFamily(page.html) && !/\/cn\/movies\//i.test(page.html)) {
      return null;
    }
    registerFlareHost(landed);
    avmooBaseCache = { base: landed, expiresAt: now + AVMOO_TTL_MS };
    return landed;
  };

  for (const s of uniq) {
    if (/avmoo\.shop/i.test(s)) {
      const hit = originOf(s) || s;
      registerFlareHost(hit);
      avmooBaseCache = { base: hit, expiresAt: now + AVMOO_TTL_MS };
      return hit;
    }
  }

  for (const s of uniq) {
    const hit = await tryBase(s);
    if (hit) return hit;
  }

  const tellme = await fetchPage(AVMOO_TELLME, {
    sourceId: "avmoo",
    timeoutMs: 28000,
    strictTimeout: true,
    viaFlare: true,
  });
  if (tellme?.html) {
    for (const m of extractAvmooMirrors(tellme.html)) {
      if (/avmoo\.shop/i.test(m)) {
        registerFlareHost(m);
        avmooBaseCache = { base: m, expiresAt: now + AVMOO_TTL_MS };
        return m;
      }
      const hit = await tryBase(m);
      if (hit) return hit;
    }
  }

  const fallback =
    originOf(preferred) || AVMOO_SEEDS[0] || "https://avmoo.shop";
  registerFlareHost(fallback);
  return fallback;
}

async function resolveAvsoxBase(preferred?: string): Promise<string> {
  const now = Date.now();
  if (avsoxBaseCache && avsoxBaseCache.expiresAt > now) {
    registerFlareHost(avsoxBaseCache.base);
    return avsoxBaseCache.base;
  }
  const pref = originOf(preferred) || String(preferred || "").replace(/\/$/, "");
  if (/avsox\.click$/i.test(pref.replace(/^https?:\/\//i, "").split("/")[0] || "")) {
    registerFlareHost(pref);
    avsoxBaseCache = { base: pref, expiresAt: now + AVMOO_TTL_MS };
    return pref;
  }
  for (const s of [pref, ...AVSOX_SEEDS].filter(Boolean)) {
    if (/avsox\.click/i.test(s)) {
      const hit = originOf(s) || s;
      registerFlareHost(hit);
      avsoxBaseCache = { base: hit, expiresAt: now + AVMOO_TTL_MS };
      return hit;
    }
  }
  const tellme = await fetchPage(AVMOO_TELLME, {
    sourceId: "avsox",
    timeoutMs: 28000,
    strictTimeout: true,
    viaFlare: true,
  });
  if (tellme?.html) {
    for (const m of extractAvsoxMirrors(tellme.html)) {
      registerFlareHost(m);
      avsoxBaseCache = { base: m, expiresAt: now + AVMOO_TTL_MS };
      return m;
    }
  }
  const fallback =
    originOf(preferred) || AVSOX_SEEDS[0] || "https://avsox.click";
  registerFlareHost(fallback);
  return fallback;
}

function pickFamilyMoviePath(html: string, code: string, lang: string): string | null {
  const codeRe = new RegExp(code.replace(/-/g, "[-_]?"), "i");
  // 新站：movie-card → /cn/movies/xxx
  const movieBlocks = [
    ...html.matchAll(
      new RegExp(
        `href=["']([^"']*/${lang}/movies/[^"'#]+)["']([\\s\\S]{0,1000})`,
        "gi",
      ),
    ),
  ];
  for (const m of movieBlocks) {
    const href = String(m[1] || "").trim();
    const chunk = `${href} ${m[2] || ""}`;
    if (href && codeRe.test(chunk)) return href;
  }
  if (movieBlocks[0]?.[1]) return String(movieBlocks[0][1]).trim();

  // 旧站：/cn/movie/xxx
  const legacy =
    html.match(
      new RegExp(
        `href=["']([^"']*/${lang}/movie/[^"']+)["'][^>]*>[\\s\\S]{0,120}?${code.replace(/-/g, "[-]?")}`,
        "i",
      ),
    )?.[1] ||
    html.match(new RegExp(`href=["']([^"']*/${lang}/movie/[^"']+)["']`, "i"))?.[1];
  return legacy || null;
}

function familyDetailValue(html: string, label: string): string {
  const re = new RegExp(
    `${label}\\s*[:：]?\\s*</span>\\s*<(?:span|a)[^>]*>([\\s\\S]*?)</(?:span|a)>`,
    "i",
  );
  return stripTags(html.match(re)?.[1] || "");
}

function parseFamilyDetail(
  html: string,
  detailUrl: string,
  code: string,
  source: string,
): PartialFromSource | null {
  if (!html) return null;
  if (!pageMentionsCode(html, code) && !familyDetailValue(html, "识别码") && !familyDetailValue(html, "識別碼")) {
    return null;
  }
  const idSpan =
    familyDetailValue(html, "识别码") || familyDetailValue(html, "識別碼");
  if (idSpan && codeKey(idSpan) !== codeKey(code)) {
    return null;
  }

  let title = cleanTitle(
    html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ||
      pickOgTitle(html) ||
      html.match(/<h3[^>]*>([\s\S]*?)<\/h3>/i)?.[1],
    code,
  );
  if (isJunkTitle(title)) title = "";

  const actors = [
    ...collectByRe(
      html,
      /class=["'][^"']*actress-name[^"']*["'][^>]*>([^<]+)</gi,
    ),
    ...collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?actresses\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
    ...collectByRe(
      html,
      /href=["'][^"']*\/star\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
  ].filter((n) => n.length >= 1 && n.length <= 40);
  const uniqActors = [...new Set(actors)].slice(0, 20);

  const genres = [
    ...collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?genres\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
    ...collectByRe(
      html,
      /href=["'][^"']*\/genre\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
  ]
    .map((g) => g.trim())
    .filter((g) => g && !/更多|全部|类别|類別/i.test(g) && !isJunkTitle(g));
  const uniqGenres = [...new Set(genres)].slice(0, 40);

  let series =
    familyDetailValue(html, "系列") ||
    collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?series\/[^"']+["'][^>]*>([^<]+)</gi,
    )[0] ||
    "";
  if (series === "-" || series.length < 2 || isJunkTitle(series)) series = "";

  const studioRaw =
    familyDetailValue(html, "制作商") ||
    familyDetailValue(html, "製作商") ||
    collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?studios\/[^"']+["'][^>]*>([^<]+)</gi,
    )[0] ||
    "";
  const studio = studioRaw && studioRaw !== "-" ? studioRaw : "";
  const directorRaw =
    familyDetailValue(html, "导演") || familyDetailValue(html, "導演") || "";
  const director =
    directorRaw && directorRaw !== "-" ? directorRaw : undefined;
  const publisherRaw =
    familyDetailValue(html, "发行商") ||
    familyDetailValue(html, "發行商") ||
    "";
  const publisher =
    publisherRaw && publisherRaw !== "-" ? publisherRaw : undefined;
  const premiered = (
    familyDetailValue(html, "发行时间") ||
    familyDetailValue(html, "發行時間") ||
    ""
  ).slice(0, 10);
  const runtimeRaw =
    familyDetailValue(html, "长度") || familyDetailValue(html, "長度") || "";
  const runtime = Number(runtimeRaw.match(/(\d+)/)?.[1] || 0) || null;

  let cover =
    html.match(
      /(https?:\/\/[^"'>\s]+\/(?:digital\/video|pics_dig\/digital\/video)\/[^"'>\s]+pl\.(?:jpg|jpeg|png|webp))/i,
    )?.[1] ||
    html.match(
      /class=["'][^"']*poster-button[^"']*["'][\s\S]{0,1200}?src=["'](https?:\/\/[^"']+\.(?:jpg|jpeg|png|webp)[^"']*)["']/i,
    )?.[1] ||
    html.match(
      /src=["'](https?:\/\/[^"']+\/(?:player_thumbnail|l_l|l_thum|thumb_l)\.(?:jpg|jpeg|png|webp)[^"']*)["']/i,
    )?.[1] ||
    html.match(/class=["']bigImage["'][^>]*href=["']([^"']+)["']/i)?.[1] ||
    pickOgImage(html);
  if (cover) cover = absUrl(cover, detailUrl) || cover;
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart = [
    ...html.matchAll(
      /(https?:\/\/[^"'>\s]+\/digital\/video\/[^"'>\s]+-(?:\d+)\.(?:jpg|jpeg|png|webp))/gi,
    ),
    ...html.matchAll(
      /(https?:\/\/[^"'>\s]+\/(?:sample|images)\/[^"'>\s]+(?:jp)?-?\d+\.(?:jpg|jpeg|png|webp))/gi,
    ),
  ]
    .map((m) => m[1]!)
    .filter(
      (u) =>
        u &&
        !isJunkCoverUrl(u) &&
        !/avatar|player_thumbnail|thumbnail\.jpg|thum_b|list1/i.test(u),
    );
  const uniqFanart = [...new Set(fanart)].filter((u) => u !== cover).slice(0, 30);

  const productId =
    cover?.match(
      /(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp|jp\.netcdn\.space)\/(?:pics_dig\/)?digital\/video\/([a-z0-9]+)\//i,
    )?.[1] || undefined;

  if (!title && !cover && !uniqActors.length && !uniqGenres.length && !series) {
    return null;
  }

  const titleZh = title && isLikelyChinese(title) ? title : "";
  return {
    code,
    title: title || "",
    titleZh: titleZh || undefined,
    originalTitle: title || "",
    actors: uniqActors,
    genres: uniqGenres,
    series: series || undefined,
    studio: studio || undefined,
    publisher: publisher || undefined,
    makers: studio ? [studio] : [],
    director: director || undefined,
    premiered: premiered || undefined,
    runtime,
    poster: cover,
    fanart: uniqFanart.length ? uniqFanart : undefined,
    productId,
    source,
  };
}

/**
 * AVSOX / AVMOO（新站 /cn/movies + Quasar 详情；兼容旧 /cn/movie）。
 *
 * 访问说明（重要）：
 * - 代理能连上，但正文在前端 JS 里渲染；curl/undici 只有 ~1.5KB 壳。
 * - FlareSolverr 在这里是「浏览器渲染」，不是 Cloudflare 挑战过盾。
 * - 策略：首包带短 wait；空壳最多再补一枪；详情同理。避免 4～6 次长 wait 串行占锁。
 */
export async function scrapeAvsoxFamily(
  codeRaw: string,
  opts: { baseUrl: string; source: string; langPath?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  const lang = opts.langPath || "cn";
  let base = String(opts.baseUrl || "").replace(/\/$/, "");
  if (opts.source === "avmoo") {
    base = await resolveAvmooBase(base || AVMOO_SEEDS[0]);
  } else if (opts.source === "avsox") {
    base = await resolveAvsoxBase(base || AVSOX_SEEDS[0]);
  }
  if (!base) return null;
  registerFlareHost(base);
  if (opts.source === "avmoo" || opts.source === "avsox") {
    rememberSiteMirror(opts.source, base, opts.baseUrl);
  }

  const searchUrl = `${base}/${lang}/search/${encodeURIComponent(code)}`;
  const flareSearch = (url: string, wait: number, timeoutMs = 35000) =>
    fetchPage(url, {
      referer: `${base}/${lang}`,
      sourceId: opts.source,
      timeoutMs,
      viaFlare: true,
      waitInSeconds: wait,
    });

  // 1) 搜索：首包直接短 wait（省掉「空手 + 再打」的双倍排队）
  let searchPage = await flareSearch(searchUrl, AV_SPA_WAIT_S);
  if (
    searchPage?.html &&
    !pickFamilyMoviePath(searchPage.html, code, lang) &&
    isAvSpaShell(searchPage.html)
  ) {
    searchPage = await flareSearch(searchUrl, AV_SPA_RETRY_WAIT_S, 40000);
  }
  if (!searchPage?.html) return null;
  let searchHtml = searchPage.html;
  let searchFinal = searchPage.finalUrl || searchUrl;

  // 入口跳到 tellme 导航页：清缓存跟镜像后再搜一枪
  if (
    (opts.source === "avmoo" || opts.source === "avsox") &&
    (/tellme\.pw/i.test(searchFinal) ||
      /tellme\.pw/i.test(searchHtml.slice(0, 800)))
  ) {
    if (opts.source === "avmoo") {
      avmooBaseCache = null;
      base = await resolveAvmooBase(base);
    } else {
      avsoxBaseCache = null;
      base = await resolveAvsoxBase(base);
    }
    const againUrl = `${base}/${lang}/search/${encodeURIComponent(code)}`;
    const again = await flareSearch(againUrl, AV_SPA_RETRY_WAIT_S, 40000);
    if (!again?.html) return null;
    searchHtml = again.html;
    searchFinal = again.finalUrl || againUrl;
  }

  const moviePath = pickFamilyMoviePath(searchHtml, code, lang);
  if (!moviePath) return null;

  const detailUrl = absUrl(moviePath, base);
  if (!detailUrl) return null;

  // 2) 详情：同 session 短 wait；缺 h1/识别码再补等一轮
  let detailPage = await fetchPage(detailUrl, {
    referer: searchUrl,
    sourceId: opts.source,
    timeoutMs: 35000,
    viaFlare: true,
    waitInSeconds: AV_SPA_WAIT_S,
  });
  if (
    detailPage?.html &&
    !/<h1[\s>]/i.test(detailPage.html) &&
    !/识别码|識別碼|actress-name|detail-value/i.test(detailPage.html)
  ) {
    detailPage = await fetchPage(detailUrl, {
      referer: searchUrl,
      sourceId: opts.source,
      timeoutMs: 40000,
      viaFlare: true,
      waitInSeconds: AV_SPA_RETRY_WAIT_S,
    });
  }
  if (!detailPage?.html) return null;
  return parseFamilyDetail(
    detailPage.html,
    detailPage.finalUrl || detailUrl,
    code,
    opts.source,
  );
}

export async function scrapeJavdb(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "javdb",
    opts?.baseUrl || "https://javdb.com",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);

  // locale=zh：UI/标签偏中文；片名多为日文。需 Flare；出口被站方封 IP 时整站空返回
  const searchUrl = `${base}/search?q=${encodeURIComponent(code)}&f=all&locale=zh`;
  const searchPage = await fetchPage(searchUrl, {
    referer: `${base}/`,
    sourceId: "javdb",
    viaFlare: true,
    waitInSeconds: 4,
    timeoutMs: 60000,
  });
  const search = searchPage?.html || null;
  if (!search) return null;
  if (/banned your access|禁止了你的訪問|異常行為/i.test(search)) return null;

  const $s = cheerio.load(search);
  const want = codeKey(code);
  let detailPath = "";
  $s(".movie-list .item a.box, #videos a.box, a.box[href*='/v/']").each((_, el) => {
    if (detailPath) return;
    const href = String($s(el).attr("href") || "");
    if (!/\/v\//i.test(href)) return;
    const uid = stripTags(
      $s(el).find(".uid, .video-title strong, .id").first().text() ||
        $s(el).find(".video-title").first().text(),
    );
    const uidKey = codeKey(uid.split(/\s+/)[0] || uid);
    const titleText = stripTags($s(el).find(".video-title").text() || $s(el).text());
    if (uidKey === want || codeKey(titleText).startsWith(want)) {
      detailPath = href;
    }
  });
  if (!detailPath) {
    // 回退：带番号的首个 /v/ 链接
    detailPath =
      search.match(
        new RegExp(
          `href=["'](/v/[^"']+)["'][^>]*>[\\s\\S]{0,400}?${code.replace(/-/g, "[-]?")}`,
          "i",
        ),
      )?.[1] ||
      "";
  }
  if (!detailPath) return null;

  const detailUrl = absUrl(detailPath, searchPage?.finalUrl || base);
  if (!detailUrl) return null;
  const detailPage = await fetchPage(detailUrl, {
    referer: searchUrl,
    sourceId: "javdb",
    viaFlare: true,
    waitInSeconds: 3,
    timeoutMs: 60000,
  });
  const html = detailPage?.html || null;
  const landed = detailPage?.finalUrl || detailUrl;
  if (!html || /banned your access|禁止了你的訪問/i.test(html)) return null;
  if (!pageMentionsCode(html, code)) return null;

  const $ = cheerio.load(html);
  let title = cleanTitle(
    $("strong.current-title").first().text() ||
      $("h2.title strong").first().text() ||
      pickOgTitle(html) ||
      $("title").first().text().replace(/\s*\|\s*JavDB.*$/i, ""),
    code,
  );
  title = title
    .replace(/\s*[|｜].*$/, "")
    .replace(/\s*(中文字幕|无码流出|無碼流出)\s*$/i, "")
    .trim();
  if (isJunkTitle(title)) title = "";

  const panelValue = (label: RegExp): { text: string; links: string[] } => {
    let text = "";
    const links: string[] = [];
    $(".movie-panel-info .panel-block, .panel-block").each((_, el) => {
      const lab = stripTags($(el).find("strong").first().text());
      if (!label.test(lab)) return;
      const $val = $(el).find("span.value").first();
      $val.find("a").each((__, a) => {
        const n = stripTags($(a).text());
        if (n && n.length < 60 && !links.includes(n)) links.push(n);
      });
      text = stripTags($val.text() || $(el).text().replace(lab, ""));
    });
    return { text, links };
  };

  const actors: string[] = [];
  const hasFemaleMarks = $("a[href*='/actors/'] + strong.female").length > 0;
  $("a[href*='/actors/']").each((_, el) => {
    const $a = $(el);
    const n = stripTags($a.text());
    if (!n || n.length < 2 || n.length > 40 || actors.includes(n)) return;
    const $next = $a.next("strong");
    if ($next.hasClass("male") && !$next.hasClass("female")) return;
    if (hasFemaleMarks && !$next.hasClass("female")) return;
    actors.push(n);
  });
  if (!actors.length) {
    const actorPanel = panelValue(/演員|演员|Actor/);
    for (const n of actorPanel.links) {
      if (n.length >= 2 && n.length <= 40 && !actors.includes(n)) actors.push(n);
    }
  }

  let cover =
    absUrl($("img.video-cover").attr("src"), landed) ||
    absUrl($(".column-video-cover img").attr("src"), landed) ||
    pickOgImage(html);
  if (cover) cover = absUrl(cover, landed);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart: string[] = [];
  $(".tile-images .tile-item img, .preview-images img").each((_, el) => {
    const u =
      absUrl($(el).attr("data-src") || $(el).attr("src"), landed) ||
      absUrl($(el).parent("a").attr("href"), landed);
    if (u && !isJunkCoverUrl(u) && !fanart.includes(u) && u !== cover) {
      fanart.push(u);
    }
  });

  const datePanel = panelValue(/日期|Released Date|発売日/);
  let premiered = "";
  const dm = datePanel.text.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const runtimeRaw = panelValue(/時長|时长|Duration|収録時間/).text;
  const runtime = Number(runtimeRaw.match(/(\d+)/)?.[1] || 0) || null;
  const director =
    panelValue(/導演|导演|Director|監督/).links[0] ||
    panelValue(/導演|导演|Director|監督/).text ||
    "";
  const publisher =
    panelValue(/發行|发行|Publisher|レーベル/).links[0] ||
    panelValue(/發行|发行|Publisher|レーベル/).text ||
    "";
  const maker =
    panelValue(/片商|Maker|制作|製作|メーカー/).links[0] ||
    panelValue(/片商|Maker|制作|製作|メーカー/).text ||
    "";
  const series =
    panelValue(/系列|Series|シリーズ/).links[0] ||
    panelValue(/系列|Series|シリーズ/).text ||
    "";

  const tagPanel = panelValue(/類別|类别|Tags|タグ|标签/);
  const genres = [
    ...tagPanel.links,
    ...collectByRe(html, /href=["'][^"']*\/tags\?[^"']*["'][^>]*>([^<]+)</gi),
  ]
    .map((n) => n.trim())
    .filter((n) => n && n.length < 40)
    .filter((n, i, a) => a.indexOf(n) === i)
    .slice(0, 40);

  let plot = stripTags(
    $("meta[property='og:description']").attr("content") ||
      html.match(
        /property=["']og:description["']\s+content=["']([^"']+)["']/i,
      )?.[1] ||
      "",
  );
  if (plot.length < 12 || isJunkTitle(plot) || plot === title) plot = "";

  // 评分常见「4.xx分」（5 分制）→ 映射 0–10
  const scoreRaw =
    stripTags($(".score-stars, .score").first().text()) ||
    html.match(/(\d(?:\.\d)?)\s*分/)?.[1] ||
    "";
  let userRating: number | null =
    Number(String(scoreRaw).match(/(\d(?:\.\d)?)/)?.[1] || 0) || null;
  if (userRating && userRating > 0 && userRating <= 5) userRating *= 2;
  if (userRating && (userRating <= 0 || userRating > 10)) userRating = null;

  const productId =
    cover?.match(
      /(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp|jp\.netcdn\.space|jdbstatic)\/(?:pics_dig\/)?digital\/video\/([a-z0-9_]+)\//i,
    )?.[1] || undefined;

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    plot: plot || undefined,
    actors: actors.slice(0, 20),
    genres: genres.length ? genres : undefined,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    director: director || undefined,
    studio: maker || undefined,
    publisher: publisher || undefined,
    makers: maker ? [maker] : undefined,
    series: series || undefined,
    userRating,
    poster: cover,
    fanart: fanart.slice(0, 30),
    productId,
    source: "javdb",
  };
    },
  );
}

/**
 * MGS 官方（mgstage.com）。年龄门 Cookie `adc=1`（domain=.mgstage.com）。
 * 直达 /product/product_detail/{CODE}/；强制 Flare。全日文字段。
 */
export async function scrapeMgstage(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "mgstage",
    opts?.baseUrl || "https://www.mgstage.com",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);

  const detailUrls = [
    `${base}/product/product_detail/${encodeURIComponent(code)}/`,
    `${base}/product/product_detail/${encodeURIComponent(code.toLowerCase())}/`,
  ];

  let html: string | null = null;
  let landed = "";
  for (const url of detailUrls) {
    const page = await fetchPage(url, {
      referer: `${base}/`,
      sourceId: "mgstage",
      viaFlare: true,
      waitInSeconds: 2,
      timeoutMs: 60000,
    });
    const h = page?.html || "";
    if (!h || looksBlockedHtml(h)) continue;
    if (/成人認証|年齢認証|Age Verification/i.test(h.slice(0, 2500))) continue;
    if (/お探しのページ|404|Not Found/i.test(h.slice(0, 1500)) && !/og:title/i.test(h)) {
      continue;
    }
    html = h;
    landed = page?.finalUrl || url;
    break;
  }
  if (!html) return null;

  const $ = cheerio.load(html);
  if (/成人認証/i.test($("title").text())) return null;

  const panel = (label: RegExp): string => {
    let out = "";
    $("table th, .detail_data th, dl dt").each((_, el) => {
      const lab = stripTags($(el).text());
      if (!label.test(lab)) return;
      const $n = $(el).next();
      out = stripTags($n.text()) || out;
    });
    return out;
  };

  const productCode = stdCode(panel(/品番/) || "");
  if (productCode && codeKey(productCode) !== codeKey(code)) return null;
  if (!productCode && !pageMentionsCode(html, code)) return null;

  let title = cleanTitle(
    $("h1").first().text() || pickOgTitle(html) || $("title").first().text(),
    code,
  );
  title = title
    .replace(/\s*[-|｜]\s*MGS.*$/i, "")
    .replace(/^「「/, "「")
    .trim();
  if (
    !title ||
    isJunkTitle(title) ||
    /成人認証|アダルト動画サイト|^エロ動画|^アダルトビデオ/i.test(title) ||
    title.length < 8
  ) {
    return null;
  }

  const actressRaw = panel(/出演/);
  const actors = actressRaw
    .split(/[,，、\/|]/)
    .map((s) =>
      stripTags(s)
        .replace(/\s*\d{2}\s*歳.*$/u, "")
        .replace(/\s*(OL|学生|人妻|主婦).*$/u, "")
        .trim(),
    )
    .filter((n) => n && n.length >= 1 && n.length <= 40 && !/新人女優|女優一覧/i.test(n));

  // 链接触女優优先
  const linked = $(
    "a[href*='/search/cSearch.php'][href*='actress'], a[href*='c_actress'], a[href*='/actress/']",
  )
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length <= 40 && !/新人|一覧|女優/i.test(n));
  const uniqActors = [...new Set([...linked, ...actors])].slice(0, 12);

  const studio = panel(/メーカー/) || undefined;
  const label = panel(/レーベル/) || undefined;
  const series = panel(/シリーズ/) || undefined;
  const genreRaw = panel(/ジャンル/);
  const genres = genreRaw
    .split(/\s+/)
    .map((s) => stripTags(s))
    .filter(
      (g) =>
        g &&
        g.length >= 2 &&
        g.length <= 30 &&
        !/独占配信|配信専用|フルハイビジョン|FHD|対応/i.test(g),
    );

  const runtimeRaw = panel(/収録時間/);
  const runtime =
    Number(runtimeRaw.match(/(\d+)\s*min/i)?.[1] || runtimeRaw.match(/(\d+)/)?.[1] || 0) ||
    null;

  let premiered = "";
  const dateRaw = panel(/配信開始日|商品発売日|発売日/);
  const dm = dateRaw.match(/(\d{4})\D(\d{1,2})\D(\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  let plot = stripTags(
    $(".detail_txt, #introduction, .introduction").first().text() || "",
  );
  plot = plot.replace(/^商品紹介\s*/i, "").trim();
  if (plot.length < 20 || isJunkTitle(plot) || plot === title) plot = "";

  let cover = pickOgImage(html);
  // 优先大图 pb_e_ → 可保留；部分条目有 package
  const pkg =
    html.match(
      /https?:\/\/image\.mgstage\.com\/images\/[^"'>\s]+(?:pb_e_|pac_e_)[^"'>\s]+\.jpg/i,
    )?.[0] ||
    html.match(/https?:\/\/image\.mgstage\.com\/images\/[^"'>\s]+\.jpg/i)?.[0];
  if (pkg) cover = pkg;
  if (cover) cover = absUrl(cover, landed || base);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const ratingRaw = panel(/評価/);
  const rating = Number(ratingRaw.match(/(\d+(?:\.\d+)?)/)?.[1] || 0) || null;

  return {
    code,
    title,
    originalTitle: title,
    plot: plot || undefined,
    actors: uniqActors.length ? uniqActors : undefined,
    studio,
    makers: studio ? [studio] : undefined,
    publisher: label || undefined,
    series: series || undefined,
    genres: genres.length ? genres.slice(0, 20) : undefined,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    userRating: rating && rating > 0 ? rating : undefined,
    poster: cover,
    source: "mgstage",
  };
    },
  );
}

/** javten：打开 .com 后 CF 常 302 到 /en（或 /cn）；跟语言前缀再搜。 */
function javtenLangFromUrl(url: string): string | null {
  const m = String(url || "").match(
    /javten\.com\/(en|cn|ja|tw|ko)(?:\/|$|\?)/i,
  );
  return m ? m[1]!.toLowerCase() : null;
}

export async function scrapeFc2Hub(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  const m = code.match(/FC2[-_]?PPV[-_]?(\d+)/i) || code.match(/FC2[-_]?(\d+)/i);
  if (!m) return null;
  const id = m[1]!;
  const displayCode = `FC2-PPV-${id}`;
  return withSiteMirrorBase(
    "fc2_hub",
    opts?.baseUrl || "https://javten.com",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);

  // 对齐手机：CF 后常落 /en。不先单独打首页（Flare 多一枪极易拖死）；
  // 直接优先 /en/search，referer 用 /en；失败再 cn / 无前缀。
  const searchUrls = [
    `${base}/en/search?kw=${encodeURIComponent(id)}`,
    `${base}/cn/search?kw=${encodeURIComponent(id)}`,
    `${base}/search?kw=${encodeURIComponent(id)}`,
  ];
  const homeReferer = `${base}/en`;

  let detailUrl: string | null = null;
  let html: string | null = null;

  for (const searchUrl of searchUrls) {
    const searchPage = await fetchPage(searchUrl, {
      referer: homeReferer,
      sourceId: "fc2_hub",
      viaFlare: true,
      waitInSeconds: 3,
      timeoutMs: 40000,
      strictTimeout: true,
    });
    if (!searchPage?.html) continue;
    if (
      /Edge IP Restricted|Just a moment|cf-browser-verification|Access Denied|banned your access|禁止了你的訪問/i.test(
        searchPage.html,
      )
    ) {
      continue;
    }

    // MetaTube：搜索常 302 到 /video/{vid}/id{number}/；fetch 跟随后 finalUrl 即详情
    const landed = searchPage.finalUrl || "";
    const landedLang = javtenLangFromUrl(landed);
    if (landedLang === "tw" || landedLang === "ko") {
      continue;
    }
    if (new RegExp(`/video/\\d+/id${id}\\b`, "i").test(landed)) {
      detailUrl = landed;
      html = searchPage.html;
      break;
    }

    const hrefs = [
      ...searchPage.html.matchAll(
        new RegExp(`(?:href|content)=["']([^"']*id${id}[^"']*)["']`, "gi"),
      ),
    ].map((x) => x[1]!);
    const href =
      hrefs.find((h) => /\/video\/\d+\/id/i.test(h) && !/\/(tw|ko)\//i.test(h)) ||
      hrefs.find((h) => !/\/(tw|ko)\//i.test(h)) ||
      hrefs[0] ||
      searchPage.html.match(
        new RegExp(`href=["']([^"']*(?:id)?${id}[^"']*)["']`, "i"),
      )?.[1];
    if (!href) continue;
    detailUrl = absUrl(href, base);
    if (!detailUrl) continue;

    if (
      detailUrl === searchPage.finalUrl ||
      new RegExp(`/video/\\d+/id${id}\\b`, "i").test(searchPage.finalUrl || "")
    ) {
      html = searchPage.html;
      break;
    }

    const detailPage = await fetchPage(detailUrl, {
      referer: searchUrl,
      sourceId: "fc2_hub",
      viaFlare: true,
      waitInSeconds: 3,
      timeoutMs: 40000,
      strictTimeout: true,
    });
    if (!detailPage?.html) continue;
    if (
      /Edge IP Restricted|Just a moment|cf-browser-verification|banned your access|禁止了你的訪問/i.test(
        detailPage.html,
      )
    ) {
      continue;
    }
    html = detailPage.html;
    detailUrl = detailPage.finalUrl || detailUrl;
    break;
  }

  if (!html || !detailUrl) return null;

  // JSON-LD Movie（MetaTube 主路径）
  let ldTitle = "";
  let ldPlot = "";
  let ldCover = "";
  let ldDate = "";
  let ldRuntime: number | null = null;
  let ldMaker = "";
  const ldGenres: string[] = [];
  const ldActors: string[] = [];
  for (const block of html.matchAll(
    /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi,
  )) {
    try {
      const data = JSON.parse(block[1] || "");
      const items = Array.isArray(data) ? data : [data];
      for (const item of items) {
        if (!item || typeof item !== "object") continue;
        const t = String(item["@type"] || "");
        if (t === "Movie" || t === "VideoObject" || t === "Product") {
          ldTitle = String(item.name || ldTitle || "").trim();
          ldPlot = String(item.description || ldPlot || "").trim();
          ldCover = String(item.image || ldCover || "").trim();
          ldDate = String(item.datePublished || ldDate || "").trim();
          const dur = String(item.duration || "");
          const mins = dur.match(/PT(?:(\d+)H)?(?:(\d+)M)?/i);
          if (mins) {
            ldRuntime =
              Number(mins[1] || 0) * 60 + Number(mins[2] || 0) || ldRuntime;
          }
          if (item.director) ldMaker = String(item.director).trim() || ldMaker;
          if (Array.isArray(item.genre)) {
            for (const g of item.genre) {
              const n = String(g || "").trim();
              if (n && !ldGenres.includes(n)) ldGenres.push(n);
            }
          }
          if (Array.isArray(item.actor)) {
            for (const a of item.actor) {
              const n = String(a || "").trim();
              if (n && !ldActors.includes(n)) ldActors.push(n);
            }
          }
        }
      }
    } catch {
      /* ignore bad ld+json */
    }
  }

  const h1s = [...html.matchAll(/<h1[^>]*>([\s\S]*?)<\/h1>/gi)].map((x) =>
    stripTags(x[1] || ""),
  );
  const h1Title =
    h1s.length >= 2
      ? h1s[1]!
      : h1s.find((t) => t && !/^FC2/i.test(t)) || h1s[0] || "";
  let title = cleanTitle(ldTitle || h1Title || pickOgTitle(html), displayCode);
  title = cleanTitle(title, code)
    .replace(new RegExp(`^FC2[-_]?PPV[-_]?${id}\\s*[-–—:]?\\s*`, "i"), "")
    .trim();
  if (!title || isJunkTitle(title)) return null;

  let cover =
    ldCover ||
    html.match(
      /<a[^>]+data-fancybox=["']gallery["'][^>]+href=["']([^"']+)["']/i,
    )?.[1] ||
    html.match(
      /href=["']([^"']+)["'][^>]+data-fancybox=["']gallery["']/i,
    )?.[1] ||
    pickOgImage(html);
  if (cover) cover = absUrl(cover, detailUrl);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const genres = [...ldGenres];
  for (const g of html.matchAll(
    /href=["'][^"']*(?:tag|genre)[^"']*["'][^>]*>([^<]{1,40})/gi,
  )) {
    const n = stripTags(g[1] || "");
    if (!n || /もっと|タグ|ジャンル|FC2/i.test(n) || genres.includes(n)) continue;
    genres.push(n);
  }

  let plot = stripTags(ldPlot || "");
  if (plot.length < 12 || isJunkTitle(plot)) plot = "";

  let premiered = "";
  const dm = ldDate.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const studio = ldMaker || undefined;

  return {
    code: displayCode,
    title,
    originalTitle: title,
    plot: plot || undefined,
    genres: genres.slice(0, 40),
    actors: ldActors.slice(0, 20),
    studio,
    makers: studio ? [studio] : undefined,
    premiered: premiered || undefined,
    runtime: ldRuntime && ldRuntime > 0 ? ldRuntime : undefined,
    poster: cover,
    productId: id,
    source: "fc2_hub",
  };
    },
  );
}

async function scrapeByPaths(
  codeRaw: string,
  opts: { baseUrl: string; source: string; paths: string[] },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  const base = opts.baseUrl.replace(/\/$/, "");
  const slug = code.toLowerCase().replace(/_/g, "-");
  for (const p of opts.paths) {
    const path = p
      .replace(/\{code\}/gi, encodeURIComponent(code))
      .replace(/\{slug\}/gi, encodeURIComponent(slug));
    const url = path.startsWith("http") ? path : `${base}${path.startsWith("/") ? "" : "/"}${path}`;
    const html = await fetchText(url);
    if (!html || html.length < 400) continue;
    if (/404|not found|找不到/i.test(html.slice(0, 1500)) && !/og:title/i.test(html)) {
      continue;
    }
    const title = cleanTitle(pickOgTitle(html), code);
    if (!title) continue;
    let cover = pickOgImage(html);
    if (cover) cover = absUrl(cover, url);
    return {
      code,
      title,
      originalTitle: title,
      poster: cover,
      source: opts.source,
    };
  }
  return null;
}

/** 国产站标签里常混女优名与类别；类别/玩法词走 genres，剩余短中文名尝试作女优 */
const MADOU_GENRE_WORDS = new Set(
  [
    "口交",
    "后入",
    "骑乘位",
    "女上位",
    "白虎",
    "少妇",
    "巨乳",
    "美乳",
    "美臀",
    "黑丝",
    "丝袜",
    "调教",
    "自拍",
    "出轨",
    "人妻",
    "学生",
    "制服",
    "创意",
    "内射",
    "颜射",
    "中出",
    "无套",
    "潮吹",
    "开裆",
    "多P",
    "3P",
    "剧情",
    "无码",
    "有码",
    "强奸",
    "痴女",
    "主观",
    "按摩",
    "车震",
    "足交",
    "肛交",
    "群交",
    "露出",
    "偷拍",
    "约炮",
    "69",
    "ol",
    "女销售",
    "护士",
    "老师",
    "空姐",
    "女仆",
    "泡泡浴",
    "口交",
    "深喉",
    "乳交",
    "自慰",
    "高潮",
    "痉挛",
    "捆绑",
    "眼罩",
    "道具",
  ].map((s) => s.toLowerCase()),
);

function madouCompactCode(code: string): string {
  return String(code || "").replace(/-/g, "").toUpperCase();
}

/** 保留前导零（MD-0362）；勿用 stdCode（会把 0362 收成 362） */
function madouStdCode(codeRaw: string): string {
  const s = String(codeRaw || "")
    .trim()
    .toUpperCase()
    .replace(/_/g, "-");
  if (!s) return "";
  if (!s.includes("-")) {
    const m = s.match(/^([A-Z]{1,12})(\d{2,}[A-Z0-9-]*)$/);
    if (m) return `${m[1]}-${m[2]}`;
    return s;
  }
  return s;
}

function madouPageHasCode(html: string, code: string): boolean {
  const compact = madouCompactCode(code);
  if (new RegExp(compact, "i").test(html.slice(0, 12000))) return true;
  const loose = code.replace(/-/g, "[-_]?");
  return new RegExp(loose, "i").test(html.slice(0, 12000));
}

function parseMadouDetail(
  html: string,
  detailUrl: string,
  code: string,
): PartialFromSource | null {
  const $ = cheerio.load(html);
  const compact = madouCompactCode(code);
  let title = cleanTitle(
    $(".article-title, h1.article-title, h1").first().text() ||
      $("title").first().text().replace(/\s*[-|｜].*麻豆.*$/i, ""),
    code,
  );
  title = title
    .replace(new RegExp(`^${compact}\\s+`, "i"), "")
    .replace(new RegExp(`^${code}\\s+`, "i"), "")
    .replace(/\s*[-|｜]\s*麻豆社?\s*$/i, "")
    .trim();
  if (isJunkTitle(title)) title = "";

  const studio =
    stripTags(
      $(".article-meta a[rel='category tag'], a[rel='category tag']")
        .first()
        .text(),
    ) || undefined;

  const tags = $("a[rel='tag'], .article-tags a")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length < 40);

  const actors: string[] = [];
  const genres: string[] = [];
  for (const t of tags) {
    const key = t.toLowerCase();
    const asGenre =
      MADOU_GENRE_WORDS.has(key) ||
      /[a-z0-9]/i.test(t) ||
      t.length > 3 ||
      /丝|交|入|抽|插|震|臀|乳|潮|射|码|P$/i.test(t);
    if (asGenre) {
      if (!genres.includes(t)) genres.push(t);
      continue;
    }
    // 2–3 汉字且不像玩法词 → 女优候选
    if (/^[\u4e00-\u9fff]{2,3}$/.test(t)) {
      if (!actors.includes(t)) actors.push(t);
    } else if (!genres.includes(t)) {
      genres.push(t);
    }
  }

  // 封面：优先 /covers/ 全尺寸，排除 -240x180 缩略图
  const coverCands: string[] = [];
  const pushCover = (raw: string | undefined | null) => {
    const u = absUrl(String(raw || "").trim(), detailUrl);
    if (!u || !/\/covers\//i.test(u)) return;
    if (/avatar|logo|icon|emoji/i.test(u)) return;
    coverCands.push(u);
  };
  $("img").each((_, el) => {
    pushCover($(el).attr("data-src"));
    pushCover($(el).attr("src"));
  });
  for (const m of html.matchAll(
    /https?:\/\/[^"'>\s]+\/covers\/[^"'>\s]+\.(?:jpe?g|png|webp)/gi,
  )) {
    pushCover(m[0]);
  }
  const full = coverCands.find((u) => !/-\d+x\d+\./i.test(u));
  let cover: string | null =
    full || coverCands.find((u) => !/thumb/i.test(u)) || coverCands[0] || null;
  if (cover && isJunkCoverUrl(cover)) cover = null;

  if (!title && !cover) return null;
  if (
    !madouPageHasCode(html, code) &&
    !new RegExp(compact, "i").test(detailUrl) &&
    !new RegExp(compact, "i").test(title)
  ) {
    return null;
  }

  return {
    code,
    title: title || "",
    titleZh: title && isLikelyChinese(title) ? title : undefined,
    originalTitle: title || "",
    actors: actors.slice(0, 20),
    genres: genres.length ? genres.slice(0, 40) : undefined,
    studio,
    makers: studio ? [studio] : undefined,
    poster: cover,
    source: "madou",
  };
}

export async function scrapeMadou(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  // 麻豆番号常 4 位前导零；stdCode 会吞零，这里单独规范化
  const code = madouStdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "madou",
    opts?.baseUrl || "https://madou.club",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);

  // 站内搜索对「MD-0362」常 0 命中，无连字符「MD0362」才有结果
  const compact = madouCompactCode(code);
  const queries = [...new Set([compact, code])].filter(Boolean);

  for (const q of queries) {
    const searchUrl = `${base}/?s=${encodeURIComponent(q)}`;
    const searchPage = await fetchPage(searchUrl, {
      referer: `${base}/`,
      sourceId: "madou",
      timeoutMs: 25000,
    });
    const search = searchPage?.html || null;
    if (!search || search.length < 400) continue;
    if (
      /没有找到|未找到|Nothing Found|抱歉.*没有/i.test(search) &&
      !madouPageHasCode(search, code) &&
      !new RegExp(compact, "i").test(search.slice(0, 8000))
    ) {
      continue;
    }

    const $s = cheerio.load(search);
    const want = compact.toLowerCase();
    let detailUrl = "";
    $s("h2 a, h3 a, .entry-title a, .article-title a, a.blog-entry-title-link").each(
      (_, el) => {
        if (detailUrl) return;
        const href = String($s(el).attr("href") || "");
        const text = stripTags($s(el).text());
        const hay = `${href} ${text}`.toLowerCase().replace(/-/g, "");
        if (hay.includes(want)) detailUrl = href;
      },
    );
    if (!detailUrl) {
      $s("a[href$='.html'], a[href*='.html?']").each((_, el) => {
        if (detailUrl) return;
        const href = String($s(el).attr("href") || "");
        if (href.toLowerCase().replace(/-/g, "").includes(want)) detailUrl = href;
      });
    }
    if (!detailUrl) continue;

    const abs = absUrl(detailUrl, searchPage?.finalUrl || base);
    if (!abs) continue;
    const detailPage = await fetchPage(abs, {
      referer: searchUrl,
      sourceId: "madou",
      timeoutMs: 25000,
    });
    const html = detailPage?.html || null;
    if (!html) continue;
    const parsed = parseMadouDetail(html, detailPage?.finalUrl || abs, code);
    if (parsed?.title || parsed?.poster) return parsed;
  }
  return null;
    },
  );
}

export async function scrapeMadouqu(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  // 与 madou 相同：保留前导零；本站搜索反而「带横杠」更准
  const code = madouStdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "madouqu",
    opts?.baseUrl || "https://madouqu.com",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);
  const compact = madouCompactCode(code);
  const want = compact.toLowerCase();

  const tryDetail = async (
    url: string,
    referer: string,
  ): Promise<PartialFromSource | null> => {
    const detailPage = await fetchPage(url, {
      referer,
      sourceId: "madouqu",
      viaFlare: false,
      timeoutMs: 25000,
    });
    const html = detailPage?.html || null;
    if (!html || html.length < 800) return null;
    if (
      /Just a moment|cf-browser-verification|Web server is returning an unknown error|Error code\s*5\d{2}|520:\s*Web server/i.test(
        html.slice(0, 4000),
      )
    ) {
      return null;
    }
    return parseMadouquDetail(html, detailPage?.finalUrl || url, code);
  };

  // 直达 /video/ 常被 CF 打成 5xx 错误页；以搜索精确命中为主
  const queries = [...new Set([code, compact])].filter(Boolean);
  for (const q of queries) {
    const searchUrl = `${base}/?s=${encodeURIComponent(q)}`;
    const searchPage = await fetchPage(searchUrl, {
      referer: `${base}/`,
      sourceId: "madouqu",
      viaFlare: false,
      timeoutMs: 25000,
    });
    const search = searchPage?.html || null;
    if (!search) continue;

    const $s = cheerio.load(search);
    let detailUrl = "";
    // 精确：标题首段番号或 /video/{slug}/
    $s("h2 a, h3 a, .entry-title a, .post-title a").each((_, el) => {
      if (detailUrl) return;
      const href = String($s(el).attr("href") || "");
      const text = stripTags($s(el).text());
      const idGuess = (text.split(/\s+/)[0] || "").replace(/-/g, "").toUpperCase();
      if (idGuess !== compact) return;
      detailUrl = href;
    });
    if (!detailUrl) {
      $s("a[href*='/video/']").each((_, el) => {
        if (detailUrl) return;
        const href = String($s(el).attr("href") || "");
        const key = href.toLowerCase().replace(/-/g, "");
        if (
          key.includes(`/video/${want}/`) ||
          key.includes(`/video/${code.toLowerCase()}/`)
        ) {
          detailUrl = href;
        }
      });
    }
    if (!detailUrl) continue;
    const abs = absUrl(detailUrl, searchPage?.finalUrl || base);
    if (!abs) continue;
    const hit = await tryDetail(abs, searchUrl);
    if (hit?.title || hit?.poster) return hit;
  }

  // 搜索失败再试直达（偶发可用）
  for (const slug of [...new Set([code.toLowerCase(), want])]) {
    const hit = await tryDetail(
      `${base}/video/${encodeURIComponent(slug)}/`,
      `${base}/`,
    );
    if (hit?.title || hit?.poster) return hit;
  }
  return null;
    },
  );
}

function parseMadouquDetail(
  html: string,
  detailUrl: string,
  code: string,
): PartialFromSource | null {
  const $ = cheerio.load(html);
  const compact = madouCompactCode(code);
  if (
    !madouPageHasCode(html, code) &&
    !new RegExp(compact, "i").test(detailUrl)
  ) {
    return null;
  }

  let title = cleanTitle(
    $("h1.entry-title, h1").first().text() ||
      pickOgTitle(html) ||
      $("title").first().text().replace(/\s*[-|｜].*麻豆.*$/i, ""),
    code,
  );
  title = title
    .replace(new RegExp(`^${code}\\s*[!！]?\\s*`, "i"), "")
    .replace(new RegExp(`^${compact}\\s*[!！]?\\s*`, "i"), "")
    .replace(/\s*[-|｜]\s*麻豆区?\s*$/i, "")
    .trim();
  if (isJunkTitle(title) || /的搜索结果|Web server is returning|Error code/i.test(title)) {
    title = "";
  }

  // 描述里结构化：麻豆女郎：梁幂、苡若…
  const desc =
    $("meta[name='description']").attr("content") ||
    $(".entry-content").first().text() ||
    "";
  const actressRaw =
    desc.match(/麻豆女郎\s*[:：]\s*([^\n下载下載]{2,80})/i)?.[1] ||
    html.match(/麻豆女郎\s*[:：]\s*([^<"\n]{2,80})/i)?.[1] ||
    "";
  const actorsFromDesc = actressRaw
    .split(/[,，、\/|]/)
    .map((s) => stripTags(s))
    .filter((n) => n && n.length >= 2 && n.length <= 20);

  const actorsFromTags = $("a[rel='tag'], .entry-tags a")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length >= 2 && n.length <= 20);

  const actors = [
    ...actorsFromDesc,
    ...actorsFromTags.filter((n) => !actorsFromDesc.includes(n)),
  ].slice(0, 20);

  let studio =
    stripTags(
      html.match(/分类\s*[:：]\s*([^<"\n{]{2,40})/i)?.[1] || "",
    ) ||
    stripTags(
      $(".entry-meta a[rel='category tag'], a[rel='category tag']").first().text(),
    ) ||
    "";
  if (/madou/i.test(studio) && /麻豆/.test(studio)) {
    studio = studio.replace(/madou\s*/i, "").trim() || studio;
  }
  // body 常以「madou 麻豆传媒」开头
  if (!studio) {
    const m = $(".entry-content").first().text().match(
      /(?:^|\s)((?:麻豆|果冻|天美|蜜桃|星空|兔子|皇家|精东)[^\s]{0,12})/,
    );
    studio = m?.[1] ? stripTags(m[1]) : "";
  }

  let cover =
    pickOgImage(html) ||
    absUrl(
      $(".entry-content img.size-full, .entry-content img.wp-image-")
        .first()
        .attr("src") ||
        $(".entry-content img.size-full, .entry-content img.wp-image-")
          .first()
          .attr("data-src") ||
        $(".entry-content img")
          .filter((_, el) => {
            const s =
              String($(el).attr("src") || "") ||
              String($(el).attr("data-src") || "") ||
              String($(el).attr("data-lazy-src") || "");
            return /uploads\//i.test(s) && !/logo|avatar|emoji/i.test(s);
          })
          .first()
          .attr("data-src") ||
        $(".entry-content img")
          .filter((_, el) => {
            const s =
              String($(el).attr("src") || "") ||
              String($(el).attr("data-src") || "");
            return /uploads\//i.test(s) && !/logo|avatar|emoji/i.test(s);
          })
          .first()
          .attr("src"),
      detailUrl,
    );
  if (cover) cover = absUrl(cover, detailUrl);
  // jetpack/i0.wp.com 代理图 → 原图
  if (cover) {
    const jp = cover.match(/i\d\.wp\.com\/([^?]+)/i)?.[1];
    if (jp) cover = `https://${jp}`;
  }
  if (cover && isJunkCoverUrl(cover)) cover = null;

  let premiered = "";
  const dt =
    $("time[datetime]").attr("datetime") ||
    html.match(/datePublished"\s*:\s*"([^"]+)"/i)?.[1] ||
    "";
  const dm = String(dt).match(/(\d{4})-(\d{2})-(\d{2})/);
  if (dm) premiered = `${dm[1]}-${dm[2]}-${dm[3]}`;

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    titleZh: title && isLikelyChinese(title) ? title : undefined,
    originalTitle: title || "",
    actors,
    studio: studio || undefined,
    makers: studio ? [studio] : undefined,
    premiered: premiered || undefined,
    poster: cover,
    source: "madouqu",
  };
}

/** 小黄书保留前导零（MD-0362）；勿用 stdCode 吞零 */
function xchinaCode(codeRaw: string): string {
  return madouStdCode(codeRaw);
}

function xchinaCompact(code: string): string {
  return madouCompactCode(code);
}

function parseXchinaLd(html: string): {
  title: string;
  cover: string;
  date: string;
  runtime: number | null;
  actors: string[];
} {
  let title = "";
  let cover = "";
  let date = "";
  let runtime: number | null = null;
  const actors: string[] = [];
  for (const block of html.matchAll(
    /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi,
  )) {
    try {
      const data = JSON.parse(block[1] || "");
      const items = Array.isArray(data) ? data : [data];
      for (const item of items) {
        if (!item || typeof item !== "object") continue;
        if (String(item["@type"] || "") !== "VideoObject") continue;
        title = String(item.name || title || "").trim();
        cover = String(item.thumbnailUrl || cover || "").trim();
        date = String(item.uploadDate || date || "").trim();
        const dur = String(item.duration || "");
        const mins = dur.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/i);
        if (mins) {
          runtime =
            Number(mins[1] || 0) * 60 +
              Number(mins[2] || 0) +
              Math.round(Number(mins[3] || 0) / 60) || runtime;
        }
        const act = item.actor;
        const list = Array.isArray(act) ? act : act ? [act] : [];
        for (const a of list) {
          const n = stripTags(String(a?.name || a || ""));
          if (n && !/^TEST[_-]?model$/i.test(n) && !actors.includes(n)) {
            actors.push(n);
          }
        }
      }
    } catch {
      /* ignore bad ld+json */
    }
  }
  return { title, cover, date, runtime, actors };
}

function parseXchinaDetail(
  html: string,
  detailUrl: string,
  code: string,
): PartialFromSource | null {
  const compact = xchinaCompact(code);
  if (
    !madouPageHasCode(html, code) &&
    !new RegExp(compact, "i").test(detailUrl)
  ) {
    return null;
  }

  const $ = cheerio.load(html);
  const ld = parseXchinaLd(html);

  let title = cleanTitle(
    $("h1.hero-title-item, h1").first().text() ||
      ld.title ||
      pickOgTitle(html) ||
      "",
    code,
  );
  title = title
    .replace(new RegExp(`^${compact}\\s*`, "i"), "")
    .replace(new RegExp(`^${code}\\s*`, "i"), "")
    .replace(new RegExp(`[（(]\\s*${compact}\\s*[）)]\\s*$`, "i"), "")
    .replace(new RegExp(`[（(]\\s*${code}\\s*[）)]\\s*$`, "i"), "")
    .replace(/\s*[-|｜]\s*(麻豆传媒|中文AV|小黄书|xChina).*$/i, "")
    .replace(/\s*[（(][^）)]{1,12}[）)]\s*$/u, (m) =>
      /MD|番号|官方|创作者|Vlog/i.test(m) ? "" : m,
    )
    .trim();
  // og 常带「片名 - 片商 - 中文AV」
  if (/ - /.test(title)) {
    const parts = title.split(/\s+-\s+/);
    if (parts.length >= 2 && /中文AV|小黄书|xChina/i.test(parts[parts.length - 1]!)) {
      title = parts.slice(0, -2).join(" - ").trim() || parts[0]!.trim();
    }
  }
  if (
    !title ||
    isJunkTitle(title) ||
    /站内搜索|成人影片|情色套图|Web server is returning/i.test(title)
  ) {
    title = "";
  }

  const crumb = $(".breadcrumb a")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((t) => t && !/首页|成人影片|情色套图/i.test(t));
  // 面包屑：… → 片商 → 片名；片商常为倒数第二
  let studio =
    stripTags($(".content-box.series .sub.checked").first().text()).replace(
      /\s*\(\d+\)\s*$/,
      "",
    ) ||
    (crumb.length >= 2 ? crumb[crumb.length - 2]! : "") ||
    stripTags($(".info-card.video-detail .item .text a").last().text()) ||
    "";
  if (/中文AV|^分类$/i.test(studio)) studio = "";
  if (studio === title) studio = "";

  const actors = [
    ...ld.actors,
    ...$(".info-card.video-detail .model-item, .model-container .model-item")
      .map((_, el) => stripTags($(el).text()))
      .get(),
  ]
    .map((n) => n.trim())
    .filter(
      (n) =>
        n &&
        n.length >= 2 &&
        n.length <= 24 &&
        !/^TEST[_-]?model$/i.test(n) &&
        !/推广|全国|约炮|空降/i.test(n),
    );
  const uniqActors = [...new Set(actors)].slice(0, 12);

  let cover =
    ld.cover ||
    pickOgImage(html) ||
    absUrl(
      $(".item.video .img")
        .first()
        .attr("style")
        ?.match(/url\(['"]?([^'")]+)['"]?\)/i)?.[1],
      detailUrl,
    );
  if (cover) cover = absUrl(cover, detailUrl);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  let premiered = "";
  const dm = String(ld.date).match(/(\d{4})-(\d{2})-(\d{2})/);
  if (dm) premiered = `${dm[1]}-${dm[2]}-${dm[3]}`;

  let runtime = ld.runtime;
  if (!runtime || runtime <= 0) {
    const sec = Number(
      $('meta[property="og:duration"]').attr("content") || 0,
    );
    if (sec > 0) runtime = Math.round(sec / 60);
  }

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    titleZh: title && isLikelyChinese(title) ? title : undefined,
    originalTitle: title || "",
    actors: uniqActors.length ? uniqActors : undefined,
    studio: studio || undefined,
    makers: studio ? [studio] : undefined,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    poster: cover,
    source: "xiao_huang_shu",
  };
}

/**
 * 小黄书 / xchina.co
 * 搜索 /search.html?keyword= → /video/id-{hex}.html；代理直连（一般无 CF）。
 * 番号保留前导零；勿把搜索页 og:title「站内搜索」当元数据。
 */
export async function scrapeXchina(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = xchinaCode(codeRaw);
  if (!code) return null;
  const compact = xchinaCompact(code);
  return withSiteMirrorBase(
    "xiao_huang_shu",
    opts?.baseUrl || "https://xchina.co",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");

  const searchUrls = [
    `${base}/search.html?keyword=${encodeURIComponent(code)}`,
    `${base}/search.html?keyword=${encodeURIComponent(compact)}`,
    `${base}/videos/keyword-${encodeURIComponent(code)}.html`,
    `${base}/videos/keyword-${encodeURIComponent(compact)}.html`,
  ];

  const want = codeKey(code);
  let detailUrl: string | null = null;

  for (const searchUrl of searchUrls) {
    const searchPage = await fetchPage(searchUrl, {
      referer: `${base}/`,
      sourceId: "xiao_huang_shu",
      viaFlare: false,
      timeoutMs: 25000,
    });
    const html = searchPage?.html || "";
    if (!html || looksBlockedHtml(html)) continue;

    const $ = cheerio.load(html);
    let best = "";
    $(".list.video-list .item.video, .item.video").each((_, el) => {
      if (best) return;
      const href =
        $(el).find("a[href*='/video/id-']").first().attr("href") ||
        $(el).find("a[href*='/video/']").first().attr("href") ||
        "";
      if (!href || !/\/video\/id-/i.test(href)) return;
      // 闭包里的 $ 才是本页；重绑匹配函数
      const tags = $(el)
        .find(".tags > div")
        .map((_, node) => codeKey(stripTags($(node).text())))
        .get()
        .filter(Boolean);
      const text = stripTags($(el).text());
      const title =
        stripTags($(el).find(".title a, a[title]").first().attr("title") || "") ||
        stripTags($(el).find(".title a").first().text());
      const blob = `${title} ${text}`;
      const boundary = new RegExp(
        `(?:^|[^A-Z0-9])${compact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:[^A-Z0-9]|$)`,
        "i",
      );
      const hit =
        tags.some((t) => t === want) ||
        codeKey(blob) === want ||
        boundary.test(blob);
      if (hit) best = href;
    });
    if (!best) {
      // 回退：页内紧邻 compact 的 /video/id-（仍要求边界，避免 MDSR 误命中）
      const esc = compact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const m =
        html.match(
          new RegExp(
            `href=["']([^"']*/video/id-[^"']+)["'][\\s\\S]{0,600}?(?:^|[^A-Za-z0-9])${esc}(?:[^A-Za-z0-9]|$)`,
            "i",
          ),
        ) ||
        html.match(
          new RegExp(
            `(?:^|[^A-Za-z0-9])${esc}(?:[^A-Za-z0-9]|$)[\\s\\S]{0,600}?href=["']([^"']*/video/id-[^"']+)["']`,
            "i",
          ),
        );
      best = m?.[1] || "";
    }
    // 仅一条结果时也必须番号匹配，禁止盲取
    if (!best && $(".item.video").length === 1) {
      const el = $(".item.video").get(0);
      if (el) {
        const tags = $(el)
          .find(".tags > div")
          .map((_, node) => codeKey(stripTags($(node).text())))
          .get()
          .filter(Boolean);
        const boundary = new RegExp(
          `(?:^|[^A-Z0-9])${compact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:[^A-Z0-9]|$)`,
          "i",
        );
        if (
          tags.some((t) => t === want) ||
          boundary.test(stripTags($(el).text()))
        ) {
          best =
            $(el).find("a[href*='/video/id-']").first().attr("href") || "";
        }
      }
    }
    if (!best) continue;
    detailUrl = absUrl(best, searchPage?.finalUrl || base);
    if (detailUrl) break;
  }

  if (!detailUrl) return null;

  const detailPage = await fetchPage(detailUrl, {
    referer: `${base}/search.html`,
    sourceId: "xiao_huang_shu",
    viaFlare: false,
    timeoutMs: 25000,
  });
  const detailHtml = detailPage?.html || "";
  if (!detailHtml || looksBlockedHtml(detailHtml)) return null;
  return parseXchinaDetail(
    detailHtml,
    detailPage?.finalUrl || detailUrl,
    code,
  );
    },
  );
}
