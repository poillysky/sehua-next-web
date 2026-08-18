/**
 * Pack-bleed / multi-resource view normalization.
 * Port of sehua-search apps/web/src/utils/resource.ts (core subset).
 */

import type { ResourceItem } from "@/types/resource";
import { formatByteSize } from "@/lib/format";
import { normalizeMakerCode, parseMakerCode } from "@/lib/makerCode";

export type DescriptionLine = {
  label: string;
  value: string;
};

const DISPLAY_DESCRIPTION_LABELS = [
  "资源名称",
  "影片名称",
  "资源大小",
  "出演女优",
  "资源类型",
  "是否有码",
  "有无水印",
  "资源数量",
  "解压密码",
] as const;

const DESCRIPTION_LABEL_ALIASES: Record<
  string,
  (typeof DISPLAY_DESCRIPTION_LABELS)[number]
> = {
  有无第三方水印: "有无水印",
  影片容量: "资源大小",
  影片大小: "资源大小",
  文件大小: "资源大小",
  提取密码: "解压密码",
  资源密码: "解压密码",
  资源解压密码: "解压密码",
  影片名稱: "影片名称",
  資源名稱: "资源名称",
  女优名称: "出演女优",
  女优: "出演女优",
  演员: "出演女优",
  主演: "出演女优",
};

const MAX_PREVIEW_IMAGES = 5;
const IMAGE_EXT_RE = /\.(jpe?g|png|gif|webp|bmp)(\?|#|$)/i;
const INVALID_IMAGE_MARKERS = [
  "filetype",
  "hrline",
  "smiley",
  "/static/image/common/",
  "static/image/",
  "avatar",
  "attachment/common/",
  "usergroup_icon",
  "groupicon",
  "favicon",
];

const ED2K_LINK_RE =
  /ed2k:\/\/\|file\|([^|]+)\|(\d+)\|([A-Fa-f0-9]{32})\|/i;
const MAGNET_HASH_RE =
  /magnet:\?xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})/i;

const PLACEHOLDER_MAGNET_NAME_RE = /^magnet-[0-9a-f]{8}$/i;

type ResourcePick = Pick<
  ResourceItem,
  | "title"
  | "name"
  | "description"
  | "hash"
  | "ed2k_link"
  | "ed2k_links"
  | "size"
  | "preview_images"
  | "link_kind"
>;

export function formatDescriptionLines(
  description?: string | null,
): DescriptionLine[] {
  const text = description?.trim();
  if (!text) return [];

  const seen = new Set<string>();
  const collected: DescriptionLine[] = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    const match = line.match(/^【([^】]+)】(.*)$/);
    if (!match) continue;
    const rawLabel = match[1].trim();
    if (!rawLabel) continue;
    const label = DESCRIPTION_LABEL_ALIASES[rawLabel] || rawLabel;
    if (seen.has(label)) continue;
    const value = match[2].trim().replace(/^[:：]+/, "");
    if (!value) continue;
    seen.add(label);
    collected.push({ label, value });
  }
  if (!collected.length) return [];

  const preferredIndex = new Map(
    DISPLAY_DESCRIPTION_LABELS.map((label, index) => [label, index]),
  );
  const known: DescriptionLine[] = [];
  const rest: DescriptionLine[] = [];
  for (const row of collected) {
    if (
      preferredIndex.has(row.label as (typeof DISPLAY_DESCRIPTION_LABELS)[number])
    ) {
      known.push(row);
    } else {
      rest.push(row);
    }
  }
  known.sort(
    (a, b) =>
      (preferredIndex.get(
        a.label as (typeof DISPLAY_DESCRIPTION_LABELS)[number],
      ) ?? 0) -
      (preferredIndex.get(
        b.label as (typeof DISPLAY_DESCRIPTION_LABELS)[number],
      ) ?? 0),
  );
  return [...known, ...rest];
}

export function getDescriptionField(
  description: string | null | undefined,
  label: string,
): string | null {
  return (
    formatDescriptionLines(description).find((line) => line.label === label)
      ?.value || null
  );
}

