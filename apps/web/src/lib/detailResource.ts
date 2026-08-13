/** 详情页用：对齐色花 `utils/resource` 的轻量子集 */

import {
  formatDescriptionLines,
  formatDescriptionLinesForItem,
  getDescriptionField,
  getDetailTitle,
  linkKindOf,
  linksForResourceHash,
  normalizeResourceView,
  type DescriptionLine,
} from "@/lib/resourceView";

export type { DescriptionLine };

export {
  formatDescriptionLines,
  formatDescriptionLinesForItem,
  getDescriptionField,
  getDetailTitle,
  linkKindOf,
  linksForResourceHash,
  normalizeResourceView,
};

export function getExtractPassword(item: {
  extract_password?: string | null;
  description?: string | null;
}): string | null {
  const fromCol = item.extract_password?.trim();
  if (fromCol) return fromCol;
  return (
    getDescriptionField(item.description, "解压密码") ||
    getDescriptionField(item.description, "访问码") ||
    getDescriptionField(item.description, "分享码")
  );
}

/** 当前 hash 下的下载链（等同 sehua linksForResourceHash） */
export function linksForResource(item: {
  hash?: string | null;
  ed2k_link?: string | null;
  ed2k_links?: string[] | null;
}): string[] {
  return linksForResourceHash(item.hash, item.ed2k_links, item.ed2k_link);
}

export function getEd2kCopyText(item: {
  hash?: string | null;
  ed2k_link?: string | null;
  ed2k_links?: string[] | null;
}): string {
  return linksForResource(item).join("\n");
}

export function getEd2kLinkCount(item: {
  hash?: string | null;
  ed2k_link?: string | null;
  ed2k_links?: string[] | null;
}): number {
  return linksForResource(item).length;
}

export function shortSourceLabel(url: string): string {
  try {
    const u = new URL(url);
    const tid = u.pathname.match(/thread-(\d+)/)?.[1];
    if (tid) return `${u.hostname} · 帖子 ${tid}`;
    return u.hostname + (u.pathname === "/" ? "" : u.pathname);
  } catch {
    return url.length > 42 ? `${url.slice(0, 40)}…` : url;
  }
}

export function copyAllLabel(item: {
  link_kind?: string | null;
  hash?: string | null;
  ed2k_link?: string | null;
  ed2k_links?: string[] | null;
}): string {
  const count = getEd2kLinkCount(item);
  const kind = normalizeLinkKind(
    item.link_kind || linkKindOf(item.ed2k_link || item.ed2k_links?.[0]),
  );
  if (count > 1) return `复制全部 (${count})`;
  if (kind === "magnet") return "复制磁力";
  if (kind === "115share") return "复制分享";
  return "复制链接";
}

/** API 用 share115，色花 UI 用 115share */
export function normalizeLinkKind(
  kind?: string | null,
): "ed2k" | "magnet" | "stub" | "115share" | "other" {
  const k = (kind || "").trim().toLowerCase();
  if (k === "share115" || k === "115share") return "115share";
  if (k === "magnet") return "magnet";
  if (k === "ed2k") return "ed2k";
  if (k === "stub" || k === "unavailable") return "stub";
  return "other";
}

const ARCHIVE_EXT_RE = /\.(zip|rar|7z)(?:\?|#|$)/i;

export function isArchiveFilename(name?: string | null): boolean {
  return ARCHIVE_EXT_RE.test((name || "").trim());
}

export function isArchiveDownloadLink(link?: string | null): boolean {
  const raw = (link || "").trim();
  if (!raw) return false;
  const ed2k = raw.match(/^ed2k:\/\/\|file\|([^|]+)\|/i);
  if (ed2k?.[1]) {
    try {
      return isArchiveFilename(decodeURIComponent(ed2k[1]));
    } catch {
      return isArchiveFilename(ed2k[1]);
    }
  }
  const dn = raw.match(/[?&]dn=([^&]+)/i);
  if (dn?.[1]) {
    try {
      return isArchiveFilename(decodeURIComponent(dn[1].replace(/\+/g, " ")));
    } catch {
      return isArchiveFilename(dn[1]);
    }
  }
  return ARCHIVE_EXT_RE.test(raw);
}

export function hasArchiveEd2k(item: {
  name?: string | null;
  hash?: string | null;
  ed2k_link?: string | null;
  ed2k_links?: string[] | null;
}): boolean {
  if (isArchiveFilename(item.name)) return true;
  return linksForResource(item).some((link) => isArchiveDownloadLink(link));
}

export function linkSectionTitle(linkKind?: string | null): string {
  const kind = normalizeLinkKind(linkKind);
  if (kind === "115share") return "115 分享";
  if (kind === "magnet") return "磁力链接";
  return "下载链接";
}
