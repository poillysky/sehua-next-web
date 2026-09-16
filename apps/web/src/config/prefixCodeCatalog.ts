/**
 * 前缀流水号种子已迁到 `apps/maps/prefixes/code-ranges.json`。
 * 运行时由 API（`data/prefix/code-ranges.json`）提供；本模块不再打包种子 JSON。
 * 仅保留与图床试探相关的纯函数工具。
 */

export type PrefixCodeRange = {
  from: number;
  to: number;
  pad: number;
  source?: string;
};

function normPrefix(prefix: string): string {
  return String(prefix || "")
    .trim()
    .toUpperCase()
    .replace(/_/g, "-");
}

export function formatPrefixCode(
  prefix: string,
  n: number,
  pad = 3,
): string {
  const p = normPrefix(prefix);
  return `${p}-${String(n).padStart(pad, "0")}`;
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