function isMissingSubName(
  name?: string | null,
  hash?: string | null,
): boolean {
  const n = (name || "").trim();
  if (!n) return true;
  const h = (hash || "").trim().toUpperCase();
  if (h && n.toUpperCase() === h) return true;
  if (h.length >= 8 && n.toUpperCase() === h.slice(0, 8)) return true;
  if (PLACEHOLDER_MAGNET_NAME_RE.test(n)) return true;
  return false;
}

export function isPublicDownloadLink(link?: string | null): boolean {
  const lower = (link || "").trim().toLowerCase();
  if (!lower || lower.startsWith("unavailable://")) return false;
  if (lower.startsWith("ed2k://") || lower.startsWith("magnet:")) return true;
  return lower.includes("115cdn.com/s/") || lower.includes("115.com/s/");
}

export function linkKindOf(
  link?: string | null,
): "ed2k" | "magnet" | "stub" | "115share" | "other" {
  const lower = (link || "").trim().toLowerCase();
  if (lower.startsWith("magnet:")) return "magnet";
  if (lower.startsWith("ed2k://")) return "ed2k";
  if (lower.startsWith("unavailable://")) return "stub";
  if (lower.includes("115cdn.com/s/") || lower.includes("115.com/s/")) {
    return "115share";
  }
  return "other";
}

export function parseEd2kLink(link: string) {
  const match = link.match(ED2K_LINK_RE);
  if (!match) return null;
  return {
    filename: match[1],
    size: match[2],
    hash: match[3].toUpperCase(),
    link,
  };
}

export function parseMagnetLink(link: string) {
  const match = link.match(MAGNET_HASH_RE);
  if (!match) return null;
  const hash = match[1];
  const out: {
    hash: string;
    link: string;
    filename?: string;
    size?: number;
  } = {
    hash: hash.length === 40 ? hash.toUpperCase() : hash.toUpperCase(),
    link,
  };
  try {
    const q = link.includes('?') ? link.split('?').slice(1).join('?') : '';
    const params = new URLSearchParams(q);
    const dn = params.get('dn');
    if (dn) out.filename = decodeURIComponent(dn.replace(/\+/g, ' ')).trim();
    const xl = params.get('xl');
    if (xl) {
      const n = Number(xl);
      if (Number.isFinite(n)) out.size = n;
    }
  } catch {
    /* ignore */
  }
  return out;
}

export function normalizeEd2kLinks(
  ed2kLinks?: string[] | null,
  fallbackLink?: string | null,
): string[] {
  const raw = (
    Array.isArray(ed2kLinks) && ed2kLinks.length
      ? ed2kLinks
      : fallbackLink
        ? [fallbackLink]
        : []
  ).filter(Boolean);
  return Array.from(new Set(raw.filter((link) => isPublicDownloadLink(link))));
}

export function linkMatchesResourceHash(
  link: string | null | undefined,
  hash: string | null | undefined,
): boolean {
  const h = (hash || "").trim().toUpperCase();
  if (!h) return true;
  const raw = (link || "").trim();
  if (!raw) return false;
  const ed2k = parseEd2kLink(raw);
  if (ed2k?.hash) return ed2k.hash.toUpperCase() === h;
  const magnet = parseMagnetLink(raw);
  if (magnet?.hash) return magnet.hash.toUpperCase() === h;
  return true;
}

/** sehua linksForResourceHash */
export function linksForResourceHash(
  hash: string | null | undefined,
  ed2kLinks?: string[] | null,
  fallbackLink?: string | null,
): string[] {
  const primary = (fallbackLink || "").trim();
  const fromMeta = normalizeEd2kLinks(ed2kLinks, null);
  const out: string[] = [];
  const push = (link: string) => {
    if (!link || out.includes(link)) return;
    if (
      !isPublicDownloadLink(link) &&
      !link.toLowerCase().startsWith("unavailable://")
    ) {
      return;
    }
    out.push(link);
  };
  if (primary) push(primary);
  for (const link of fromMeta) push(link);
  if (!out.length && primary) return [primary];

  const h = (hash || "").trim().toUpperCase();
  if (!h) return out;

  const hashable = out.filter(
    (link) =>
      Boolean(parseEd2kLink(link)?.hash || parseMagnetLink(link)?.hash),
  );
  if (!hashable.length) return out;

  const matched = out.filter((link) => {
    const ed2k = parseEd2kLink(link);
    const magnet = parseMagnetLink(link);
    if (ed2k?.hash || magnet?.hash) {
      return linkMatchesResourceHash(link, h);
    }
    return false;
  });
  if (matched.length) return matched;
  return primary ? [primary] : [];
}

