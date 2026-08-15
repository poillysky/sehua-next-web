import * as cheerio from "cheerio";
import { fetch as undiciFetch } from "undici";
import {
  dmmCoverUrls,
  extractDmmCidFromUrl,
  guessDmmCids,
} from "../dmmCid.js";
import {
  fetchJson,
  fetchPage,
  fetchPostForm,
  fetchText,
  probeImageUrl,
} from "../download.js";
import { looksBlockedHtml, registerFlareHost } from "../flaresolverr.js";
import {
  invalidateAiravMirror,
  normalizeAiravCnBase,
  rememberAiravMirror,
  resolveAiravCnBase,
} from "../airavMirror.js";
import {
  invalidateIqqtvMirror,
  normalizeIqqtvRoot,
  rememberIqqtvMirror,
  resolveIqqtvRoot,
} from "../iqqtvMirror.js";
import { withSiteMirrorBase } from "../siteMirror.js";
import type { PartialFromSource } from "../sources.js";
import { isJunkCoverUrl, isJunkTitle, isLikelyChinese, stdCode, UA } from "../util.js";

type LibreMovie = {
  err?: string;
  title?: string;
  subtitle?: string;
  description?: string;
  comment?: string;
  normalized_id?: string;
  cover_image_url?: string;
  thumbnail_image_url?: string;
  actresses?: Array<{ name?: string }>;
  makers?: string[];
  genres?: string[];
  directors?: string[];
  labels?: string[];
  series?: string | string[];
  date?: string;
  review?: number;
  minute?: number;
  runtime?: number;
  url?: string;
  sample_image_urls?: string[];
};

