/** DMM CID 识别 / 猜测（对齐 mdc-ng：他源 CID → 回退重查） */

const CID_IN_URL =
  /(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp|pics\.dmm\.com|jp\.netcdn\.space)\/(?:pics_dig\/)?digital\/video\/([a-z0-9]+)\/\1(?:pl|ps|jm)?\.(?:jpe?g|webp)/i;

const CID_LOOSE = /(?:^|[^\w])([0-9]{0,3}[a-z]{2,10}\d{3,6})(?:[^\w]|$)/i;

export function extractDmmCidFromUrl(url: string | null | undefined): string | null {
  const s = String(url || "").trim();
  if (!s) return null;
  const m = s.match(CID_IN_URL);
  if (m?.[1]) return m[1].toLowerCase();
  return null;
}

export function extractDmmCidFromText(text: string | null | undefined): string | null {
  const s = String(text || "").trim();
  if (!s) return null;
  const fromUrl = extractDmmCidFromUrl(s);
  if (fromUrl) return fromUrl;
  const m = s.match(CID_LOOSE);
  return m?.[1] ? m[1].toLowerCase() : null;
}

/** 从番号猜常见 CID：dv1588 / dv01588 / 53dv01588 / 1dv01588 */
export function guessDmmCids(codeRaw: string): string[] {
  const code = String(codeRaw || "")
    .trim()
    .toUpperCase()
    .replace(/_/g, "-");
  const m = code.match(/^([A-Z]{2,10})-(\d{2,6})$/);
  if (!m || /^FC2/.test(code)) return [];
  const prefix = m[1]!.toLowerCase();
  const num = m[2]!;
  const out: string[] = [];
  const push = (c: string) => {
    if (c && !out.includes(c)) out.push(c);
  };
  for (const width of [5, 3, num.length]) {
    push(`${prefix}${num.padStart(width, "0")}`);
  }
  push(`${prefix}${num}`);
  push(`1${prefix}${num.padStart(5, "0")}`);
  push(`1${prefix}${num}`);
  // 常见 maker 前缀数字（如 53dv01588）
  for (const maker of ["1", "53", "55", "118", "130", "140", "h_"]) {
    push(`${maker}${prefix}${num.padStart(5, "0")}`);
    push(`${maker}${prefix}${num}`);
  }
  return out;
}

export function collectDmmCidsFromHits(
  hits: Array<{
    productId?: string | null;
    cid?: string | null;
    poster?: string | null;
    fanart?: string[] | null;
  }>,
): string[] {
  const out: string[] = [];
  const push = (c: string | null | undefined) => {
    const v = String(c || "")
      .trim()
      .toLowerCase();
    if (v && !out.includes(v)) out.push(v);
  };
  for (const h of hits) {
    push(h.productId);
    push(h.cid);
    push(extractDmmCidFromUrl(h.poster || ""));
    for (const u of h.fanart || []) push(extractDmmCidFromUrl(u));
  }
  return out;
}

export function dmmCoverUrls(cid: string): { pl: string; ps: string; awsPl: string; awsPs: string } {
  const c = cid.toLowerCase();
  return {
    pl: `https://pics.dmm.co.jp/digital/video/${c}/${c}pl.jpg`,
    ps: `https://pics.dmm.co.jp/digital/video/${c}/${c}ps.jpg`,
    awsPl: `https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/${c}/${c}pl.jpg`,
    awsPs: `https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/${c}/${c}ps.jpg`,
  };
}