export function distinctDownloadHashCount(
  ed2kLinks?: string[] | null,
  fallbackLink?: string | null,
): number {
  const raw = normalizeEd2kLinks(ed2kLinks, fallbackLink);
  const hashes = new Set<string>();
  for (const link of raw) {
    const h =
      parseEd2kLink(link)?.hash?.toUpperCase() ||
      parseMagnetLink(link)?.hash?.toUpperCase();
    if (h) hashes.add(h);
  }
  return hashes.size;
}

function firstMakerCodeIn(text: string): string | null {
  const raw = normalizeMakerCode(text);
  if (!raw) return null;
  const whole = parseMakerCode(raw);
  if (whole) return whole.canonical;
  const re =
    /(?:^|[^A-Za-z0-9])([A-Za-z]{2,15}[-_\s]?\d{2,8}|FC2[-_\s]?PPV[-_\s]?\d{5,10})(?![0-9])/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw))) {
    const parsed = parseMakerCode(m[1]);
    if (parsed) return parsed.canonical;
  }
  return null;
}

function resourceNamesAlign(a: string, b: string): boolean {
  const ca = firstMakerCodeIn(a);
  const cb = firstMakerCodeIn(b);
  if (ca && cb) return ca === cb;
  const na = a.trim().toLowerCase();
  const nb = b.trim().toLowerCase();
  if (!na || !nb) return false;
  return na === nb || na.includes(nb.slice(0, 24)) || nb.includes(na.slice(0, 24));
}

function isPackStyleTitle(title: string): boolean {
  return /BT种子|合集|黑客最新|\d+\s*部|部1080|打包/i.test(title);
}

export function isPackBleedItem(
  item: Pick<
    ResourceItem,
    "title" | "name" | "description" | "hash" | "ed2k_link" | "ed2k_links"
  >,
): boolean {
  const name = item.name?.trim() || "";
  const title = item.title?.trim() || "";
  const fromDesc =
    getDescriptionField(item.description, "资源名称") ||
    getDescriptionField(item.description, "影片名称") ||
    "";
  if (distinctDownloadHashCount(item.ed2k_links, item.ed2k_link) > 1) {
    return true;
  }
  if (name && fromDesc && !resourceNamesAlign(fromDesc, name)) return true;
  if (name && isPackStyleTitle(title) && !resourceNamesAlign(title, name)) {
    return true;
  }
  return false;
}

export function guessNetcdnJacketUrls(code: string): string[] {
  const raw = String(code || "").trim().toUpperCase();
  if (!raw) return [];
  if (/^FC2/.test(raw) || /^\d+$/.test(raw)) return [];
  const m = raw.match(/^([A-Z]{2,15})[-_\s]?(\d{2,5})$/);
  if (!m) return [];
  const prefix = m[1].toLowerCase();
  const num = m[2].replace(/^0+/, "") || "0";
  const pad = num.padStart(5, '0');
  const cid = `${prefix}${pad}`;
  return [`https://jp.netcdn.space/digital/video/${cid}/${cid}pl.jpg`];
}

export function isUnreliableCoverHost(url: string) {
  return /dmm\.co\.jp|netcdn\.space|imagetwist\.com|gifyu\.com|imghost\.biz/i.test(
    url,
  );
}

export function isForumCoverHost(url: string) {
  return /sehuatang\.(net|org)|picdcd\.com|adipcd\.com|pkapic\.cc|imgccc\.com|11img\.com|yichkp\.com|ewrewej\.la|ymawv\.la|ldkms\.la|qpic\.ws|gdvdvb\.com|img906\.com|microsoftsa\.com|xunse\.pics|023pic3\.cc|pic26077\.cc|pic2607a\.cc|pic505hz\.cc|pid505st\.cc/i.test(
    url,
  );
}

