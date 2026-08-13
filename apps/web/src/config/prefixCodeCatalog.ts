import rangesJson from "./prefix-code-ranges.json";

export type PrefixCodeRange = {
  from: number;
  to: number;
  pad: number;
  source?: string;
};

type RangesFile = {
  version: string;
  updated?: string;
  principle?: string;
  ranges: Record<string, PrefixCodeRange>;
  skip: string[];
};

const DATA = rangesJson as RangesFile;
const SKIP = new Set(
  (DATA.skip || []).map((p) => String(p).trim().toUpperCase().replace(/_/g, "-")),
);

function normPrefix(prefix: string): string {
  return String(prefix || "")
    .trim()
    .toUpperCase()
    .replace(/_/g, "-");
}

export function prefixCatalogVersion(): string {
  return DATA.version || "";
}

export function getPrefixCodeRange(prefix: string): PrefixCodeRange | null {
  const key = normPrefix(prefix);
  if (!key || SKIP.has(key)) return null;
  const r = DATA.ranges?.[key];
  if (!r) return null;
  const from = Math.max(1, Number(r.from) || 1);
  const to = Math.max(from, Number(r.to) || from);
  const pad = Math.max(1, Math.min(8, Number(r.pad) || 3));
  return { from, to, pad, source: r.source };
}

export function formatPrefixCode(
  prefix: string,
  n: number,
  pad = 3,
): string {
  const p = normPrefix(prefix);
  return `${p}-${String(n).padStart(pad, "0")}`;
}

/** 预设全量件数（from..to），与库无关 */
export function getPrefixPresetTotal(prefix: string): number {
  const r = getPrefixCodeRange(prefix);
  if (!r) return 0;
  return r.to - r.from + 1;
}

/**
 * 分页切片；页码从 1 起。
 * 默认从小到大：from → to。
 */
export function listPresetPrefixCodes(
  prefix: string,
  page: number,
  pageSize: number,
  opts?: { order?: "asc" | "hot"; range?: PrefixCodeRange | null },
): { codes: string[]; total: number; range: PrefixCodeRange | null } {
  const range =
    opts?.range !== undefined ? opts.range : getPrefixCodeRange(prefix);
  if (!range) return { codes: [], total: 0, range: null };
  const total = range.to - range.from + 1;
  const ps = Math.max(1, pageSize);
  const safePage = Math.max(1, page);
  const startIdx = (safePage - 1) * ps;
  if (startIdx >= total) return { codes: [], total, range };
  const endIdx = Math.min(total, startIdx + ps);
  const hotFirst = opts?.order === "hot";
  const codes: string[] = [];
  for (let i = startIdx; i < endIdx; i++) {
    const n = hotFirst ? range.to - i : range.from + i;
    codes.push(formatPrefixCode(prefix, n, range.pad));
  }
  return { codes, total, range };
}

/**
 * 公开图床试探 URL（非本库）。失败由 <img onError> 消化。
 * DMM digital 常见：小写前缀 + 5 位；部分带 1/118 发行元前缀。
 */
export function publicCoverCandidates(code: string): string[] {
  const m = /^([A-Z0-9]+)-(\d+)$/i.exec(String(code || "").trim());
  if (!m) return [];
  const prefix = m[1].toLowerCase();
  const num = String(parseInt(m[2], 10) || 0);
  const n5 = num.padStart(5, "0");
  const cid = `${prefix}${n5}`;
  return [
    `https://pics.dmm.co.jp/digital/video/${cid}/${cid}pl.jpg`,
    `https://pics.dmm.co.jp/digital/video/1${cid}/1${cid}pl.jpg`,
    `https://pics.dmm.co.jp/digital/video/118${cid}/118${cid}pl.jpg`,
  ];
}