function stripTags(s: string): string {
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function absUrl(href: string | undefined | null, base: string): string | null {
  if (!href) return null;
  try {
    if (href.startsWith("//")) return `https:${href}`;
    return new URL(href, base).href;
  } catch {
    return null;
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

/** freejavbt 详情常把播放器 16:9 截帧写进 og:image，不能当碟片封面 */
function isFreejavbtVideoThumb(url: string, html?: string): boolean {
  const u = String(url || "").trim().toLowerCase();
  if (!u) return true;
  if (
    /tutu\d*\.space|fmtu\.|sl2025p\.com|sex8|\/vod\/|\/video\/m3u8|loading_|placeholder|theporndude|upload\.png/i.test(
      u,
    )
  ) {
    return true;
  }
  if (/\/samples?\//i.test(u)) return true;
  // jdbstatic/covers 在 freejavbt 上几乎全是「推荐」别人的封面，opaque id 无法校验番号
  if (/jdbstatic\.com\/covers\//i.test(u)) return true;
  if (html) {
    const w = Number(
      html.match(
        /property=["']og:image:width["'][^>]*content=["'](\d+)/i,
      )?.[1] ||
        html.match(
          /content=["'](\d+)["'][^>]*property=["']og:image:width["']/i,
        )?.[1] ||
        0,
    );
    const h = Number(
      html.match(
        /property=["']og:image:height["'][^>]*content=["'](\d+)/i,
      )?.[1] ||
        html.match(
          /content=["'](\d+)["'][^>]*property=["']og:image:height["']/i,
        )?.[1] ||
        0,
    );
    if (w > 0 && h > 0) {
      const ratio = w / h;
      if (ratio >= 1.65 && ratio <= 1.9) return true;
    }
  }
  return false;
}

/** DMM 封面 URL 是否明显属于该番号（避免串号） */
function dmmCoverMatchesCode(url: string, code: string): boolean {
  const u = String(url || "").toLowerCase();
  const c = stdCode(code).toLowerCase();
  if (!u || !c || !/pics\.dmm\.co\.jp|awsimgsrc\.dmm/i.test(u)) return false;
  const compact = c.replace(/-/g, "");
  // sone-001 → sone001 / sone00001（DMM 常补零）
  const m = c.match(/^([a-z]+)(\d+)$/i);
  if (!m) return u.includes(compact);
  const prefix = m[1]!;
  const digits = m[2]!;
  const n = String(parseInt(digits, 10));
  const padded = digits.padStart(5, "0");
  const padded3 = digits.padStart(3, "0");
  return (
    u.includes(`${prefix}${digits}`) ||
    u.includes(`${prefix}${padded}`) ||
    u.includes(`${prefix}${padded3}`) ||
    u.includes(`${prefix}${n}`) ||
    u.includes(compact)
  );
}

/**
 * freejavbt 封面：只认「URL 能校验番号」的 DMM pl/封面。
 * 不采用 jdbstatic（推荐位串号）/ 播放器截帧 / og:image。
 * 没有可靠封面则返回 null，交给 javbus/jav321。
 */
function pickFreejavbtCover(
  _$: cheerio.CheerioAPI,
  html: string,
  landed: string,
  code: string,
): string | null {
  const cutRe = /你可能喜欢|あなたは好きかもしれません/i;
  const cutAt = html.search(cutRe);
  const mainHtml = cutAt > 0 ? html.slice(0, cutAt) : html;

  const cands: string[] = [];
  const push = (raw: string | undefined | null) => {
    const abs = absUrl(String(raw || "").trim(), landed);
    if (!abs || isJunkCoverUrl(abs) || isFreejavbtVideoThumb(abs, html)) return;
    if (!dmmCoverMatchesCode(abs, code) && !/javbus\.com\/pics\/cover\//i.test(abs)) {
      return;
    }
    // javbus 站内封面偶现，仍要求页面提到本番号（main 区）
    if (!cands.includes(abs)) cands.push(abs);
  };

  for (const m of mainHtml.matchAll(
    /https?:\/\/[^"'\s]+(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm)[^"'\s]+/gi,
  )) {
    push(m[0]);
  }
  // 优先 pl 大图
  const pl = cands.find((u) => /pl\.(?:jpe?g|png|webp)(?:$|\?)/i.test(u));
  if (pl) return pl;
  if (cands[0]) return cands[0];
  return null;
}

function cleanTitle(raw: string | null | undefined, code: string): string {
  let t = stripTags(String(raw || ""));
  if (!t) return "";
  t = t.replace(new RegExp(`^${code}\\s*[-–—:]?\\s*`, "i"), "").trim() || t;
  t = t.replace(/\s*[|｜].*$/, "").trim();
  return t;
}

function collectByRe(html: string, re: RegExp): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const r = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  let m: RegExpExecArray | null;
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
  return new RegExp(c, "i").test(html.slice(0, 12000));
}

function hit(
  code: string,
  source: string,
  title: string,
  poster: string | null,
  actors: string[] = [],
): PartialFromSource | null {
  if (!title && !poster) return null;
  return {
    code,
    title: title || "",
    originalTitle: title || "",
    actors,
    poster,
    productId: extractDmmCidFromUrl(poster) || undefined,
    source,
  };
}

function isDmmRegionBlocked(html: string): boolean {
  return /このページはお住まいの地域からご利用になれません|not available in your (area|region)|国外から.*ご利用|地域からご利用になれません|お住まいの地域|not-available-in-your-region/i.test(
    html,
  );
}

function isDmmAgeGate(html: string): boolean {
  if (!html) return false;
  if (/出演者|メーカー|収録時間|商品発売日|h1#title|itemprop=["']description["']/i.test(html)) {
    return false;
  }
  return /年齢認証|Age Verification|age_check|adult site that handles adult/i.test(
    html,
  );
}

function looksLikeDmmDetail(html: string): boolean {
  return /出演者|メーカー|収録時間|商品発売日|レーベル|シリーズ|id=["']title["']/i.test(
    html,
  );
}

async function probeDmmCovers(
  cid: string,
): Promise<{ pl: string | null; ps: string | null }> {
  const urls = dmmCoverUrls(cid);
  const site = "https://www.dmm.co.jp";
  let pl: string | null = null;
  let ps: string | null = null;
  for (const url of [urls.pl, urls.awsPl]) {
    const probe = await probeImageUrl(url, { referer: `${site}/` });
    if (!probe.ok) continue;
    if (/now_printing/i.test(probe.finalUrl)) continue;
    if (probe.sizeHint > 0 && probe.sizeHint < 30000) continue;
    pl = url;
    break;
  }
  for (const url of [urls.ps, urls.awsPs]) {
    const probe = await probeImageUrl(url, { referer: `${site}/` });
    if (!probe.ok) continue;
    if (/now_printing/i.test(probe.finalUrl)) continue;
    if (probe.sizeHint > 0 && probe.sizeHint < 8000) continue;
    ps = url;
    break;
  }
  return { pl, ps };
}

function parseDmmDetailHtml(
  html: string,
  code: string,
  cid: string,
): PartialFromSource {
  const $ = cheerio.load(html);
  const regionBlocked = isDmmRegionBlocked(html);

  let title = cleanTitle(
    pickOgTitle(html) ||
      $("h1#title").text() ||
      $("h1").first().text() ||
      html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1],
    code,
  );

  const actors: string[] = [];
  $('a[href*="actress="], a[href*="/actress/"], span#performer a').each(
    (_, el) => {
      const n = stripTags($(el).text());
      if (n && n.length < 40 && !actors.includes(n)) actors.push(n);
    },
  );

  const genres: string[] = [];
  $('a[href*="genre="], a[href*="/genre/"]').each((_, el) => {
    const n = stripTags($(el).text());
    if (n && n.length < 40 && !genres.includes(n)) genres.push(n);
  });

  const tableText = (label: RegExp): string => {
    let found = "";
    $("table.mg-b20 tr, table[class*='mg-b'] tr, .page-detail table tr").each(
      (_, el) => {
        const row = $(el).text().replace(/\s+/g, " ").trim();
        if (!label.test(row)) return;
        const cells = $(el).find("td");
        if (cells.length >= 2) {
          found = stripTags(cells.last().text());
        } else {
          found = stripTags(row.replace(label, "").replace(/^[:：\s]+/, ""));
        }
      },
    );
    return found;
  };

  const premiered = (
    tableText(/発売日|配信開始日|商品発売日/) ||
    html.match(/発売日[:：\s]*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2})/i)?.[1] ||
    ""
  )
    .replace(/年|月/g, "-")
    .replace(/日/g, "")
    .replace(/\//g, "-")
    .slice(0, 10);

  const runtimeRaw =
    tableText(/収録時間|播放時間|動画時間/) ||
    html.match(/収録時間[:：\s]*(\d+)\s*分/i)?.[1] ||
    "";
  const runtime = Number(String(runtimeRaw).match(/(\d+)/)?.[1] || 0) || null;

  const director = tableText(/監督/) || "";
  const maker =
    tableText(/メーカー/) ||
    collectByRe(html, /メーカー[:：\s]*([^<\n]+)/i)[0] ||
    "";
  const publisher = tableText(/レーベル/) || "";
  const studio = maker || undefined;
  const series =
    tableText(/シリーズ/) ||
    $('a[href*="series="]').first().text().trim() ||
    "";

  let plot =
    stripTags(
      $(".mg-b20.lh4").first().text() ||
        $("[class*='summary']").first().text() ||
        $("meta[name='description']").attr("content") ||
        "",
    ) || "";
  if (plot.length < 20) {
    plot =
      stripTags(
        html.match(/<div[^>]*class=["'][^"']*lh4[^"']*["'][^>]*>([\s\S]*?)<\/div>/i)?.[1] ||
          "",
      ) || plot;
  }
  if (
    plot &&
    (isJunkTitle(plot) ||
      plot.length < 12 ||
      /adult site that handles adult|年齢認証|定額料金で見放題/i.test(plot))
  ) {
    plot = "";
  }

  // 年龄门 / 英文壳页勿当标题
  if (isDmmAgeGate(html) || /年齢認証\s*-\s*FANZA/i.test(html)) {
    title = "";
  }

  const ratingRaw =
    html.match(/平均[：:]\s*([0-9.]+)/)?.[1] ||
    html.match(/([0-9]\.[0-9]{2})\s*点/)?.[1] ||
    $('p.d-review__average strong, .d-review__average').first().text();
  const userRating = Number(String(ratingRaw).match(/([0-9.]+)/)?.[1] || 0) || null;

  const originalTitle = title;

  return {
    code,
    title: regionBlocked ? title : title,
    originalTitle,
    plot,
    actors: actors.slice(0, 40),
    genres: genres.slice(0, 40),
    premiered,
    studio,
    publisher: publisher || undefined,
    makers: maker ? [maker] : [],
    runtime,
    director,
    series,
    userRating: userRating && userRating > 0 && userRating <= 10 ? userRating : null,
    productId: cid,
    source: "dmm",
    message: regionBlocked ? "地域限制, 请使用日本节点访问！" : undefined,
  } as PartialFromSource;
}

export type DmmScrapeOpts = {
  preferCid?: string;
  preferCids?: string[];
  /** 标记本次为 CID 回退重查 */
  cidRetry?: boolean;
};

/**
 * DMM 刮削：CDN 封面（pl/ps）+ 详情页字段。
 * 支持 preferCid（他源吐出的 53dv01588）回退，对齐 mdc-ng。
 */
export async function scrapeDmm(
  codeRaw: string,
  opts?: DmmScrapeOpts,
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code || /^FC2/i.test(code)) return null;
  if (!/^([A-Z]{2,10})-(\d{2,6})$/.test(code)) return null;

  const site = "https://www.dmm.co.jp";
  const prefer = [
    ...(opts?.preferCid ? [opts.preferCid] : []),
    ...(opts?.preferCids || []),
  ]
    .map((c) => String(c || "").trim().toLowerCase())
    .filter(Boolean);
  const variants = [...prefer, ...guessDmmCids(code)].filter(
    (c, i, arr) => c && arr.indexOf(c) === i,
  );

  let cid = variants[0] || "";
  let pl: string | null = null;
  let ps: string | null = null;
  for (const c of variants) {
    const covers = await probeDmmCovers(c);
    if (covers.pl || covers.ps) {
      cid = c;
      pl = covers.pl;
      ps = covers.ps;
      break;
    }
  }
  // CDN 探测全失败时仍用优先 CID 去拉详情（出口常拦 pics 但不拦/可代理详情）
  if (!pl && !ps) {
    cid = prefer[0] || variants[0] || cid;
  }

  const detailPaths = [
    `https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=${cid}/`,
    `https://video.dmm.co.jp/av/content/?id=${cid}`,
    `https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=${cid}/`,
    `https://www.dmm.co.jp/digital/video/-/detail/=/cid=${cid}/`,
  ];
  let html: string | null = null;
  let detailFinal = "";
  let regionBlockedHit = false;
  for (const detailUrl of detailPaths) {
    let page = await fetchPage(detailUrl, {
      referer: "https://www.dmm.co.jp/",
      sourceId: "dmm",
      timeoutMs: 22000,
    });
    if (!page?.html || page.html.length < 400) continue;
    detailFinal = page.finalUrl || detailUrl;

    if (
      isDmmRegionBlocked(page.html) ||
      /not-available-in-your-region/i.test(detailFinal)
    ) {
      regionBlockedHit = true;
      html = page.html;
      break;
    }

    if (isDmmAgeGate(page.html)) {
      const rurl = encodeURIComponent(detailFinal || detailUrl);
      // 落地可能是 /en/age_check/（英文壳）或日文 /age_check/
      const declareUrls = [
        /\/en\/age_check/i.test(detailFinal)
          ? `https://www.dmm.co.jp/en/age_check/=/declared=yes/?rurl=${rurl}`
          : `https://www.dmm.co.jp/age_check/=/declared=yes/?rurl=${rurl}`,
        `https://www.dmm.co.jp/age_check/=/declared=yes/?rurl=${rurl}`,
        `https://www.dmm.co.jp/en/age_check/=/declared=yes/?rurl=${rurl}`,
      ].filter((u, i, arr) => arr.indexOf(u) === i);
      for (const declareUrl of declareUrls) {
        await fetchPage(declareUrl, {
          referer: detailFinal || detailUrl,
          sourceId: "dmm",
          timeoutMs: 15000,
        });
      }
      page = await fetchPage(detailUrl, {
        referer: "https://www.dmm.co.jp/",
        sourceId: "dmm",
        timeoutMs: 22000,
      });
      if (!page?.html) continue;
      detailFinal = page.finalUrl || detailUrl;
      if (
        isDmmRegionBlocked(page.html) ||
        /not-available-in-your-region/i.test(detailFinal)
      ) {
        regionBlockedHit = true;
        html = page.html;
        break;
      }
      // 仍卡在年龄门则换下一条详情 URL
      if (isDmmAgeGate(page.html)) continue;
    }

    if (looksLikeDmmDetail(page.html) && !isDmmAgeGate(page.html)) {
      html = page.html;
      break;
    }
  }

  // 详情拿到后若仍无封面，用当前 cid 再探一次；或从 HTML 抽 og:image
  if ((!pl && !ps) && html) {
    const og = pickOgImage(html);
    if (og && /dmm\.co\.jp|awsimgsrc/i.test(og)) {
      pl = absUrl(og, site) || og;
    }
    if (!pl && !ps) {
      const covers = await probeDmmCovers(cid);
      pl = covers.pl;
      ps = covers.ps;
    }
  }

  const cover = pl || ps;
  if (!cover && !html) return null;

  if (!html) {
    return {
      code,
      title: "",
      originalTitle: "",
      poster: cover,
      portrait: ps,
      productId: cid,
      source: "dmm",
      message: "详情页不可达",
    } as PartialFromSource;
  }

  const parsed = parseDmmDetailHtml(html, code, cid);
  const regionBlocked =
    regionBlockedHit ||
    Boolean(
      (parsed as { message?: string }).message?.includes("地域限制"),
    ) ||
    isDmmRegionBlocked(html);

  if (regionBlocked && !parsed.title && !parsed.plot) {
    if (!cover) return null;
    return {
      ...parsed,
      title: "",
      plot: "",
      poster: cover,
      portrait: ps,
      productId: cid,
      source: "dmm",
      message: "地域限制, 请使用日本节点访问！",
    } as PartialFromSource;
  }

  if (isDmmAgeGate(html) && !parsed.title && !parsed.plot) {
    if (!cover) return null;
    return {
      code,
      title: "",
      originalTitle: "",
      poster: cover,
      portrait: ps,
      productId: cid,
      source: "dmm",
      message: "年龄认证未通过 / 详情页不可达",
    } as PartialFromSource;
  }

  if (!parsed.title && !parsed.plot && !cover) return null;

  return {
    ...parsed,
    poster: cover || parsed.poster || null,
    portrait: ps || undefined,
    productId: cid,
    source: "dmm",
    message: regionBlocked
      ? "地域限制, 请使用日本节点访问！"
      : parsed.message,
  } as PartialFromSource;
}

export async function scrapeJavlibrary(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "javlibrary",
    opts?.baseUrl || "https://www.javlibrary.com/cn",
    async (baseRaw) => {
  // /cn = 简体 UI（类别中文）；标题/女优仍日文。强依赖 Flare
  const cn = baseRaw.replace(/\/$/, "") || "https://www.javlibrary.com/cn";
  const searchUrl = `${cn}/vl_searchbyid.php?keyword=${encodeURIComponent(code)}`;
  const searchPage = await fetchPage(searchUrl, {
    referer: `${cn}/`,
    sourceId: "javlibrary",
    viaFlare: true,
    waitInSeconds: 3,
    timeoutMs: 60000,
  });
  let html = searchPage?.html || null;
  let detailUrl = searchPage?.finalUrl || searchUrl;
  if (!html) return null;

  const want = code.replace(/-/g, "").toUpperCase();
  const isDetail = /id=["']video_title["']/i.test(html);

  if (!isDetail) {
    const $s = cheerio.load(html);
    type Cand = { href: string; id: string; title: string };
    const cands: Cand[] = [];
    $s(".videos .video, .video").each((_, el) => {
      const $el = $s(el);
      const href = String($el.find("a").first().attr("href") || "").trim();
      const id = $el.find(".id").first().text().replace(/\s+/g, " ").trim();
      const title = $el.find(".title").first().text().replace(/\s+/g, " ").trim();
      if (!href || !id) return;
      const idKey = id.replace(/-/g, "").toUpperCase();
      if (idKey !== want) return;
      cands.push({ href, id, title });
    });
    if (!cands.length) {
      // 旧式 /?v= 兜底
      const path =
        html.match(
          new RegExp(
            `href=["']([^"']*(?:/\\?v=|jav[a-z0-9]+\\.html)[^"']*)["'][^>]*>[\\s\\S]{0,120}?${code.replace(/-/g, "[-]?")}`,
            "i",
          ),
        )?.[1] || "";
      if (!path) return null;
      cands.push({ href: path, id: code, title: "" });
    }
    // 同番号多条（蓝光盘等）：优先无「ブルーレイ」的普通盘
    cands.sort((a, b) => {
      const ab = /ブルーレイ|Blu-?ray|BD/i.test(a.title) ? 1 : 0;
      const bb = /ブルーレイ|Blu-?ray|BD/i.test(b.title) ? 1 : 0;
      return ab - bb;
    });
    const picked = cands[0]!;
    const next = absUrl(picked.href.replace(/^\.\//, ""), `${cn}/`);
    if (!next) return null;
    detailUrl = next;
    const detailPage = await fetchPage(detailUrl, {
      referer: searchUrl,
      sourceId: "javlibrary",
      viaFlare: true,
      waitInSeconds: 2,
      timeoutMs: 60000,
    });
    html = detailPage?.html || null;
    detailUrl = detailPage?.finalUrl || detailUrl;
  }
  if (!html || !/id=["']video_title["']/i.test(html)) return null;
  if (!pageMentionsCode(html, code)) return null;

  const $ = cheerio.load(html);
  let title = cleanTitle(
    $("#video_title a").first().text() ||
      pickOgTitle(html) ||
      $("title").first().text().replace(/\s*-\s*JAVLibrary.*$/i, ""),
    code,
  );
  title = title
    .replace(/\s*[（(]\s*ブルーレイディスク\s*[）)]\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
  if (isJunkTitle(title)) title = "";

  const textOf = (sel: string): string =>
    stripTags($(sel).find(".text").first().text() || $(sel).text());

  const linkOf = (sel: string): string => {
    const n = stripTags($(sel).find("a").first().text());
    const raw = n || textOf(sel).replace(/^[^:：]+[:：]\s*/, "");
    if (!raw || /^[-\u2014\u2013_]+$/.test(raw)) return "";
    return raw;
  };

  const premieredRaw = textOf("#video_date");
  let premiered = "";
  const dm = premieredRaw.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const runtime =
    Number(textOf("#video_length").match(/(\d+)/)?.[1] || 0) || null;
  const director = linkOf("#video_director") || undefined;
  const studio = linkOf("#video_maker") || undefined;
  const publisher = linkOf("#video_label") || undefined;
  const series = linkOf("#video_series") || undefined;

  const genres = $("#video_genres a")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length < 40)
    .filter((n, i, a) => a.indexOf(n) === i)
    .slice(0, 40);

  const actors = $(
    "#video_cast a[href*='star.php'], a[href*='star.php'][rel='tag']",
  )
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length >= 2 && n.length < 40)
    .filter((n, i, a) => a.indexOf(n) === i)
    .slice(0, 20);

  let cover =
    absUrl($("#video_jacket_img").attr("src"), detailUrl) ||
    pickOgImage(html);
  if (cover) cover = absUrl(cover, detailUrl);
  // mono ps → 优先 pl
  let portrait: string | undefined;
  if (cover && /ps\.jpg/i.test(cover)) {
    portrait = cover;
    cover = cover.replace(/ps\.jpg/i, "pl.jpg");
  }
  if (cover && isJunkCoverUrl(cover)) cover = null;
  if (portrait && isJunkCoverUrl(portrait)) portrait = undefined;

  const scoreRaw =
    stripTags($("#video_review .score").text()) ||
    textOf("#video_review").match(/\(([\d.]+)\)/)?.[1] ||
    "";
  const userRating =
    Number(String(scoreRaw).match(/(\d+(?:\.\d+)?)/)?.[1] || 0) || null;

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    actors,
    genres: genres.length ? genres : undefined,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    director,
    studio,
    publisher: publisher || undefined,
    makers: studio ? [studio] : undefined,
    series: series || undefined,
    userRating:
      userRating && userRating > 0 && userRating <= 10 ? userRating : null,
    poster: cover,
    portrait,
    productId:
      extractDmmCidFromUrl(cover || portrait || "") ||
      String(cover || portrait || "").match(
        /\/(?:mono\/movie\/adult|digital\/video)\/([a-z0-9_]+)\//i,
      )?.[1] ||
      undefined,
    source: "javlibrary",
  };
    },
  );
}

/** Avbase = Next.js；SSR 嵌在 __NEXT_DATA__，勿再瞎匹配 HTML 卡片链接 */
function parseNextData(html: string): Record<string, unknown> | null {
  const raw = html.match(
    /id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i,
  )?.[1];
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function nextPageProps(html: string): Record<string, unknown> | null {
  const nd = parseNextData(html);
  if (!nd) return null;
  const props = (nd.props || {}) as Record<string, unknown>;
  const pp = (props.pageProps || {}) as Record<string, unknown>;
  return pp && typeof pp === "object" ? pp : null;
}

function avbaseCodeKey(s: string): string {
  return String(s || "")
    .replace(/[-_\s]/g, "")
    .toUpperCase();
}

function normalizeAvbaseBase(raw?: string): string {
  const fallback = "https://www.avbase.net";
  const t = String(raw || "").trim();
  if (!t) return fallback;
  try {
    const u = new URL(/^https?:\/\//i.test(t) ? t : `https://${t}`);
    return `${u.protocol}//${u.host}`;
  } catch {
    return fallback;
  }
}

function avbaseJoinId(prefix: string, workId: string): string {
  const p = String(prefix || "").trim();
  const w = String(workId || "").trim();
  if (!w) return "";
  return p ? `${p}:${w}` : w;
}

type AvbaseProduct = {
  source?: string;
  title?: string;
  image_url?: string;
  thumbnail_url?: string;
  product_id?: string;
  date?: string;
  maker?: { name?: string } | string;
  label?: { name?: string } | string;
  series?: { name?: string } | string;
  iteminfo?: {
    description?: string;
    director?: string;
    volume?: string | number;
  };
  sample_image_urls?: Array<{ l?: string; s?: string }>;
};

type AvbaseWork = {
  id?: number | string;
  prefix?: string;
  work_id?: string;
  title?: string;
  min_date?: string;
  actors?: Array<{ name?: string } | string>;
  casts?: Array<{ actor?: { name?: string }; name?: string } | string>;
  genres?: Array<{ name?: string } | string>;
  tags?: Array<{ name?: string } | string>;
  products?: AvbaseProduct[];
};

function avbaseNameOf(x: unknown): string {
  if (!x) return "";
  if (typeof x === "string") return x.trim();
  if (typeof x === "object" && x && "name" in x) {
    return String((x as { name?: string }).name || "").trim();
  }
  return "";
}

function avbasePickProduct(products: AvbaseProduct[]): AvbaseProduct | null {
  if (!products.length) return null;
  const rank = (src: string) => {
    const s = src.toLowerCase();
    if (s.includes("mgstage") || s === "mgs") return 50;
    if (s.includes("fanza") || s.includes("dmm")) return 40;
    if (s.includes("duga")) return 30;
    if (s.includes("getchu")) return 20;
    if (s.includes("pcolle")) return 10;
    return 0;
  };
  return [...products].sort((a, b) => {
    const rd = rank(String(b.source || "")) - rank(String(a.source || ""));
    if (rd) return rd;
    const aScore =
      (a.image_url ? 2 : 0) +
      (a.iteminfo?.description ? 1 : 0) +
      (a.series ? 1 : 0);
    const bScore =
      (b.image_url ? 2 : 0) +
      (b.iteminfo?.description ? 1 : 0) +
      (b.series ? 1 : 0);
    return bScore - aScore;
  })[0]!;
}

function avbasePickWork(works: AvbaseWork[], code: string): AvbaseWork | null {
  const want = avbaseCodeKey(code);
  if (!want || !works.length) return null;
  const exact = works.find(
    (w) => avbaseCodeKey(String(w.work_id || "")) === want,
  );
  if (exact) return exact;
  return (
    works.find((w) => {
      const id = String(w.work_id || w.id || "");
      const tail = id.includes(":") ? id.split(":").pop() || "" : id;
      return avbaseCodeKey(tail) === want;
    }) || null
  );
}

function parseAvbaseWork(
  work: AvbaseWork,
  code: string,
): PartialFromSource | null {
  if (!work) return null;
  const product = avbasePickProduct(work.products || []);
  let title = cleanTitle(
    String(product?.title || work.title || "").trim(),
    code,
  );
  if (isJunkTitle(title)) title = "";

  const actors: string[] = [];
  const pushActor = (n: string) => {
    const t = n.trim();
    if (!t || actors.includes(t)) return;
    if (/女優|女优|出演|cast|actor/i.test(t)) return;
    actors.push(t);
  };
  for (const c of work.casts || []) {
    if (typeof c === "string") pushActor(c);
    else pushActor(avbaseNameOf(c?.actor) || avbaseNameOf(c));
  }
  for (const a of work.actors || []) {
    pushActor(typeof a === "string" ? a : avbaseNameOf(a));
  }

  const genres: string[] = [];
  const pushGenre = (n: string) => {
    const t = n.trim();
    if (!t || genres.includes(t)) return;
    if (/更多|全部|标签|ジャンル/i.test(t) || isJunkTitle(t)) return;
    genres.push(t);
  };
  for (const g of [...(work.genres || []), ...(work.tags || [])]) {
    pushGenre(typeof g === "string" ? g : avbaseNameOf(g));
  }

  const maker = avbaseNameOf(product?.maker);
  const label = avbaseNameOf(product?.label);
  let series = avbaseNameOf(product?.series);
  if (series.length < 2 || isJunkTitle(series)) series = "";

  let plot = stripTags(String(product?.iteminfo?.description || "").trim());
  if (plot.length < 12 || isJunkTitle(plot)) plot = "";

  let cover =
    String(product?.image_url || product?.thumbnail_url || "").trim() || null;
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart = (product?.sample_image_urls || [])
    .map((s) => String(s.l || s.s || "").trim())
    .filter((u) => u && !isJunkCoverUrl(u))
    .slice(0, 30);

  const director = String(product?.iteminfo?.director || "").trim() || undefined;
  const vol = Number(product?.iteminfo?.volume);
  const runtime = Number.isFinite(vol) && vol > 0 ? vol : null;

  let premiered: string | undefined;
  const dateRaw = String(product?.date || work.min_date || "").trim();
  if (dateRaw) {
    const d = new Date(dateRaw);
    if (!Number.isNaN(d.getTime())) {
      premiered = d.toISOString().slice(0, 10);
    }
  }

  const productId =
    String(product?.product_id || "").trim() ||
    extractDmmCidFromUrl(cover) ||
    undefined;

  if (
    !title &&
    !cover &&
    !actors.length &&
    !plot &&
    !genres.length &&
    !series
  ) {
    return null;
  }

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    plot,
    actors: actors.slice(0, 20),
    genres: genres.slice(0, 40),
    series: series || undefined,
    studio: maker || undefined,
    publisher: label || undefined,
    makers: maker ? [maker] : [],
    director,
    runtime,
    premiered,
    poster: cover,
    portrait: product?.thumbnail_url || undefined,
    fanart: fanart.length ? fanart : undefined,
    productId,
    source: "avbase",
  };
}

export async function scrapeAvbase(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "avbase",
    opts?.baseUrl || "https://www.avbase.net",
    async (baseRaw) => {
  const base = normalizeAvbaseBase(baseRaw);
  const searchUrl = `${base}/works?q=${encodeURIComponent(code)}`;

  const searchPage = await fetchPage(searchUrl, {
    referer: `${base}/`,
    sourceId: "avbase",
    timeoutMs: 20000,
    viaFlare: false,
    strictTimeout: true,
  });
  if (!searchPage?.html) return null;
  const searchProps = nextPageProps(searchPage.html);
  const works = (searchProps?.works as AvbaseWork[] | undefined) || [];
  let work = avbasePickWork(works, code);

  // 搜索页摘要 → 详情页补全 casts / genres / 简介
  if (work) {
    const detailId = avbaseJoinId(
      String(work.prefix || ""),
      String(work.work_id || code),
    );
    if (detailId) {
      // Avbase 路由用字面 colon：/works/honnaka:HMN-001
      const detailUrlColon = `${base}/works/${detailId}`;
      const detailPage = await fetchPage(detailUrlColon, {
        referer: searchUrl,
        sourceId: "avbase",
        timeoutMs: 20000,
        viaFlare: false,
        strictTimeout: true,
      });
      const detailProps = detailPage?.html
        ? nextPageProps(detailPage.html)
        : null;
      const detailWork = (detailProps?.work as AvbaseWork | undefined) || null;
      if (detailWork) {
        work = detailWork;
      } else {
        const detailUrlEnc = `${base}/works/${encodeURIComponent(detailId)}`;
        const again = await fetchPage(detailUrlEnc, {
          referer: searchUrl,
          sourceId: "avbase",
          timeoutMs: 20000,
          viaFlare: false,
          strictTimeout: true,
        });
        const againProps = again?.html ? nextPageProps(again.html) : null;
        if (againProps?.work) work = againProps.work as AvbaseWork;
      }
    }
  }

  if (!work) return null;
  return parseAvbaseWork(work, code);
    },
  );
}

export async function scrapeJav321(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "jav321",
    opts?.baseUrl || "https://www.jav321.com",
    async (baseRaw) => {
  // www=简体 UI 标签，但标题/简介/女优/ジャンル 实际多为日文；无 og:*，靠 panel 解析
  const base = baseRaw.replace(/\/$/, "") || "https://www.jav321.com";
  const html = await fetchPostForm(
    `${base}/search`,
    `sn=${encodeURIComponent(code)}`,
    { referer: `${base}/`, sourceId: "jav321", timeoutMs: 20000 },
  );
  if (!html) return null;
  if (
    /AVが見つかりませんでした|還沒有人投稿|not found|找不到|没有找到/i.test(html) &&
    !/panel-info/i.test(html)
  ) {
    return null;
  }
  if (!/panel-info/i.test(html) || !pageMentionsCode(html, code)) return null;

  const $ = cheerio.load(html);
  const panel = $(".panel-info").first();
  if (!panel.length) return null;

  const metaAfterBold = (lab: RegExp): string => {
    let found = "";
    panel.find("b").each((_, el) => {
      const name = stripTags($(el).text());
      if (!lab.test(name)) return;
      // <b>标签</b>: value<br> 或后接 a 链接
      let node: any = el.nextSibling;
      const parts: string[] = [];
      while (node) {
        if (node.type === "tag") {
          const tag = String(node.name || "").toLowerCase();
          if (tag === "br" || tag === "b") break;
          if (tag === "a") {
            const n = stripTags($(node).text());
            if (n) parts.push(n);
          } else {
            const n = stripTags($(node).text());
            if (n) parts.push(n);
          }
        } else if (node.type === "text") {
          const n = stripTags(String(node.data || ""));
          if (n && n !== ":") parts.push(n.replace(/^[:：]\s*/, ""));
        }
        node = node.nextSibling;
      }
      found = parts.join(" ").replace(/^[:：]\s*/, "").trim();
    });
    return found;
  };

  const snRaw = metaAfterBold(/品番|番號|番号|SN/i);
  const sn = stdCode(snRaw) || "";
  if (sn && sn !== code && sn.replace(/-/g, "") !== code.replace(/-/g, "")) {
    // 搜索偶发跳错号时丢弃
    if (!pageMentionsCode(panel.html() || "", code)) return null;
  }

  let title = cleanTitle(
    panel.find(".panel-heading h3").first().clone().children("small").remove().end().text() ||
      panel.find("h3").first().text() ||
      $("title").first().text().replace(/\s*bittorrent.*$/i, ""),
    code,
  );
  title = title
    .replace(/\s*bittorrent\s*Download\s*dmm\s*$/i, "")
    .replace(new RegExp(`\\b${code}\\b`, "ig"), "")
    .replace(/\s+/g, " ")
    .trim();
  if (isJunkTitle(title)) title = "";

  const actors = collectByRe(
    panel.html() || "",
    /href=["'][^"']*\/star\/[^"']+["'][^>]*>([^<]+)</gi,
  ).filter((n) => n && n.length < 40);

  const studio =
    collectByRe(
      panel.html() || "",
      /href=["'][^"']*\/company\/[^"']+["'][^>]*>([^<]+)</gi,
    )[0] ||
    metaAfterBold(/メーカー|片商|Maker/i) ||
    "";

  const genres = collectByRe(
    panel.html() || "",
    /href=["'][^"']*\/genre\/[^"']+["'][^>]*>([^<]+)</gi,
  )
    .filter((n) => n && n.length < 40 && !/ジャンル|类别|類型/i.test(n))
    .slice(0, 40);

  const series =
    collectByRe(
      panel.html() || "",
      /href=["'][^"']*\/series\/\d+[^"']*["'][^>]*>([^<]+)</gi,
    )[0] ||
    metaAfterBold(/シリーズ|系列|Series/i) ||
    "";

  let premiered = "";
  const dateRaw = metaAfterBold(/配信開始日|發行日期|发行日期|Release\s*Date|発売日/i);
  const dm = dateRaw.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const runtimeRaw = metaAfterBold(/収録時間|播放時長|播放时长|Play\s*time|Runtime/i);
  const runtime =
    Number(runtimeRaw.match(/(\d+)\s*(?:minutes?|分|分钟|分鐘)?/i)?.[1] || 0) ||
    null;

  const ratingRaw = metaAfterBold(/平均評価|評分|评分|Rating/i);
  const userRating =
    Number(String(ratingRaw).match(/([0-9]+(?:\.[0-9]+)?)/)?.[1] || 0) || null;

  // 简介：详情区 col-md-12 正文；去掉特集/广告/章节小标题
  let plot = "";
  panel.find(".row .col-md-12").each((_, el) => {
    const $el = $(el);
    if ($el.find("video,img").length) return;
    const clone = $el.clone();
    clone.find("script,h2,ul,p.mg-t6").remove();
    let t = stripTags(clone.text());
    t = t
      .replace(/※\s*配信方法によって[\s\S]*$/i, "")
      .replace(/特集[\s\S]*$/i, "")
      .replace(/(?:（\d+）[^\s（]{0,40}\s*)+$/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (t.length < 20) return;
    if (t.length > plot.length) plot = t;
  });
  if (plot.length < 20 || isJunkTitle(plot)) plot = "";

  // 封面：无 og:image；优先 pl 大图，其次 panel 首图 ps
  const tidyUrl = (u: string) =>
    u.replace(/^(https?:)\/+/i, "$1//").replace(/([^:/])\/{2,}/g, "$1/");
  let cover: string | null = null;
  let portrait: string | null = null;
  const posterAttr =
    panel.find("video[poster]").attr("poster") ||
    html.match(/poster=["']([^"']+pl\.jpg[^"']*)["']/i)?.[1] ||
    "";
  const panelImg =
    panel.find(".col-md-3 img.img-responsive").first().attr("src") ||
    panel.find("img.img-responsive").first().attr("src") ||
    "";
  if (posterAttr) cover = absUrl(tidyUrl(posterAttr), base);
  if (panelImg) {
    const u = absUrl(tidyUrl(panelImg), base);
    if (u && /ps\.jpg/i.test(u)) portrait = u;
    if (!cover) cover = u;
  }
  // 只有竖图 ps 时升级横版 pl（DMM 惯例）
  if (cover && /ps\.jpg/i.test(cover)) {
    if (!portrait) portrait = cover;
    cover = cover.replace(/ps\.jpg/i, "pl.jpg");
  }
  if (cover && isJunkCoverUrl(cover)) cover = null;
  if (portrait && isJunkCoverUrl(portrait)) portrait = null;

  const cidHint =
    extractDmmCidFromUrl(cover || portrait || "") ||
    String(cover || portrait || "").match(
      /\/digital\/video\/([a-z0-9_]+)\//i,
    )?.[1]?.toLowerCase() ||
    "";

  const fanartRaw = [
    ...html.matchAll(
      /src=["'](https?:\/\/[^"']+\/digital\/video\/([^/"']+)\/([^/"']+jp-\d+\.jpg))["']/gi,
    ),
  ].filter((m) => {
    if (!cidHint) return true;
    return String(m[2] || "").toLowerCase() === cidHint;
  });
  // 同图常有 DMM + jav321 镜像各一份，按文件名去重并优先 pics.dmm
  const fanartByName = new Map<string, string>();
  for (const m of fanartRaw) {
    const name = String(m[3] || "").toLowerCase();
    const u = absUrl(m[1], base);
    if (!name || !u || isJunkCoverUrl(u)) continue;
    const prev = fanartByName.get(name);
    if (!prev || (/pics\.dmm/i.test(u) && !/pics\.dmm/i.test(prev))) {
      fanartByName.set(name, u);
    }
  }
  const uniqFanart = [...fanartByName.values()].slice(0, 30);

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    plot: plot || undefined,
    actors: actors.slice(0, 20),
    genres: genres.length ? genres : undefined,
    studio: studio || undefined,
    makers: studio ? [studio] : undefined,
    series: series || undefined,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    userRating:
      userRating && userRating > 0 && userRating <= 10 ? userRating : null,
    poster: cover,
    portrait: portrait || undefined,
    fanart: uniqFanart.length ? uniqFanart : undefined,
    productId:
      extractDmmCidFromUrl(cover || portrait || "") || cidHint || undefined,
    source: "jav321",
  };
    },
  );
}

/**
 * MissAV（missav123 / 镜像）。在线站，强制 Flare。
 * 优先 /cn/{slug}：中文 UI；「标题」字段常为日文原名。落地会带 /dmNNN/ 前缀。
 */
export async function scrapeMissav(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  const slug = code.toLowerCase();
  return withSiteMirrorBase(
    "miss_av",
    opts?.baseUrl || "https://missav123.com",
    async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "");
  registerFlareHost(base);
  const paths = [
    `/cn/${slug}`,
    `/${code}`,
    `/${slug}`,
    `/en/${slug}`,
  ];

  for (const path of paths) {
    const url = `${base}${path}`;
    const page = await fetchPage(url, {
      referer: `${base}/`,
      sourceId: "miss_av",
      viaFlare: true,
      waitInSeconds: 2,
      timeoutMs: 90000,
    });
    const html = page?.html || "";
    const landed = page?.finalUrl || url;
    if (!html || html.length < 2000) continue;
    if (looksBlockedHtml(html)) continue;
    if (/的搜尋結果|的搜索结果|Search results/i.test($titleHint(html))) continue;
    if (/404|找不到|Not Found/i.test(html.slice(0, 2000)) && !/og:title/i.test(html)) {
      continue;
    }
    if (!pageMentionsCode(html, code) && !pageMentionsCode(html, slug)) continue;

    const $ = cheerio.load(html);
    const panel = (label: RegExp): { text: string; links: string[] } => {
      let text = "";
      const links: string[] = [];
      $(".space-y-2 .text-secondary, .text-secondary").each((_, el) => {
        const lab = stripTags($(el).find("span").first().text());
        if (!label.test(lab)) return;
        text = stripTags($(el).text().replace(lab, ""));
        $(el)
          .find("a")
          .each((__, a) => {
            const n = stripTags($(a).text());
            if (n && !links.includes(n)) links.push(n);
          });
      });
      return { text, links };
    };

    // 日文原名在「标题:」；h1/og 多为中文译名
    const jaTitle = cleanTitle(panel(/标题|標題|Title/i).text, code);
    let zhTitle = cleanTitle(
      $("h1").first().text() || pickOgTitle(html) || "",
      code,
    );
    zhTitle = zhTitle
      .replace(/\s*[-|｜]\s*MissAV.*$/i, "")
      .replace(/\s*[-|｜]\s*[^-|｜]{1,40}\s*$/u, (m) => {
        // 去掉末尾「 - 女优名」
        const name = m.replace(/^\s*[-|｜]\s*/, "");
        return /[\u4e00-\u9fff]/.test(name) && name.length <= 20 ? "" : m;
      })
      .trim();

    let title = jaTitle || zhTitle;
    if (!title || isJunkTitle(title) || /搜尋結果|搜索结果|免费高清AV/i.test(title)) {
      continue;
    }

    const actressRaw = panel(/女优|女優|Actress/i).links;
    const actors = actressRaw
      .map((n) => {
        const jp = n.match(/[（(]\s*([^）)]+)\s*[）)]/)?.[1]?.trim();
        return stripTags(jp || n.split(/[（(]/)[0] || "").trim();
      })
      .filter(
        (n) =>
          n &&
          n.length >= 1 &&
          n.length <= 40 &&
          !/女优|女優|排行|一览|一覧|收藏/i.test(n),
      );

    const genres = panel(/类型|類型|Genre/i)
      .links.filter(
        (g) =>
          g &&
          !/^(VR|4K|高清|独家|獨家|HD|FHD)$/i.test(g) &&
          g.length <= 20,
      )
      .slice(0, 20);

    const series = panel(/系列|Series/i).links[0] || "";
    const studio =
      panel(/发行商|發行商|Maker|メーカー/i).links[0] ||
      panel(/发行商|發行商/).text ||
      "";
    const publisher =
      panel(/标[签籤]|標籤|Label|レーベル/i).links[0] || undefined;
    const director = panel(/导演|導演|Director/i).links[0] || undefined;

    let premiered = "";
    const dt =
      $("time[datetime]").attr("datetime") ||
      panel(/发行日期|發行日期|Release/i).text;
    const dm = String(dt).match(/(\d{4})-(\d{2})-(\d{2})/);
    if (dm) premiered = `${dm[1]}-${dm[2]}-${dm[3]}`;

    let cover =
      pickOgImage(html) ||
      absUrl(
        html.match(
          new RegExp(
            `https?://[^"'\\s]*fourhoi\\.com/${slug}/cover[^"'\\s]*`,
            "i",
          ),
        )?.[0],
        landed,
      );
    if (cover) {
      // cover-n 缩略 → 尝试同路径 cover-n 保留（站方主图）
      cover = absUrl(cover, landed);
    }
    if (cover && isJunkCoverUrl(cover)) cover = null;

    let plot = stripTags(
      $('meta[property="og:description"]').attr("content") ||
        $('meta[name="description"]').attr("content") ||
        "",
    );
    if (
      plot.length < 40 ||
      isJunkTitle(plot) ||
      /MissAV|免费高清|在线看|線上看/i.test(plot.slice(0, 40))
    ) {
      plot = "";
    }

    const titleZh =
      zhTitle && isLikelyChinese(zhTitle)
        ? zhTitle
        : title && isLikelyChinese(title)
          ? title
          : undefined;

    return {
      code,
      title,
      titleZh,
      originalTitle: jaTitle || title,
      plot: plot || undefined,
      actors: actors.length ? [...new Set(actors)].slice(0, 12) : undefined,
      genres: genres.length ? genres : undefined,
      series: series || undefined,
      studio: studio || undefined,
      makers: studio ? [studio] : undefined,
      publisher,
      director,
      premiered: premiered || undefined,
      poster: cover,
      source: "miss_av",
    };
  }
  return null;
    },
  );
}

function $titleHint(html: string): string {
  return (
    html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] ||
    pickOgTitle(html) ||
    ""
  );
}

/**
 * 7MMTV（7mmtv.sx）。中文 UI 标题；搜索须 POST，或走 /zh/searchall_search/all/{CODE}/1.html。
 * 详情优先 censored_content，其次 chinese / amateurjav；reducing-mosaic 垫后。
 */
export async function scrape7mmtv(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase(
    "sevenmmtv",
    opts?.baseUrl || "https://7mmtv.sx",
    async (baseRaw) => {
  const root = baseRaw.replace(/\/$/, "").replace(/\/zh$/i, "");

  // 实测：代理 + curl 回退即可；强制过盾只会拉长排队
  const pageOpts = {
    sourceId: "sevenmmtv" as const,
    viaFlare: false as const,
    timeoutMs: 20000,
    strictTimeout: true,
  };

  const pickDetailHref = (html: string): string => {
    const hrefs = [
      ...html.matchAll(
        /href=["']([^"']*\/(?:censored|chinese|amateurjav|uncensored|reducing-mosaic|amateur)_content\/\d+\/[^"']+)["']/gi,
      ),
    ].map((m) => m[1]!);
    const scored = [...new Set(hrefs)].map((h) => {
      let score = 0;
      if (/censored_content/i.test(h) && !/reducing/i.test(h)) score += 50;
      if (/chinese_content/i.test(h)) score += 40;
      if (/amateurjav_content/i.test(h)) score += 30;
      if (/uncensored_content/i.test(h)) score += 20;
      if (/reducing-mosaic/i.test(h)) score += 5;
      const codeRe = code.replace(/-/g, "[-]?");
      if (new RegExp(codeRe, "i").test(h)) score += 20;
      return { h, score };
    });
    scored.sort((a, b) => b.score - a.score);
    return scored[0]?.h || "";
  };

  let detailPath = "";
  // 1) GET 结果页（站点 SEO 路径）
  for (const searchUrl of [
    `${root}/zh/searchall_search/all/${encodeURIComponent(code)}/1.html`,
    `${root}/zh/searchform_search/all/${encodeURIComponent(code)}/1.html`,
  ]) {
    const page = await fetchPage(searchUrl, {
      ...pageOpts,
      referer: `${root}/zh/`,
    });
    const html = page?.html || "";
    if (!html || looksBlockedHtml(html)) continue;
    detailPath = pickDetailHref(html);
    if (detailPath) break;
  }

  // 2) POST 表单搜索（GET 空结果时；仍走 undici，失败则放弃）
  if (!detailPath) {
    const body = new URLSearchParams({
      search_keyword: code,
      search_type: "searchall",
      op: "search",
    }).toString();
    const searchHtml = await fetchPostForm(
      `${root}/zh/searchform_search/all/index.html`,
      body,
      {
        referer: `${root}/zh/`,
        sourceId: "sevenmmtv",
        timeoutMs: 20000,
      },
    );
    if (searchHtml && !looksBlockedHtml(searchHtml)) {
      detailPath = pickDetailHref(searchHtml);
    }
  }
  if (!detailPath) return null;

  const detailUrl = absUrl(detailPath, root);
  if (!detailUrl) return null;
  const detailPage = await fetchPage(detailUrl, {
    ...pageOpts,
    referer: `${root}/zh/`,
  });
  const html = detailPage?.html || "";
  const landed = detailPage?.finalUrl || detailUrl;
  if (!html || looksBlockedHtml(html)) return null;
  if (!pageMentionsCode(html, code)) return null;

  const $ = cheerio.load(html);
  let title = cleanTitle(
    $("h1.fullvideo-title, h1").first().text() || pickOgTitle(html) || "",
    code,
  );
  title = title.replace(/\s*[-|｜]\s*7mmtv.*$/i, "").trim();
  if (!title || isJunkTitle(title) || /Watch JAV Online|^搜索/i.test(title)) {
    return null;
  }

  const actors = $(".fullvideo-idol a, a[href*='_avperformer/']")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter((n) => n && n.length <= 40 && !/女優|女优|演員/i.test(n));
  const uniqActors = [...new Set(actors)].slice(0, 12);

  const genres = $(".categories a, a[href*='_category/']")
    .map((_, el) => stripTags($(el).text()))
    .get()
    .filter(
      (g) =>
        g &&
        g.length <= 20 &&
        !/高畫質|高清|DMM獨家|切卡|VR|4K/i.test(g),
    )
    .slice(0, 20);

  const attrValue = (label: RegExp): string => {
    let out = "";
    $(".fullvideo-attr .row, .fullvideo-attr").each((_, el) => {
      const lab = stripTags($(el).find("strong").first().text());
      if (!label.test(lab)) return;
      const $col = $(el).children().eq(1);
      out =
        stripTags($col.find("a").first().text()) ||
        stripTags($col.text()) ||
        stripTags($(el).find("a").first().text()) ||
        out;
    });
    return out;
  };

  const publisher = attrValue(/發行商|发行商|Issuer/i) || undefined;
  const studio = attrValue(/製作商|制作商|Maker|メーカー/i) || undefined;
  const director = attrValue(/導演|导演|Director/i) || undefined;

  let premiered = "";
  let runtime: number | null = null;
  $(".fullvideo-details .text-muted, .d-flex .text-muted").each((_, el) => {
    const t = stripTags($(el).text());
    const dm = t.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (dm) premiered = `${dm[1]}-${dm[2]}-${dm[3]}`;
    const rm = t.match(/(\d+)\s*分/);
    if (rm) runtime = Number(rm[1]) || null;
  });

  let cover =
    $(".content_main_cover img").attr("src") ||
    $(".mvspan_2_s_k_i_p_cover img").attr("src") ||
    pickOgImage(html);
  if (cover) cover = absUrl(cover, landed);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart = $("img.lazyload[data-src*='pics.dmm'], img[data-src*='digital/video']")
    .map((_, el) => String($(el).attr("data-src") || "").trim())
    .get()
    .filter((u) => /^https?:\/\//i.test(u))
    .slice(0, 20);

  return {
    code,
    title,
    // 7mm 中文站标题默认可用，不做语种/质量拦截
    titleZh: title && !isJunkTitle(title) ? title : undefined,
    originalTitle: title,
    actors: uniqActors.length ? uniqActors : undefined,
    genres: genres.length ? genres : undefined,
    publisher,
    studio,
    makers: studio ? [studio] : undefined,
    director,
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    poster: cover,
    fanart: fanart.length ? fanart : undefined,
    source: "sevenmmtv",
  };
    },
  );
}

/** iQQTV：中文标题快源；镜像常换（iqq5 → iqqk4 等），自动跟跳转。 */
function normalizeIqqtvBase(raw?: string): string {
  return normalizeIqqtvRoot(raw || "") || "https://iqq5.xyz";
}

function iqqtvJunkTitle(title: string): boolean {
  return /克破|无码破解|無碼破解|无码流出|無碼流出|马赛克破坏|馬賽克破壞/i.test(
    title,
  );
}

async function scrapeIqqtvOnce(
  code: string,
  root: string,
): Promise<PartialFromSource | null> {
  const cnBase = `${root}/cn`;

  const searchUrl = `${cnBase}/search.php?kw=${encodeURIComponent(code)}`;
  const searchPage = await fetchPage(searchUrl, {
    referer: `${cnBase}/`,
    sourceId: "iqqtv",
    viaFlare: false,
    timeoutMs: 20000,
  });
  const searchHtml = searchPage?.html || "";
  if (!searchHtml || searchHtml.length < 400) return null;
  if (looksBlockedHtml(searchHtml) && searchHtml.length < 8000) return null;

  const landedRoot =
    normalizeIqqtvRoot(searchPage?.finalUrl || "") || root;
  if (landedRoot && landedRoot !== root) {
    rememberIqqtvMirror(landedRoot, root);
  }
  const effectiveCn = `${landedRoot}/cn`;

  const $s = cheerio.load(searchHtml);
  let detailPath = "";
  const codeRe = new RegExp(code.replace(/-/g, "[-_]?"), "i");
  const consider = (href: string, title: string) => {
    if (detailPath || !href) return;
    const hay = `${href} ${title}`;
    if (!codeRe.test(hay)) return;
    if (iqqtvJunkTitle(hay)) return;
    if (!/player\.php/i.test(href)) return;
    detailPath = href;
  };
  // ga_click 常是时长链（title=02:25:05）；番号多在 a.ga_name / span.title a
  $s("span.title a, a.ga_name, a.ga_click").each((_, el) => {
    const href = String($s(el).attr("href") || "");
    const title = String(
      $s(el).attr("title") || $s(el).text() || "",
    ).trim();
    consider(href, title);
  });
  if (!detailPath) {
    $s("a[href*='player.php']").each((_, el) => {
      const href = String($s(el).attr("href") || "");
      const title = String(
        $s(el).attr("title") || $s(el).text() || "",
      ).trim();
      consider(href, title);
    });
  }
  if (!detailPath) return null;

  let detailUrl = absUrl(detailPath, `${effectiveCn}/`);
  if (!detailUrl) return null;
  // 统一走 /cn/ 详情拿中文题
  detailUrl = detailUrl
    .replace(/\/jp\//i, "/cn/")
    .replace(/^(https?:\/\/[^/]+)\/(?!cn\/)/i, `$1/cn/`);
  if (!/\/cn\//i.test(detailUrl) && /player\.php/i.test(detailUrl)) {
    detailUrl = detailUrl.replace(
      /^(https?:\/\/[^/]+)\/(.*)$/i,
      `$1/cn/$2`,
    );
  }

  const detailPage = await fetchPage(detailUrl, {
    referer: searchUrl,
    sourceId: "iqqtv",
    viaFlare: false,
    timeoutMs: 20000,
  });
  const html = detailPage?.html || "";
  if (!html || html.length < 800) return null;
  if (looksBlockedHtml(html) && html.length < 8000) return null;
  if (!pageMentionsCode(html, code)) return null;

  const detailLanded = normalizeIqqtvRoot(detailPage?.finalUrl || "");
  if (detailLanded && detailLanded !== landedRoot) {
    rememberIqqtvMirror(detailLanded, landedRoot);
  }

  const $ = cheerio.load(html);
  let title = cleanTitle(
    $("h1.h4.b").first().text() || pickOgTitle(html),
    code,
  );
  title = title
    .replace(/\s*iQQTV\s*.*$/i, "")
    .replace(new RegExp(`\\s*${code.replace(/-/g, "[-_]?")}\\s*$`, "i"), "")
    .trim();
  if (!title || isJunkTitle(title) || iqqtvJunkTitle(title)) return null;

  const actors: string[] = [];
  $('a[href*="s_type=actor"] span[itemprop="name"], a[href*="actor"] span').each(
    (_, el) => {
      const n = stripTags($(el).text());
      if (n && n.length < 40 && !actors.includes(n)) actors.push(n);
    },
  );

  const genres: string[] = [];
  $(".tag-info a[href*='s_type=tag'], a[href*='s_type=tag']").each((_, el) => {
    const n = stripTags($(el).text());
    if (
      !n ||
      n.length > 24 ||
      /更多|全部|类别/i.test(n) ||
      genres.includes(n)
    ) {
      return;
    }
    genres.push(n);
  });

  let studio = stripTags(
    $('a[href*="s_type=fac"] [itemprop="name"], a[href*="s_type=fac"] .company')
      .first()
      .text(),
  );
  if (studio.length > 60) studio = "";

  let series = stripTags(
    $('a[href*="s_type=series"]').first().text(),
  );
  if (series.length < 2 || isJunkTitle(series)) series = "";

  let plot = "";
  $("p").each((_, el) => {
    if (plot) return;
    const t = stripTags($(el).text());
    if (/^(简|簡)介[：:]/.test(t) || t.includes("简介：") || t.includes("簡介：")) {
      plot = t
        .replace(/^(简|簡)介[：:]\s*/, "")
        .split("*根据分发")[0]
        .trim();
    }
  });
  if (plot.length < 12 || isJunkTitle(plot) || iqqtvJunkTitle(plot)) plot = "";

  let premiered = stripTags($("div.date").first().text()).replace(
    /\//g,
    "-",
  );
  const dm = premiered.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  premiered = dm
    ? `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`
    : "";

  const poster =
    pickOgImage(html) ||
    absUrl($('img[itemprop="image"]').first().attr("src"), detailUrl);

  const titleZh = !isJunkTitle(title) ? title : undefined;

  return {
    code,
    title: titleZh || title,
    titleZh,
    plot: plot || undefined,
    actors: actors.length ? actors : undefined,
    genres: genres.length ? genres : undefined,
    studio: studio || undefined,
    series: series || undefined,
    premiered: premiered || undefined,
    poster: poster || null,
    source: "iqqtv",
  };
}

export async function scrapeIqqtv(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  const preferred = normalizeIqqtvBase(opts?.baseUrl);
  let root = await resolveIqqtvRoot({ preferred });
  let parsed = await scrapeIqqtvOnce(code, root);
  if (!parsed) {
    invalidateIqqtvMirror();
    root = await resolveIqqtvRoot({ preferred, forceRefresh: true });
    parsed = await scrapeIqqtvOnce(code, root);
  }
  return parsed;
}

export async function scrapeFreejavbt(codeRaw: string): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  return withSiteMirrorBase("freejavbt", "https://freejavbt.com", async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "") || "https://freejavbt.com";
  // 裸数字会误跳（如 4821288→48212-88）；FC2 用完整番号
  const slugs = [code];
  const fc2 = code.match(/FC2[-_]?PPV[-_]?(\d+)/i) || code.match(/^FC2[-_]?(\d+)$/i);
  if (fc2) {
    slugs.unshift(`FC2-PPV-${fc2[1]}`, `FC2-${fc2[1]}`);
  }
  const uniqSlugs = [...new Set(slugs.map((s) => s.trim()).filter(Boolean))];

  for (const slug of uniqSlugs) {
    // /zh/：类别中文；/ja/：类别日文；裸路径常 302 到 ja
    const paths = [
      `/zh/${encodeURIComponent(slug)}`,
      `/${encodeURIComponent(slug)}/`,
      `/ja/${encodeURIComponent(slug)}`,
    ];
    for (const path of paths) {
      const url = `${base}${path}`;
      const page = await fetchPage(url, {
        referer: `${base}/`,
        sourceId: "freejavbt",
        viaFlare: false,
        timeoutMs: 18000,
      });
      const html = page?.html || null;
      if (!html || html.length < 2000) continue;
      if (
        /Just a moment|cf-browser-verification|Edge IP Restricted/i.test(html) &&
        html.length < 8000
      ) {
        continue;
      }
      // 软 404 / 推荐页：此 slug 无详情，换路径无意义
      if (
        /あなたは好きかもしれません|你可能喜欢|404|找不到|Not Found/i.test(html) &&
        !pageMentionsCode(html, code) &&
        !pageMentionsCode(html, slug)
      ) {
        return null;
      }
      if (!pageMentionsCode(html, code) && !pageMentionsCode(html, slug)) {
        continue;
      }
      const landed = page?.finalUrl || url;
      const landOk =
        new RegExp(code.replace(/-/g, "[-_]?"), "i").test(landed) ||
        new RegExp(String(slug).replace(/-/g, "[-_]?"), "i").test(landed);
      if (!landOk) continue;

      const $ = cheerio.load(html);
      if (!$(".single-video-meta").length && !pickOgImage(html)) continue;

      const metaByLabel = (re: RegExp): { text: string; links: string[] } => {
        let text = "";
        const links: string[] = [];
        $(".single-video-meta").each((_, el) => {
          const $el = $(el);
          const lab = stripTags($el.children("span").first().text());
          if (!re.test(lab)) return;
          $el.find("a").each((__, a) => {
            const n = stripTags($(a).text());
            if (n && n.length < 60 && !links.includes(n)) links.push(n);
          });
          const spans = $el.children("span");
          if (spans.length >= 2) {
            text = stripTags(spans.last().text());
          } else {
            const clone = $el.clone();
            clone.children("span").first().remove();
            text = stripTags(clone.text());
          }
        });
        return { text, links };
      };

      let title = cleanTitle(
        $("h1").first().text() || pickOgTitle(html),
        code,
      );
      title = title
        .replace(/\s*(免费AV在线看|無料で見る|在线看)\s*$/i, "")
        .replace(new RegExp(`^${code}\\s+`, "i"), "")
        .trim();
      if (isJunkTitle(title) || /あなたは好きかもしれません|你可能喜欢/i.test(title)) {
        title = "";
      }

      const dateMeta = metaByLabel(/日期|発売日|公開日/);
      let premiered = "";
      const dm = (dateMeta.text || dateMeta.links.join(" ")).match(
        /(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/,
      );
      if (dm) {
        premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
      }

      const runtimeMeta = metaByLabel(/时长|収録時間|再生時間/);
      const runtime =
        Number(
          (runtimeMeta.text || "").match(/(\d+)\s*(?:分|分钟|分鐘)/)?.[1] || 0,
        ) || null;

      const director =
        metaByLabel(/导演|導演|監督/).links[0] ||
        metaByLabel(/导演|導演|監督/).text ||
        "";
      const series =
        metaByLabel(/系列|シリーズ/).links[0] ||
        metaByLabel(/系列|シリーズ/).text ||
        "";

      const genreMeta = metaByLabel(/类别|類別|ジャンル|类型|類型/);
      const genres = genreMeta.links
        .filter((n) => !/同一|動画|视频|更多/i.test(n))
        .slice(0, 40);

      const actorMeta = metaByLabel(/女优|女優|演员|演員/);
      const actors = actorMeta.links
        .filter(
          (n) =>
            !/同一|ランキング|有修正|無修正|西洋|動画|作品|在线看|線上|下载|下載|同女优|同主题|同主題/i.test(
              n,
            ) &&
            n.length >= 2 &&
            n.length < 40,
        )
        .slice(0, 20);

      const cover = pickFreejavbtCover($, html, landed, code);

      if (!title && !cover && !genres.length && !actors.length) continue;

      return {
        code,
        title: title || "",
        originalTitle: title || "",
        genres,
        actors,
        director: director || undefined,
        series: series || undefined,
        premiered: premiered || undefined,
        runtime: runtime && runtime > 0 ? runtime : undefined,
        // 封面不可靠（播放器截帧 / 推荐位串号），禁止作封面源
        poster: null,
        source: "freejavbt",
      };
    }
  }
  return null;
  });
}

/**
 * Airav Wiki。实站已 302→airav.io（/video?jid=番号）；与 airav_io 同源不同入口。
 * 强制 Flare；解析复用 airav.io 详情结构。
 */
export async function scrapeAiravWiki(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;

  // 与 airav_io 同源：wiki 入口常 302→airav.io；强制过盾只会拖死 deadline。
  // 优先走已验证的搜索 kw→hid；失败再试 wiki /video/{CODE}（代理+curl，不过盾）。
  const fromIo = await scrapeAiravIo(codeRaw, {
    baseUrl: "https://airav.io/cn",
  });
  if (fromIo?.title || fromIo?.poster) {
    return { ...fromIo, source: "airav" };
  }

  return withSiteMirrorBase(
    "airav",
    opts?.baseUrl || "https://www.airav.wiki",
    async (wikiRaw) => {
      const wikiBase = wikiRaw.replace(/\/$/, "");
      const page = await fetchPage(
        `${wikiBase}/video/${encodeURIComponent(code)}`,
        {
          referer: `${wikiBase}/`,
          sourceId: "airav",
          viaFlare: false,
          timeoutMs: 20000,
          strictTimeout: true,
        },
      );
      const html = page?.html || "";
      const landed = page?.finalUrl || `${wikiBase}/video/${code}`;
      if (!html || looksBlockedHtml(html)) return null;
      if (
        /找不到|404|Not Found|521:\s*Web server/i.test(html.slice(0, 2500)) &&
        !/video-title|og:title|番[号號]/i.test(html)
      ) {
        return null;
      }
      if (!airavDetailCodeOk(html, code) && !pageMentionsCode(html, code)) {
        return null;
      }
      const parsed = parseAiravIoDetail(html, landed, code);
      if (!parsed?.title && !parsed?.poster) return null;
      return { ...parsed, source: "airav" };
    },
  );
}

export async function scrapeAiravIo(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;

  const preferred = normalizeAiravCnBase(opts?.baseUrl || "") || undefined;
  let base = await resolveAiravCnBase({ preferred });
  const tryOnce = async (cnBase: string) => {
    const searchUrl = `${cnBase}/search_result?kw=${encodeURIComponent(code)}`;
    // 实测：代理直连即可；强制过盾只会拖死 deadline
    const searchPage = await fetchPage(searchUrl, {
      referer: `${cnBase}/`,
      sourceId: "airav_io",
      timeoutMs: 18000,
      viaFlare: false,
      strictTimeout: true,
    });
    if (!searchPage?.html) return null;

    // 搜索过程也可能跟到新镜像
    const landedBase =
      normalizeAiravCnBase(searchPage.finalUrl) || cnBase;
    if (landedBase && landedBase !== cnBase) {
      rememberAiravMirror(landedBase, cnBase);
    }
    const html = searchPage.html;
    const hidHref = pickAiravHidFromSearch(html, code);
    if (!hidHref) return null;

    const detailUrl =
      absUrl(hidHref, landedBase) ||
      absUrl(hidHref, searchPage.finalUrl) ||
      `${landedBase}${hidHref.startsWith("/") ? "" : "/"}${hidHref}`;
    const detailPage = await fetchPage(detailUrl, {
      referer: searchUrl,
      sourceId: "airav_io",
      timeoutMs: 18000,
      viaFlare: false,
      strictTimeout: true,
    });
    if (!detailPage?.html) return null;
    if (!airavDetailCodeOk(detailPage.html, code)) return null;
    return parseAiravIoDetail(detailPage.html, detailPage.finalUrl || detailUrl, code);
  };

  let parsed = await tryOnce(base);
  if (!parsed) {
    // 镜像可能过期：清缓存后重探一次
    invalidateAiravMirror();
    base = await resolveAiravCnBase({ preferred, forceRefresh: true });
    parsed = await tryOnce(base);
  }
  return parsed;
}

function pickAiravHidFromSearch(html: string, code: string): string | null {
  const codeRe = new RegExp(code.replace(/-/g, "[-_]?"), "i");
  // 卡片：oneVideo → video?hid → 邻近 h5 标题
  const blocks = [
    ...html.matchAll(
      /class=["'][^"']*oneVideo[^"']*["'][\s\S]{0,2000}?href=["']([^"']*\/video\?hid=[^"'#]+)["']([\s\S]{0,1200})/gi,
    ),
  ];
  for (const m of blocks) {
    const href = String(m[1] || "").trim();
    const h5 = stripTags(
      String(m[2] || "").match(/<h5[^>]*>([\s\S]*?)<\/h5>/i)?.[1] || "",
    );
    const chunk = `${href} ${h5} ${String(m[2] || "").slice(0, 400)}`;
    if (href && codeRe.test(h5 || chunk)) return href;
  }
  // 标题行优先：h5 含番号时回溯最近 hid
  for (const m of html.matchAll(/<h5[^>]*>([\s\S]*?)<\/h5>/gi)) {
    const h5 = stripTags(m[1] || "");
    if (!codeRe.test(h5)) continue;
    const before = html.slice(Math.max(0, (m.index || 0) - 800), m.index || 0);
    const href = before.match(/href=["']([^"']*\/video\?hid=[^"'#]+)["'][^>]*>\s*$/i)?.[1]
      || [...before.matchAll(/href=["']([^"']*\/video\?hid=[^"'#]+)["']/gi)].pop()?.[1];
    if (href) return href;
  }
  return null;
}

function airavDetailCodeOk(html: string, code: string): boolean {
  const codeRe = new RegExp(`^${code.replace(/-/g, "[-_]?")}$`, "i");
  const span = html.match(/番[号號]\s*[：:]\s*<span[^>]*>([^<]+)<\/span>/i)?.[1];
  if (span && codeRe.test(stripTags(span))) return true;
  const h1 = stripTags(
    html.match(/<div[^>]*class=["'][^"']*video-title[^"']*["'][^>]*>[\s\S]*?<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ||
      html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ||
      "",
  );
  if (h1 && new RegExp(`^${code.replace(/-/g, "[-_]?")}\\b`, "i").test(h1)) {
    return true;
  }
  const og = pickOgTitle(html);
  if (og && new RegExp(`^${code.replace(/-/g, "[-_]?")}\\b`, "i").test(og)) {
    return true;
  }
  return false;
}

function parseAiravIoDetail(
  html: string,
  pageUrl: string,
  code: string,
): PartialFromSource | null {
  if (/找不到|404|Not Found/i.test(html) && !/video-title|og:title|oneVideo/i.test(html)) {
    return null;
  }
  let title = cleanTitle(
    html.match(/<div[^>]*class=["'][^"']*video-title[^"']*["'][^>]*>[\s\S]*?<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ||
      pickOgTitle(html),
    code,
  )
    .replace(/\s*[-–—]\s*airav(?:\.io)?\s*$/i, "")
    .trim();
  if (isJunkTitle(title)) title = "";

  let cover = pickOgImage(html);
  if (cover) cover = absUrl(cover, pageUrl);
  if (isJunkCoverUrl(cover)) cover = null;
  // 搜索/详情封面常见 /storage/cover/
  if (!cover) {
    const m = html.match(
      /(https?:\/\/[^"'>\s]+\/storage\/cover\/(?:big\/)?[^"'>\s]+\.(?:jpg|jpeg|png|webp))/i,
    );
    if (m?.[1] && !isJunkCoverUrl(m[1])) cover = m[1];
  }

  // 详情页：/actor?id=；旧站：/actress/…；勿匹配导航 /actors
  const actors = [
    ...collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?actor\?id=\d+["'][^>]*>([^<]+)</gi,
    ),
    ...collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?actress\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
    ...(() => {
      const block =
        html.match(/女[优優]\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/女[优優]\s*[：:]([\s\S]*?)<\/div>/i)?.[1] ||
        "";
      return collectByRe(block, />([^<]{1,40})</g).filter(
        (n) => n && !/女[优優]|演员|詳|详情|一覽|一览/i.test(n),
      );
    })(),
  ];
  const uniqActors = [
    ...new Set(
      actors
        .map((a) => a.trim())
        .filter(
          (a) =>
            a &&
            a.length <= 40 &&
            !/女[优優]|一覽|一览|發行|发行|factories/i.test(a),
        ),
    ),
  ].slice(0, 20);

  const genres = [
    ...(() => {
      const block =
        html.match(/標[签籤]\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/标[签籤]\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        "";
      return collectByRe(
        block,
        /href=["'][^"']*\/(?:cn\/)?tag\?tid=[^"']*["'][^>]*>([^<]+)</gi,
      );
    })(),
    ...collectByRe(
      html,
      /href=["'][^"']*\/(?:cn\/)?(?:genre|genres)\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
  ]
    .map((g) => g.trim())
    .filter(
      (g) =>
        g &&
        !/更多|全部|标签|標籤|類型|类型|一覽|一览|VR|720p|1080p|HD高畫質|AV女優片|中文/i.test(
          g,
        ) &&
        !isJunkTitle(g),
    );
  const uniqGenres = [...new Set(genres)].slice(0, 40);

  // 详情「廠商」用 /tag?fid=；导航「發行商」勿当 studio
  let studio =
    stripTags(
      html.match(/廠商\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/厂商\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/發行商\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/发行商\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(
          /href=["'][^"']*\/(?:cn\/)?tag\?fid=\d+["'][^>]*>([^<]+)</i,
        )?.[1] ||
        html.match(
          /href=["'][^"']*\/(?:cn\/)?factory(?:\/|\?[^"']*)["'][^>]*>([^<]+)</i,
        )?.[1] ||
        "",
    ) || "";
  if (studio.length < 2 || /一覽|一览|發行商|发行商|廠商|厂商/i.test(studio)) {
    studio = "";
  }

  let series =
    stripTags(
      html.match(/系列\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(/シリーズ\s*[：:]([\s\S]*?)<\/li>/i)?.[1] ||
        html.match(
          /href=["'][^"']*\/(?:cn\/)?series\/[^"']+["'][^>]*>([^<]+)</i,
        )?.[1] ||
        "",
    ) || "";
  if (series.length < 2 || isJunkTitle(series)) series = "";

  let plot =
    stripTags(
      html.match(
        /property=["']og:description["']\s+content=["']([^"']+)["']/i,
      )?.[1] ||
        html.match(
          /content=["']([^"']+)["']\s+property=["']og:description["']/i,
        )?.[1] ||
        "",
    ) || "";
  if (plot.length < 12 || isJunkTitle(plot)) plot = "";

  if (!title && !cover && !uniqActors.length && !plot && !uniqGenres.length && !series) {
    return null;
  }

  // airav 中文站标题默认可用，不做语种/质量拦截
  const titleZh = title && !isJunkTitle(title) ? title : "";
  return {
    code,
    title: title || "",
    titleZh: titleZh || undefined,
    originalTitle: title || "",
    plot,
    actors: uniqActors,
    genres: uniqGenres,
    series: series || undefined,
    studio: studio || undefined,
    makers: studio ? [studio] : undefined,
    poster: cover,
    productId: extractDmmCidFromUrl(cover) || undefined,
    source: "airav_io",
  };
}

export async function scrapeCarib(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  const m =
    code.match(/^(\d{6})[-_](\d{3})$/) || code.match(/^CARIB[-_]?(.+)$/i);
  if (!m) return null;
  const key = /CARIB/i.test(String(m[0] || ""))
    ? String(m[1] || "").replace(/_/g, "-")
    : `${m[1]}-${m[2]}`;
  const base = (
    opts?.baseUrl || "https://www.caribbeancom.com"
  ).replace(/\/$/, "");
  // 官方路径用连字符；下划线变体会 404
  const url = `${base}/moviepages/${key}/index.html`;
  const page = await fetchPage(url, {
    referer: `${base}/`,
    sourceId: "carib",
    timeoutMs: 25000,
  });
  const html = page?.html || "";
  if (!html) return null;
  if (
    (/404|見つかりません|Not Found/i.test(html.slice(0, 2500)) ||
      page?.finalUrl?.includes("404")) &&
    !/<h1[\s>]|itemprop=["']name["']/i.test(html)
  ) {
    return null;
  }

  let title = cleanTitle(
    html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ||
      html.match(
        /itemprop=["']name["'][^>]*>([\s\S]*?)<\//i,
      )?.[1] ||
      pickOgTitle(html) ||
      html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1],
    code,
  )
    .replace(/\s*[|｜].*$/, "")
    .replace(/\s*無修正アダルト.*$/i, "")
    .trim();
  if (isJunkTitle(title)) title = "";
  if (title && !/[\u3040-\u30ff\u4e00-\u9fff]/.test(title)) title = "";

  const actorBlock =
    html.match(
      /class=["']spec-title["'][^>]*>\s*出演\s*<\/span>[\s\S]*?class=["']spec-content["'][^>]*>([\s\S]*?)<\/span>\s*<\/li>/i,
    )?.[1] || "";
  const actors = [
    ...collectByRe(
      actorBlock,
      /itemprop=["']name["'][^>]*>([^<]+)</gi,
    ),
    ...collectByRe(
      actorBlock,
      /href=["'][^"']*\/search_act\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
  ]
    .map((a) => a.trim())
    .filter((a) => a && a.length <= 40 && !/出演|再生|シリーズ/i.test(a));
  const uniqActors = [...new Set(actors)].slice(0, 20);

  const specVal = (label: string): string => {
    const re = new RegExp(
      `class=["']spec-title["'][^>]*>\\s*${label}\\s*<\\/span>[\\s\\S]*?class=["']spec-content["'][^>]*>([\\s\\S]*?)<\\/span>\\s*<\\/li>`,
      "i",
    );
    return stripTags(html.match(re)?.[1] || "");
  };

  let series = specVal("シリーズ");
  if (series.length < 2 || isJunkTitle(series) || series === "-") series = "";

  const tagBlock =
    html.match(
      /class=["']spec-title["'][^>]*>\s*タグ\s*<\/span>[\s\S]*?class=["']spec-content["'][^>]*>([\s\S]*?)<\/span>\s*<\/li>/i,
    )?.[1] || "";
  const genres = [
    ...collectByRe(
      tagBlock,
      /(?:class=["'][^"']*spec(?:__tag|-item)[^"']*["'][^>]*>|itemprop=["']genre["'][^>]*>)([^<]+)</gi,
    ),
    ...collectByRe(
      tagBlock,
      /href=["'][^"']*\/listpages\/[^"']+["'][^>]*>([^<]+)</gi,
    ),
  ]
    .map((g) => g.trim())
    .filter((g) => g && !isJunkTitle(g) && g.length < 40);
  const uniqGenres = [...new Set(genres)].slice(0, 40);

  const durationRaw = specVal("再生時間");
  let runtime: number | null = null;
  const hm = durationRaw.match(/(?:(\d+):)?(\d+):(\d+)/);
  if (hm) {
    const h = Number(hm[1] || 0);
    const mi = Number(hm[2] || 0);
    const s = Number(hm[3] || 0);
    runtime = h * 60 + mi + (s >= 30 ? 1 : 0);
    if (runtime <= 0) runtime = null;
  }

  let premiered =
    specVal("配信日").slice(0, 10) ||
    html.match(
      /itemprop=["']datePublished["'][^>]*content=["']([^"']+)/i,
    )?.[1]?.slice(0, 10) ||
    "";
  if (!/^\d{4}-\d{2}-\d{2}/.test(premiered)) premiered = "";

  let plot =
    stripTags(
      html.match(
        /itemprop=["']description["'][^>]*>([\s\S]*?)<\//i,
      )?.[1] ||
        html.match(
          /name=["']description["']\s+content=["']([^"']+)["']/i,
        )?.[1] ||
        "",
    ) || "";
  // meta description 常夹带站务套话，过短或套话则弃
  if (
    plot.length < 20 ||
    /定額料金で見放題|無料サンプルや画像ギャラリー/i.test(plot)
  ) {
    plot = stripTags(
      html.match(
        /itemprop=["']description["'][^>]*>([\s\S]*?)<\//i,
      )?.[1] || "",
    );
    if (
      plot.length < 20 ||
      /定額料金で見放題|無料サンプルや画像ギャラリー/i.test(plot)
    ) {
      plot = "";
    }
  }

  let cover =
    absUrl(`/moviepages/${key}/images/l_l.jpg`, base) ||
    `${base}/moviepages/${key}/images/l_l.jpg`;
  const og = pickOgImage(html);
  if (og) cover = absUrl(og, url) || cover;
  const inline = html.match(
    new RegExp(
      `(?:src|href)=["']([^"']*moviepages/${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/images/l_l\\.jpg[^"']*)["']`,
      "i",
    ),
  )?.[1];
  if (inline) cover = absUrl(inline, url) || cover;
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart = [
    ...html.matchAll(
      new RegExp(
        `(?:src|href)=["']([^"']*moviepages/${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/images/l/\\d+\\.jpg[^"']*)["']`,
        "gi",
      ),
    ),
  ]
    .map((x) => absUrl(x[1], url))
    .filter(
      (u): u is string =>
        Boolean(u) && !isJunkCoverUrl(u) && !/\/member\//i.test(u),
    );
  const uniqFanart = [...new Set(fanart)].slice(0, 30);

  if (!title && !cover && !uniqActors.length && !plot) return null;

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    plot,
    actors: uniqActors,
    genres: uniqGenres,
    series: series || undefined,
    studio: "カリビアンコム",
    makers: ["カリビアンコム"],
    runtime,
    premiered: premiered || undefined,
    poster: cover,
    fanart: uniqFanart.length ? uniqFanart : undefined,
    source: "carib",
  };
}

export async function scrapeFc2Official(codeRaw: string): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  const m = code.match(/FC2[-_]?PPV[-_]?(\d+)/i) || code.match(/FC2[-_]?(\d+)/i);
  if (!m) return null;
  const id = m[1]!;
  const displayCode = `FC2-PPV-${id}`;
  const base = "https://adult.contents.fc2.com";
  const url = `${base}/article/${id}/`;
  const page = await fetchPage(url, {
    referer: `${base}/`,
    sourceId: "fc2",
    timeoutMs: 28000,
  });
  const html = page?.html || null;
  if (!html) return null;
  if (
    /未找到您要找的商品|お探しの商品は見つかりません|この商品は販売を終了|お探しの商品が見つかりませんでした/i.test(
      html,
    )
  ) {
    return null;
  }

  const $ = cheerio.load(html);
  let title = cleanTitle(
    pickOgTitle(html) ||
      $("meta[property='og:title']").attr("content") ||
      $("h2.items_article_Title, .items_article_headerInfo h2, h1").first().text(),
    displayCode,
  );
  title = cleanTitle(title, code);
  title = title
    .replace(new RegExp(`^FC2[-_]?PPV[-_]?${id}\\s*[-–—:]?\\s*`, "i"), "")
    .trim();
  if (
    !title ||
    /未找到您要找的商品|お探しの商品は見つかりません|販売を終了|見つかりませんでした/i.test(
      title,
    )
  ) {
    return null;
  }

  let cover =
    pickOgImage(html) ||
    $(".items_article_MainitemThumb img").attr("src") ||
    $(".items_article_MainitemThumb img").attr("data-src") ||
    null;
  if (cover) cover = absUrl(cover, url);

  const genres: string[] = [];
  $(".items_article_TagArea a, a[href*='tag']").each((_, el) => {
    const n = stripTags($(el).text());
    if (
      !n ||
      n.length > 40 ||
      /もっと見る|タグ|ジャンル|FC2/i.test(n) ||
      genres.includes(n)
    ) {
      return;
    }
    genres.push(n);
  });

  const seller =
    stripTags(
      $('.items_article_headerInfo a[href*="/users/"]').first().text() ||
        $('a[href*="/users/"]').first().text() ||
        "",
    ) || "";

  let premiered = "";
  const saleText =
    $(".items_article_headerInfo").text() ||
    html.match(/販売日\s*[:：]\s*([0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2})/i)?.[0] ||
    "";
  const saleM = String(saleText).match(
    /販売日\s*[:：]?\s*([0-9]{4})[/-]([0-9]{1,2})[/-]([0-9]{1,2})/i,
  );
  if (saleM) {
    premiered = `${saleM[1]}-${saleM[2]!.padStart(2, "0")}-${saleM[3]!.padStart(2, "0")}`;
  }

  let plot =
    stripTags(
      $("meta[property='og:description']").attr("content") ||
        $("meta[name='description']").attr("content") ||
        "",
    ) || "";
  plot = plot
    .replace(new RegExp(`^FC2[-_]?PPV[-_]?${id}\\s*`, "i"), "")
    .replace(/\s+/g, " ")
    .trim();
  if (plot.length < 12 || isJunkTitle(plot)) plot = "";

  return {
    code: displayCode,
    title,
    originalTitle: title,
    plot: plot || undefined,
    genres: genres.slice(0, 40),
    studio: seller || "FC2",
    makers: seller ? [seller] : ["FC2"],
    premiered: premiered || undefined,
    poster: cover,
    productId: id,
    source: "fc2",
  };
}

export async function scrapeFd2ppv(codeRaw: string): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  const m = code.match(/FC2[-_]?PPV[-_]?(\d+)/i) || code.match(/FC2[-_]?(\d+)/i);
  if (!m) return null;
  const id = m[1]!;
  const displayCode = `FC2-PPV-${id}`;
  return withSiteMirrorBase("fd2ppv", "https://fd2ppv.cc", async (baseRaw) => {
  const base = baseRaw.replace(/\/$/, "") || "https://fd2ppv.cc";
  const url = `${base}/articles/${id}`;
  const page = await fetchPage(url, {
    referer: `${base}/`,
    sourceId: "fd2ppv",
    viaFlare: true,
    waitInSeconds: 4,
    timeoutMs: 45000,
  });
  const html = page?.html || null;
  if (!html) return null;
  if (
    /Too many requests|Just a moment|cf-browser-verification|Edge IP Restricted/i.test(
      html,
    ) &&
    html.length < 8000
  ) {
    return null;
  }
  if (
    /作品が見つかりません|ページが見つかりません|404 Page Not Found|404 Not Found/i.test(
      html,
    )
  ) {
    return null;
  }

  const $ = cheerio.load(html);
  let title = cleanTitle(
    $(".work-brief").first().text() ||
      $("meta[name='description']").attr("content") ||
      pickOgTitle(html) ||
      $("title").first().text(),
    displayCode,
  );
  title = cleanTitle(title, code)
    .replace(new RegExp(`^FC2[-_]?PPV[-_]?${id}\\s*[-–—:]?\\s*`, "i"), "")
    .replace(new RegExp(`^FC2\\s*PPV\\s*${id}\\s*[-–—:]?\\s*`, "i"), "")
    .replace(/\s*[|｜].*$/, "")
    .trim();
  // work-title 常只是纯数字番号，勿当标题
  if (!title || /^\d{5,}$/.test(title) || isJunkTitle(title)) {
    title = "";
  }

  const metaVal = (label: RegExp): string => {
    let found = "";
    $(".work-meta-label").each((_, el) => {
      const lab = stripTags($(el).text());
      if (!label.test(lab)) return;
      found = stripTags($(el).nextAll(".work-meta-value").first().text());
    });
    return found;
  };

  const premieredRaw = metaVal(/配信日|販売日|公開日/);
  let premiered = "";
  const dm = premieredRaw.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const runtimeRaw = metaVal(/収録時間|再生時間/);
  let runtime: number | null = null;
  const hm = runtimeRaw.match(/(?:(\d+):)?(\d{1,2}):(\d{2})/);
  if (hm) {
    const h = Number(hm[1] || 0);
    const min = Number(hm[2] || 0);
    runtime = h * 60 + min || null;
  } else {
    const mins = runtimeRaw.match(/(\d+)\s*分/);
    if (mins) runtime = Number(mins[1]) || null;
  }

  const seller = metaVal(/販売者|作者|投稿者/) || "";
  const studio = seller || metaVal(/配信元/) || "FC2";

  const genres: string[] = [];
  $(".work-tags a").each((_, el) => {
    const n = stripTags($(el).text());
    if (!n || n.length > 40 || /タグ|tag/i.test(n) || genres.includes(n)) return;
    genres.push(n);
  });

  const actors: string[] = [];
  $(
    '.artist-info-card a.artistUrl, .artist-info-card a[href*="/actresses/"], a[href*="/actresses/"]',
  ).each((_, el) => {
    const n = stripTags($(el).text());
    if (!n || n.length > 40 || /AV女優|女優|タグ/i.test(n) || actors.includes(n)) {
      return;
    }
    actors.push(n);
  });

  const photoBlock =
    html.match(
      /class=["'][^"']*work-original-photos[^"']*["'][^>]*>([\s\S]*?)<\/div>/i,
    )?.[1] ||
    html.match(
      /class=["'][^"']*work-photos[^"']*["'][^>]*>([\s\S]*?)<\/div>/i,
    )?.[1] ||
    "";
  const photos = [
    ...photoBlock.matchAll(
      /(https?:\/\/[^\s"'<>]+\.(?:jpg|jpeg|png|webp|avif))/gi,
    ),
  ].map((x) => x[1]!);
  let cover = photos[0] || pickOgImage(html) || null;
  if (cover) cover = absUrl(cover, url);
  if (cover && isJunkCoverUrl(cover)) cover = null;

  const fanart = photos
    .slice(1, 12)
    .map((u) => absUrl(u, url))
    .filter((u): u is string => Boolean(u) && !isJunkCoverUrl(u));

  if (!title && !cover) return null;

  return {
    code: displayCode,
    title: title || "",
    originalTitle: title || "",
    genres: genres.slice(0, 40),
    actors: actors.slice(0, 20),
    studio,
    makers: seller ? [seller] : studio ? [studio] : ["FC2"],
    premiered: premiered || undefined,
    runtime: runtime && runtime > 0 ? runtime : undefined,
    poster: cover,
    fanart: fanart.length ? fanart : undefined,
    productId: id,
    source: "fd2ppv",
  };
  });
}

export async function scrapeTheporndb(
  codeRaw: string,
  opts?: { baseUrl?: string; apiKey?: string },
): Promise<PartialFromSource | null> {
  const code = String(codeRaw || "").trim();
  if (!code) return null;
  const key = String(
    opts?.apiKey || process.env.THEPORNDB_API_KEY || "",
  ).trim();
  if (!key) return null;

  const base = (opts?.baseUrl || "https://api.theporndb.net").replace(/\/$/, "");
  const headers: Record<string, string> = {
    "User-Agent": UA,
    Accept: "application/json",
    Authorization: key.toLowerCase().startsWith("bearer ")
      ? key
      : `Bearer ${key}`,
  };

  type TpdbScene = {
    id?: string;
    title?: string;
    description?: string;
    date?: string;
    duration?: number | null;
    rating?: number | null;
    image?: string | null;
    poster?: string | null;
    poster_image?: string | null;
    back_image?: string | null;
    sku?: string | null;
    external_id?: string | null;
    slug?: string | null;
    site?: { name?: string; network?: string } | null;
    performers?: Array<{ name?: string; parent?: { name?: string } }>;
    tags?: Array<{ name?: string }>;
    directors?: Array<{ name?: string }>;
    background?: { full?: string; large?: string } | null;
    posters?: { full?: string; large?: string } | null;
  };

  const getJson = async (pathAndQuery: string): Promise<unknown | null> => {
    try {
      const res = await undiciFetch(`${base}${pathAndQuery}`, {
        signal: AbortSignal.timeout(25000),
        headers,
        redirect: "follow",
      });
      if (res.status === 401 || res.status === 403) return null;
      if (!res.ok) return null;
      return (await res.json()) as unknown;
    } catch {
      return null;
    }
  };

  const looksJav = (s: string): boolean => {
    const u = s.toUpperCase();
    if (/^FC2/.test(u)) return true;
    if (/^[A-Z]{1,12}-\d{2,}/.test(u)) return true;
    if (/^\d{2,3}[A-Z]{2,}-\d+/.test(u)) return true; // 200GANA-1
    return false;
  };

  const codeKey = (s: string) =>
    String(s || "")
      .replace(/[-_\s]/g, "")
      .toUpperCase();
  const want = codeKey(stdCode(code) || code);

  const scoreHit = (item: TpdbScene): number => {
    let score = 0;
    const blob = [
      item.title,
      item.sku,
      item.external_id,
      item.slug,
      item.id,
    ]
      .map((x) => String(x || ""))
      .join(" ");
    const keyBlob = codeKey(blob);
    if (keyBlob === want || keyBlob.includes(want)) score += 100;
    if (codeKey(String(item.sku || "")) === want) score += 80;
    if (codeKey(String(item.external_id || "")) === want) score += 40;
    if (new RegExp(code.replace(/-/g, "[-_]?"), "i").test(blob)) score += 30;
    if (item.image || item.poster || item.poster_image) score += 5;
    return score;
  };

  const parseScene = (item: TpdbScene | null | undefined): PartialFromSource | null => {
    if (!item || typeof item !== "object") return null;
    const title = cleanTitle(String(item.title || ""), stdCode(code) || code);
    if (!title || isJunkTitle(title)) return null;

    const actors = (item.performers || [])
      .map((p) => String(p?.parent?.name || p?.name || "").trim())
      .filter(Boolean);
    const genres = (item.tags || [])
      .map((t) => String(t?.name || "").trim())
      .filter(Boolean)
      .slice(0, 30);
    const studio =
      String(item.site?.name || "").trim() ||
      String(item.site?.network || "").trim() ||
      undefined;
    const director = String(item.directors?.[0]?.name || "").trim() || undefined;
    const premiered = String(item.date || "").slice(0, 10);
    const dur = typeof item.duration === "number" ? item.duration : null;
    // API duration 多为秒
    const runtime =
      dur && dur > 0 ? (dur > 600 ? Math.round(dur / 60) : dur) : undefined;

    let cover =
      item.posters?.full ||
      item.posters?.large ||
      item.poster_image ||
      item.poster ||
      item.image ||
      item.background?.full ||
      item.background?.large ||
      item.back_image ||
      null;
    if (cover && isJunkCoverUrl(cover)) cover = null;

    const plot = stripTags(String(item.description || ""));
    const displayCode = stdCode(code) || code.toUpperCase();

    return {
      code: displayCode,
      title,
      originalTitle: title,
      plot: plot.length >= 12 ? plot : undefined,
      actors: actors.length ? [...new Set(actors)].slice(0, 20) : undefined,
      genres: genres.length ? genres : undefined,
      studio,
      makers: studio ? [studio] : undefined,
      director,
      premiered: /^\d{4}-\d{2}-\d{2}/.test(premiered) ? premiered : undefined,
      runtime,
      userRating:
        typeof item.rating === "number" && item.rating > 0
          ? item.rating
          : undefined,
      poster: cover,
      productId: String(item.id || item.external_id || item.sku || "").trim() || undefined,
      source: "theporndb",
    };
  };

  const searchPaths = looksJav(code)
    ? [
        `/jav?q=${encodeURIComponent(code)}&per_page=10`,
        `/jav?q=${encodeURIComponent(stdCode(code) || code)}&per_page=10`,
        `/scenes?q=${encodeURIComponent(code)}&per_page=5`,
      ]
    : [
        `/scenes?q=${encodeURIComponent(code)}&per_page=10`,
        `/movies?q=${encodeURIComponent(code)}&per_page=5`,
        `/jav?q=${encodeURIComponent(code)}&per_page=5`,
      ];

  let best: TpdbScene | null = null;
  let bestScore = 0;
  let bestKind: "jav" | "scenes" | "movies" = looksJav(code) ? "jav" : "scenes";

  for (const path of searchPaths) {
    const raw = await getJson(path);
    if (!raw || typeof raw !== "object") continue;
    const list = Array.isArray((raw as { data?: unknown }).data)
      ? ((raw as { data: TpdbScene[] }).data || [])
      : [];
    for (const item of list) {
      const sc = scoreHit(item);
      if (sc > bestScore) {
        best = item;
        bestScore = sc;
        bestKind = path.startsWith("/jav")
          ? "jav"
          : path.startsWith("/movies")
            ? "movies"
            : "scenes";
      }
    }
    if (bestScore >= 100) break;
  }

  if (!best || bestScore < 20) return null;

  // 拉详情补全字段
  const id = String(best.id || "").trim();
  if (id) {
    const detailPath =
      bestKind === "jav"
        ? `/jav/${encodeURIComponent(id)}`
        : bestKind === "movies"
          ? `/movies/${encodeURIComponent(id)}`
          : `/scenes/${encodeURIComponent(id)}`;
    const detail = await getJson(detailPath);
    const full = (detail as { data?: TpdbScene } | null)?.data;
    if (full) best = full;
  }

  return parseScene(best);
}

/**
 * LibreDMM / LibreFanza：聚合 DMM·MGStage 等官方元数据（JSON，直连代理即可）。
 * 详情 `/movies/{CODE}.json`；冷门番号可能先 `err=processing` 需短轮询。
 * 独立数据源；不在 mgstage runner 内自动顶替。
 */
export async function scrapeLibreDmm(
  codeRaw: string,
  opts?: { baseUrl?: string },
): Promise<PartialFromSource | null> {
  const code = stdCode(codeRaw);
  if (!code) return null;
  const base = (opts?.baseUrl || "https://www.libredmm.com").replace(/\/$/, "");
  const referer = `${base}/`;

  const preferPlCover = (url: string | null | undefined): string | null => {
    const u = String(url || "").trim();
    if (!u) return null;
    // DMM mono：ps=竖图缩略，pl=横版大图（刮削封面优先 pl）
    return u.replace(/ps\.jpg(\?|$)/i, "pl.jpg$1");
  };

  const parseHit = (raw: unknown): PartialFromSource | null => {
    if (!raw || typeof raw !== "object") return null;
    const o = raw as LibreMovie;
    if (o.err && o.err !== "ok") return null;
    const title = cleanTitle(o.title || "", code);
    if (title && isJunkTitle(title)) return null;
    let cover =
      preferPlCover(o.cover_image_url) ||
      preferPlCover(o.thumbnail_image_url) ||
      null;
    if (cover && isJunkCoverUrl(cover)) cover = null;
    const actors = (o.actresses || [])
      .map((a) => String(a?.name || "").replace(/\s+\d+歳.*$/u, "").trim())
      .filter(Boolean);
    if (!title && !cover) return null;
    const maker = String(o.makers?.[0] || "").trim();
    const publisher = String(o.labels?.[0] || "").trim();
    const premiered = String(o.date || "").slice(0, 10);
    const review = typeof o.review === "number" ? o.review : null;
    const plot = stripTags(
      String(o.description || o.comment || o.subtitle || ""),
    );
    const seriesRaw = o.series;
    const series = Array.isArray(seriesRaw)
      ? String(seriesRaw[0] || "").trim()
      : String(seriesRaw || "").trim();
    const runtime =
      typeof o.minute === "number"
        ? o.minute
        : typeof o.runtime === "number"
          ? o.runtime
          : null;
    const productId =
      extractDmmCidFromUrl(String(o.url || "")) ||
      extractDmmCidFromUrl(cover) ||
      String(o.subtitle || "").trim() ||
      extractDmmCidFromUrl(String(o.normalized_id || "")) ||
      undefined;
    const genres = (o.genres || [])
      .map((g) => String(g).trim())
      .filter(
        (g) =>
          g &&
          !/^サンプル動画$/i.test(g) &&
          !/^デジタル配信$/i.test(g),
      );
    const fanart = (o.sample_image_urls || [])
      .map((u) => String(u || "").trim())
      .filter((u) => u && /^https?:\/\//i.test(u))
      .slice(0, 24);

    // 番号一致性：normalized_id 存在时须匹配
    const nid = stdCode(String(o.normalized_id || ""));
    if (nid && codeKey(nid) !== codeKey(code)) return null;

    return {
      code,
      title: title || "",
      originalTitle: title || "",
      plot: plot.length >= 12 ? plot : undefined,
      actors: actors.length ? actors : undefined,
      genres: genres.length ? genres : undefined,
      publisher: publisher || undefined,
      studio: maker || undefined,
      makers: (o.makers || []).map((m) => String(m).trim()).filter(Boolean),
      premiered: /^\d{4}-\d{2}-\d{2}/.test(premiered) ? premiered : undefined,
      director: String(o.directors?.[0] || "").trim() || undefined,
      series: series || undefined,
      runtime: runtime && runtime > 0 && runtime < 600 ? runtime : undefined,
      userRating: review != null && review > 0 ? review : undefined,
      poster: cover,
      productId: productId || undefined,
      fanart: fanart.length ? fanart : undefined,
      source: "libredmm",
    };
  };

  // 1) 详情 JSON（主路径）；冷门可能 processing
  const movieUrl = `${base}/movies/${encodeURIComponent(code)}.json`;
  for (let i = 0; i < 5; i++) {
    const data = await fetchJson(movieUrl, {
      referer,
      timeoutMs: 25000,
    });
    if (data && typeof data === "object") {
      const err = String((data as LibreMovie).err || "");
      if (err === "processing") {
        await new Promise((r) => setTimeout(r, 1200 + i * 400));
        continue;
      }
      if (err === "not_found") break;
      const hitMeta = parseHit(data);
      if (hitMeta?.title || hitMeta?.poster) return hitMeta;
    }
    if (i < 2) {
      await new Promise((r) => setTimeout(r, 800));
      continue;
    }
    break;
  }

  // 2) 搜索 JSON（常 302→详情 JSON）
  const searchData = await fetchJson(
    `${base}/search.json?q=${encodeURIComponent(code)}`,
    { referer, timeoutMs: 25000 },
  );
  const fromSearch = parseHit(searchData);
  if (fromSearch?.title || fromSearch?.poster) return fromSearch;

  return null;
}

function codeKey(s: string): string {
  return String(s || "")
    .replace(/[-_\s]/g, "")
    .toUpperCase();
}