function isValidPreviewUrl(src: string): boolean {
  const lower = src.toLowerCase();
  if (INVALID_IMAGE_MARKERS.some((marker) => lower.includes(marker))) {
    return false;
  }
  if (lower.includes(".txt")) return false;
  return (
    IMAGE_EXT_RE.test(lower) ||
    lower.includes("/tupian/forum/") ||
    lower.startsWith("/covers/")
  );
}

export function isJacketCoverUrl(url: string): boolean {
  const u = url.toLowerCase();
  if (u.startsWith("/covers/") || u.includes("/covers/")) return true;
  if (/netcdn\.space|pics\.dmm\.co\.jp|\.dmm\.co\.jp/.test(u)) return true;
  if (/[\/_\-]pl\.(jpe?g|png|webp)(\?|#|$)/.test(u)) return true;
  return false;
}

export function filterPreviewImagesInOrder(
  images?: string[] | null,
  limit = MAX_PREVIEW_IMAGES,
): string[] {
  const out: string[] = [];
  for (const src of images || []) {
    if (!src || !isValidPreviewUrl(src)) continue;
    out.push(src);
    if (out.length >= limit) break;
  }
  return out;
}

export function galleryPreviewImages(
  images?: string[] | null,
  /** ≤0 表示不截断（详情页要加载全部） */
  limit: number = MAX_PREVIEW_IMAGES,
): string[] {
  /** 优先片商/论坛图；写真等仅 imghost 时回退，避免封面全空 */
  const cap = limit <= 0 ? Number.MAX_SAFE_INTEGER : limit;
  const ordered = filterPreviewImagesInOrder(images, cap);
  const preferred = ordered.filter(
    (u) =>
      isJacketCoverUrl(u) ||
      isForumCoverHost(u) ||
      !isUnreliableCoverHost(u),
  );
  return preferred.length ? preferred : ordered;
}

function pathContainsNeedle(path: string, needle: string): boolean {
  if (!needle) return false;
  let pos = 0;
  while (pos < path.length) {
    const idx = path.indexOf(needle, pos);
    if (idx < 0) return false;
    if (idx > 0 && /\d/.test(path[idx - 1]!)) {
      pos = idx + 1;
      continue;
    }
    const after = idx + needle.length;
    if (after < path.length && /\d/.test(path[after]!)) {
      pos = idx + 1;
      continue;
    }
    return true;
  }
  return false;
}

export function imageUrlMatchesMakerCode(url: string, code: string): boolean {
  const raw = String(code || "").trim();
  if (!raw || !url) return false;
  const compact = raw.replace(/[-_\s]/g, "").toLowerCase();
  const parsed = parseMakerCode(raw);
  const prefix = (parsed?.prefix || "").toLowerCase();
  const numRaw = parsed?.parts?.[parsed.parts.length - 1] || "";
  const num = numRaw.replace(/^0+/, "") || numRaw;
  const needles = Array.from(
    new Set(
      [
        compact,
        raw.toLowerCase(),
        raw.replace(/-/g, "").toLowerCase(),
        prefix && num ? `${prefix}${num}` : "",
        prefix && num ? `${prefix}${num.padStart(3, "0")}` : "",
        prefix && num ? `${prefix}${num.padStart(5, "0")}` : "",
      ].filter(Boolean),
    ),
  );
  const path = url.toLowerCase().replace(/[^a-z0-9./_-]/g, '');
  return needles.some((n) => pathContainsNeedle(path, n));
}

export function pickCoversForCode(
  code: string,
  images?: string[] | null,
  limit = 4,
): string[] {
  const imgs = galleryPreviewImages(images).slice(
    0,
    Math.max(limit, MAX_PREVIEW_IMAGES),
  );
  if (!imgs.length) return [];
  const matched = imgs.filter((u) => imageUrlMatchesMakerCode(u, code));
  if (matched.length) return matched.slice(0, limit);
  const out: string[] = [];
  const seen = new Set<string>();
  for (const u of imgs) {
    if (!u || seen.has(u)) continue;
    if (isJacketCoverUrl(u) && !imageUrlMatchesMakerCode(u, code)) continue;
    seen.add(u);
    out.push(u);
    if (out.length >= limit) return out;
  }
  if (out.length) return out;
  return guessNetcdnJacketUrls(code).slice(0, limit);
}

export function pickPreviewsForResource(
  hash: string,
  name: string | null | undefined,
  ed2kLinks?: string[] | null,
  fallbackLink?: string | null,
  previewImages?: string[] | null,
  title?: string | null,
): string[] {
  const imgs = (previewImages || []).filter(Boolean);
  // 写真等：文件名常是艺名，番号在标题里
  const code =
    firstMakerCodeIn(name || "") ||
    firstMakerCodeIn(title || "") ||
    firstMakerCodeIn(
      [...normalizeEd2kLinks(ed2kLinks, fallbackLink)]
        .map((l) => parseEd2kLink(l)?.filename || "")
        .join("\n"),
    );

  if (code && imgs.length) {
    // 优先：URL 明确含当前番号（合集多图时勿把兄弟图混进 byCode）
    const matched = galleryPreviewImages(imgs).filter((u) =>
      imageUrlMatchesMakerCode(u, code),
    );
    if (matched.length) return matched.slice(0, MAX_PREVIEW_IMAGES);
    const byCode = pickCoversForCode(code, imgs, MAX_PREVIEW_IMAGES);
    if (byCode.length) return byCode;
  }

  const rawLinks = normalizeEd2kLinks(ed2kLinks, fallbackLink);
  const h = String(hash || "")
    .trim()
    .toUpperCase();
  if (h && imgs.length && rawLinks.length) {
    const idx = rawLinks.findIndex((link) => linkMatchesResourceHash(link, h));
    if (idx >= 0 && imgs[idx]) {
      return galleryPreviewImages([imgs[idx]]);
    }
  }

  if (code) {
    const guesses = guessNetcdnJacketUrls(code);
    if (guesses.length) return guesses;
  }
  return imgs.length === 1 ? galleryPreviewImages(imgs) : [];
}

export function getCardTitle(
  item: Pick<
    ResourceItem,
    "title" | "name" | "description" | "hash" | "ed2k_link" | "ed2k_links"
  >,
) {
  const title = item.title?.trim() || "";
  if (title) return title;
  const fromDesc =
    getDescriptionField(item.description, "资源名称") ||
    getDescriptionField(item.description, "影片名称");
  if (fromDesc) return fromDesc;
  return item.name?.trim() || "";
}

export function getDetailTitle(
  item: Pick<
    ResourceItem,
    "title" | "name" | "description" | "hash" | "ed2k_link" | "ed2k_links"
  >,
): string {
  const name = item.name?.trim() || "";
  if (name && !isMissingSubName(name, item.hash) && isPackBleedItem(item)) {
    return name;
  }
  return getCardTitle(item);
}

export function formatDescriptionLinesForItem(
  item: Pick<
    ResourceItem,
    | "description"
    | "name"
    | "size"
    | "title"
    | "hash"
    | "ed2k_link"
    | "ed2k_links"
  >,
): DescriptionLine[] {
  const name = item.name?.trim() || "";
  if (isPackBleedItem(item) && name) {
    const rows: DescriptionLine[] = [{ label: "资源名称", value: name }];
    if (Number(item.size) > 0) {
      rows.push({ label: "资源大小", value: formatByteSize(Number(item.size)) });
    }
    return rows;
  }

  const lines = formatDescriptionLines(item.description);
  if (!name) return lines;

  const descName =
    lines.find((l) => l.label === "资源名称" || l.label === "影片名称")
      ?.value || "";
  const mismatched = !descName || !resourceNamesAlign(descName, name);
  if (!mismatched) return lines;

  const next = lines.map((row) => {
    if (row.label === "资源名称" || row.label === "影片名称") {
      return { ...row, value: name };
    }
    if (
      (row.label === "资源大小" || row.label === "文件大小") &&
      Number(item.size) > 0
    ) {
      return { ...row, value: formatByteSize(Number(item.size)) };
    }
    return row;
  });

  if (!next.some((l) => l.label === "资源名称" || l.label === "影片名称")) {
    next.unshift({ label: "资源名称", value: name });
  }
  return next;
}

export function normalizeResourceView(item: ResourceItem): ResourceItem {
  const bleed = isPackBleedItem(item);
  const rawImgs = item.preview_images || [];
  const picked = pickPreviewsForResource(
    item.hash,
    item.name,
    item.ed2k_links,
    item.ed2k_link,
    rawImgs,
    item.title,
  );
  let previews = bleed
    ? picked
    : // 详情/列表同源：不过滤上限；列表卡片自行按槽位截断展示
      galleryPreviewImages(rawImgs, 0);
  if (!previews.length) {
    previews = picked;
  } else if (!bleed && picked.length) {
    // 帖内 netcdn 夹克 cid 错误（如 1sone00968）时，改用按番号选取结果
    const badJacket = previews.some(
      (u) =>
        isJacketCoverUrl(u) &&
        picked.some((p) => isJacketCoverUrl(p) && p !== u),
    );
    if (badJacket) previews = picked;
  }

  const links = linksForResourceHash(
    item.hash,
    item.ed2k_links,
    item.ed2k_link,
  );
  const primary = links[0] || item.ed2k_link || "";
  const name = (item.name || "").trim();
  const useName =
    bleed && name && !isMissingSubName(name, item.hash) ? name : null;

  let size = Number(item.size || 0);
  for (const link of links) {
    const parsed = parseEd2kLink(link);
    if (parsed?.size) {
      size = Number(parsed.size);
      break;
    }
    const magnet = parseMagnetLink(link);
    if (magnet?.size) {
      size = Number(magnet.size);
      break;
    }
  }

  const description = useName
    ? [
        `【资源名称】：${useName}`,
        size > 0 ? `【资源大小】：${formatByteSize(size)}` : "",
      ]
        .filter(Boolean)
        .join("\n")
    : item.description;

  const apiFiles = Array.isArray(item.files)
    ? item.files.filter((f) => f && String(f.path || "").trim())
    : [];
  const apiFilesUseful = apiFiles.some((f) => {
    const path = String(f.path || "");
    const base = path.split("/").pop() || path;
    const ext = String(f.extension || "")
      .trim()
      .replace(/^\./, "");
    if (ext && /^[a-z0-9]{1,8}$/i.test(ext)) return true;
    return /\.[a-z0-9]{2,5}$/i.test(base);
  });

  const builtFiles = links.map((link, index) => {
    const parsed = parseEd2kLink(link);
    const magnet = parsed ? null : parseMagnetLink(link);
    const path =
      parsed?.filename ||
      magnet?.filename ||
      // 无 dn 的磁力：不要把帖子标题/中文名当成「无后缀文件」
      (parsed ? name || item.name || "" : "") ||
      "";
    const fromName = String(path || "");
    let extension = "";
    if (fromName.includes(".")) {
      const pop = fromName.split(".").pop() || "";
      if (
        pop &&
        pop.length <= 5 &&
        !/\s/.test(pop) &&
        /^[a-z0-9]+$/i.test(pop)
      ) {
        extension = pop.toLowerCase();
      }
    }
    if (!extension) {
      const blob = `${item.title || ""}\n${name || ""}\n${fromName}`;
      const m = blob.match(
        /(?:^|[.\s\[\(（_/|=-])(mp4|mkv|avi|wmv|rmvb|m2ts|ts|mov|flv|mpeg|mpg|m4v|webm|rm|zip|rar|7z|iso)(?:$|[.\s\]\)）_/|=-])/i,
      );
      if (m) extension = m[1].toLowerCase();
    }
    return {
      index: index + 1,
      path,
      size: Number(parsed?.size || magnet?.size || size || 0),
      extension,
    };
  }).filter((f) => String(f.path || "").trim());

  const files = apiFilesUseful ? apiFiles : builtFiles;
  const filesCount =
    apiFilesUseful && apiFiles.length
      ? Number(item.files_count || apiFiles.length)
      : files.length || links.length;

  return {
    ...item,
    title: useName || item.title,
    name: name || item.name,
    description,
    preview_images: previews,
    ed2k_links: links,
    ed2k_link: primary,
    link_kind: linkKindOf(primary) || item.link_kind,
    size: size || item.size,
    single_file: files.length <= 1,
    files_count: filesCount,
    files,
  };
}

export { MAX_PREVIEW_IMAGES };
export type { ResourcePick };
