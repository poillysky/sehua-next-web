import * as cheerio from "cheerio";
import { fetchText } from "../download.js";
import type { ScrapeMeta } from "../types.js";
import { isJunkCoverUrl, isJunkTitle, stdCode } from "../util.js";

const BASES = [
  "https://www.javbus.com",
  "https://www.seejav.me",
];

function absUrl(base: string, href: string | undefined): string | null {
  if (!href) return null;
  try {
    if (href.startsWith("//")) return `https:${href}`;
    return new URL(href, base).href;
  } catch {
    return null;
  }
}

function cleanJavbusTitle(raw: string, code: string): string {
  let t = String(raw || "")
    .replace(/\s+/g, " ")
    .trim();
  t = t
    .replace(new RegExp(`^${code}\\s+`, "i"), "")
    .replace(/\s*-\s*JavBus.*$/i, "")
    .trim();
  if (isJunkTitle(t)) return "";
  return t;
}

function parseDetail(
  html: string,
  base: string,
  code: string,
): Partial<ScrapeMeta> | null {
  const $ = cheerio.load(html);
  if (!$(".bigImage, .movie .info").length) return null;

  const title = cleanJavbusTitle(
    $("h3").first().text() ||
      $("title").text().replace(/\s*-\s*JavBus.*$/i, ""),
    code,
  );
  if (!title && !$(".bigImage").length) return null;

  const info: Record<string, string> = {};
  const infoLinks: Record<string, string[]> = {};
  $(".movie .info p").each((_, el) => {
    const label = $(el)
      .find("span.header")
      .first()
      .text()
      .replace(/[:：]/g, "")
      .trim();
    if (!label) return;
    const links: string[] = [];
    $(el)
      .find("a")
      .each((__, a) => {
        const n = $(a).text().replace(/\s+/g, " ").trim();
        if (n && n.length < 80 && !links.includes(n)) links.push(n);
      });
    const rest = $(el)
      .clone()
      .children("span.header")
      .remove()
      .end()
      .text()
      .replace(/\s+/g, " ")
      .trim();
    info[label] = rest;
    if (links.length) infoLinks[label] = links;
  });

  const pickInfo = (...keys: string[]): string => {
    for (const k of keys) {
      if (info[k]) return info[k]!;
    }
    for (const [lab, val] of Object.entries(info)) {
      if (keys.some((k) => lab.includes(k) || new RegExp(k, "i").test(lab))) {
        return val;
      }
    }
    return "";
  };

  const pickLink = (...keys: string[]): string => {
    for (const k of keys) {
      const hit = infoLinks[k]?.[0];
      if (hit) return hit;
    }
    for (const [lab, links] of Object.entries(infoLinks)) {
      if (keys.some((k) => lab.includes(k) || new RegExp(k, "i").test(lab))) {
        return links[0] || "";
      }
    }
    return "";
  };

  const actors: string[] = [];
  $(".avatar-box .star-name a, .star-name a, a[href*='/star/']").each((_, el) => {
    const href = String($(el).attr("href") || "");
    // 导航/其它区也可能有 star，限制在详情相关
    if (href && !/\/star\//i.test(href)) return;
    const n = $(el).text().replace(/\s+/g, " ").trim();
    if (n && n.length < 40 && !/演員|演员|Actress/i.test(n) && !actors.includes(n)) {
      actors.push(n);
    }
  });

  // 类别在 .movie .info 的 span.genre；排除顶栏 /genre/hd|/genre/sub
  const genres: string[] = [];
  $(".movie .info span.genre a[href*='/genre/']").each((_, el) => {
    const href = String($(el).attr("href") || "");
    if (/\/genre\/(hd|sub)(?:\/|$|\?)/i.test(href)) return;
    const n = $(el).text().replace(/\s+/g, " ").trim();
    if (!n || n.length >= 40) return;
    if (!genres.includes(n)) genres.push(n);
  });

  const poster =
    absUrl(base, $(".bigImage img").attr("src")) ||
    absUrl(base, $(".bigImage").attr("href")) ||
    absUrl(base, $("a.bigImage img").attr("src"));
  const cover = poster && !isJunkCoverUrl(poster) ? poster : null;

  const fanart: string[] = [];
  $("#sample-waterfall a.sample-box, .sample-box").each((_, el) => {
    const u =
      absUrl(base, $(el).attr("href")) ||
      absUrl(base, $(el).find("img").attr("src"));
    if (u && !isJunkCoverUrl(u) && !fanart.includes(u)) fanart.push(u);
  });

  const premieredRaw = pickInfo("發行日期", "发行日期", "Release Date", "発売日");
  let premiered = "";
  const dm = premieredRaw.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (dm) {
    premiered = `${dm[1]}-${dm[2]!.padStart(2, "0")}-${dm[3]!.padStart(2, "0")}`;
  }

  const publisher =
    pickLink("發行商", "发行商", "Publisher", "Label", "レーベル") ||
    pickInfo("發行商", "发行商", "Publisher", "Label", "レーベル");
  const maker =
    pickLink("製作商", "制作商", "Studio", "片商", "メーカー") ||
    pickInfo("製作商", "制作商", "Studio", "片商", "メーカー");
  const runtimeRaw = pickInfo(
    "長度",
    "长度",
    "Length",
    "時長",
    "时长",
    "収録時間",
  );
  const runtime = Number(runtimeRaw.match(/(\d+)/)?.[1] || 0) || null;
  const director =
    pickLink("導演", "导演", "Director", "監督") ||
    pickInfo("導演", "导演", "Director", "監督");
  let series =
    pickLink("系列", "Series", "シリーズ") ||
    pickInfo("系列", "Series", "シリーズ");
  // 同页系列链接兜底（header 文案变体时 pick 可能落空）
  if (!series || series.length < 2) {
    const fromHref =
      $(".movie .info a[href*='/series/']")
        .first()
        .text()
        .replace(/\s+/g, " ")
        .trim() ||
      $("a[href*='/series/']")
        .filter((_, el) => {
          const href = String($(el).attr("href") || "");
          return /\/series\/[^/?#]+/i.test(href);
        })
        .first()
        .text()
        .replace(/\s+/g, " ")
        .trim();
    if (fromHref && fromHref.length >= 2 && fromHref.length < 80) {
      series = fromHref;
    }
  }
  if (series === "-" || isJunkTitle(series)) series = "";

  if (!title && !cover) return null;

  return {
    code,
    title: title || "",
    originalTitle: title || "",
    plot: "",
    premiered: premiered || undefined,
    publisher: publisher || undefined,
    studio: maker || undefined,
    makers: maker ? [maker] : undefined,
    actors: actors.slice(0, 40),
    genres: genres.slice(0, 40),
    runtime: runtime && runtime > 0 ? runtime : null,
    director: director || undefined,
    series: series || undefined,
    poster: cover,
    fanart: fanart.slice(0, 30),
    productId: cover
      ? cover.match(
          /(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp|jp\.netcdn\.space)\/(?:pics_dig\/)?digital\/video\/([a-z0-9_]+)\//i,
        )?.[1]
      : undefined,
    source: "javbus",
  };
}

/** Try detail pages for a code; return partial meta or null. */
export async function scrapeJavbus(
  code: string,
): Promise<Partial<ScrapeMeta> | null> {
  const c = stdCode(code);
  if (!c) return null;
  const slug = c.toLowerCase();

  for (const base of BASES) {
    // www 默认繁中 UI：类别繁体；标题/女优仍日文。镜像 seejav 同结构。
    const url = `${base}/${slug}`;
    const html = await fetchText(url, {
      referer: `${base}/`,
      sourceId: "javbus",
      timeoutMs: 18000,
    });
    if (!html || html.length < 800) continue;
    if (
      /Just a moment|cf-browser-verification|Access Denied/i.test(
        html.slice(0, 3000),
      ) &&
      !/bigImage/i.test(html)
    ) {
      continue;
    }
    if (
      /404|找不到|not found|沒有找到|没有找到/i.test(html.slice(0, 2500)) &&
      !/bigImage/i.test(html)
    ) {
      // 明确无详情：不再试镜像，便于快源快速判空
      return null;
    }
    if (!new RegExp(c.replace(/-/g, "[-_]?"), "i").test(html.slice(0, 15000))) {
      continue;
    }
    const parsed = parseDetail(html, base, c);
    if (parsed?.title || parsed?.poster) return parsed;
  }
  return null;
}
