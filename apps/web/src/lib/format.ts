const KEYWORD_SPLIT =
  /[.,!?;—()[\]{}<>@#%^&*~`"'|\\/\-，。！？；“”‘’「」『』《》、【】……（）·　\s]+/;
export function formatByteSize(bytes: number | string): string {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const base = 1024;
  const group = Math.min(
    Math.floor(Math.log(n) / Math.log(base)),
    units.length - 1,
  );
  return `${(n / Math.pow(base, group)).toFixed(2)} ${units[group]}`;
}
export function formatDate(ts: number | string): string {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return "—";
  // API may return unix seconds or ms
  const ms = n < 1e12 ? n * 1000 : n;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function escapeHtml(unsafe: string): string {
  return unsafe.replace(/[&<>"'`=/]/g, (match) => {
    return (
      (
        {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
          "`": "&#96;",
          "/": "&#x2F;",
          "=": "&#x3D;",
        } as Record<string, string>
      )[match] || match
    );
  });
}
export function parseHighlight(
  text: string,
  highlight: string | string[],
): string {
  if (!text) return "";
  if (!highlight) return escapeHtml(text);
  const keywords =
    typeof highlight === "string"
      ? [highlight, ...highlight.split(KEYWORD_SPLIT)].filter(
          (k) => k.trim().length >= 2,
        )
      : highlight.filter((k) => k.trim().length >= 2);
  let out = escapeHtml(text);
  const unique = Array.from(new Set(keywords.map((k) => k.trim()))).sort(
    (a, b) => b.length - a.length,
  );
  for (const keyword of unique) {
    const escaped = escapeHtml(keyword).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`(${escaped})(?![^<>]*>)`, "gi");
    out = out.replace(regex, `<mark class="hl-kw">$1</mark>`);
  }
  return out;
}
export function primaryLink(item: {
  ed2k_link?: string;
  link_kind?: string;
  hash?: string;
}): string {
  const link = (item.ed2k_link || "").trim();
  if (link) return link;
  if (item.link_kind === "magnet" && item.hash) {
    return `magnet:?xt=urn:btih:${item.hash}`;
  }
  return "";
}
