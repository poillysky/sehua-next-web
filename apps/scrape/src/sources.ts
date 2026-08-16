import type { ScrapeMeta } from "./types.js";

/** 对齐 mdc-ng / sehuatang 常用源 */
export type SourceId =
  | "dmm"
  | "mgstage"
  | "libredmm"
  | "javlibrary"
  | "avbase"
  | "javdb"
  | "javbus"
  | "jav321"
  | "avmoo"
  | "sevenmmtv"
  | "iqqtv"
  | "airav"
  | "airav_io"
  | "freejavbt"
  | "miss_av"
  | "carib"
  | "avsox"
  | "fc2"
  | "fc2_hub"
  | "fd2ppv"
  | "madou"
  | "madouqu"
  | "xiao_huang_shu"
  | "theporndb"
  | "forum";

/** 刮削方案 = maker-fs 七区 */
export type KindId =
  | "japan_censored"
  | "japan_gravure"
  | "japan_uncensored"
  | "japan_amateur"
  | "fc2"
  | "china"
  | "western";

export type SourceDef = {
  id: SourceId;
  name: string;
  group: string;
  defaultUrl: string;
  probePath?: string;
  /** direct=直连 | proxy=代理直连 | proxy_flare=代理过盾 | proxy_adaptive=不稳定过盾（先直连/代理，遇盾再 Flare） */
  access?: "direct" | "proxy" | "proxy_flare" | "proxy_adaptive";
};

export const SOURCE_CATALOG: SourceDef[] = [
  { id: "airav_io", name: "Airav_io", group: "av", defaultUrl: "https://airav.io/cn", probePath: "/", access: "proxy_adaptive" },
  { id: "avbase", name: "Avbase", group: "av", defaultUrl: "https://www.avbase.net", probePath: "/", access: "proxy_adaptive" },
  { id: "avmoo", name: "Avmoo", group: "av", defaultUrl: "https://avmoo.shop", probePath: "/cn", access: "proxy_flare" },
  { id: "avsox", name: "Avsox", group: "uncensored", defaultUrl: "https://avsox.click", probePath: "/cn", access: "proxy_flare" },
  { id: "carib", name: "Carib", group: "uncensored", defaultUrl: "https://www.caribbeancom.com", probePath: "/", access: "proxy" },
  { id: "dmm", name: "Dmm", group: "av", defaultUrl: "https://www.dmm.co.jp", probePath: "/", access: "proxy" },
  { id: "fc2", name: "Fc2", group: "fc2", defaultUrl: "https://adult.contents.fc2.com", probePath: "/", access: "proxy" },
  { id: "fc2_hub", name: "Fc2_hub", group: "fc2", defaultUrl: "https://javten.com", probePath: "/", access: "proxy_flare" },
  { id: "fd2ppv", name: "Fd2ppv", group: "fc2", defaultUrl: "https://fd2ppv.cc", probePath: "/", access: "proxy_flare" },
  { id: "freejavbt", name: "Freejavbt", group: "av", defaultUrl: "https://freejavbt.com", probePath: "/", access: "proxy" },
  { id: "jav321", name: "Jav321", group: "av", defaultUrl: "https://www.jav321.com", probePath: "/", access: "proxy" },
  { id: "javbus", name: "Javbus", group: "av", defaultUrl: "https://www.javbus.com", probePath: "/", access: "proxy" },
  { id: "javdb", name: "Javdb", group: "av", defaultUrl: "https://javdb.com", probePath: "/", access: "proxy_flare" },
  { id: "javlibrary", name: "Javlibrary", group: "av", defaultUrl: "https://www.javlibrary.com/cn", probePath: "/", access: "proxy_flare" },
  { id: "madou", name: "Madou", group: "chinese", defaultUrl: "https://madou.club", probePath: "/", access: "proxy" },
  { id: "madouqu", name: "Madouqu", group: "chinese", defaultUrl: "https://madouqu.com", probePath: "/", access: "proxy" },
  {
    id: "xiao_huang_shu",
    name: "Xiao_huang_shu",
    group: "chinese",
    defaultUrl: "https://xchina.co",
    probePath: "/",
    access: "proxy",
  },
  { id: "mgstage", name: "Mgstage", group: "av", defaultUrl: "https://www.mgstage.com", probePath: "/", access: "proxy_adaptive" },
  {
    id: "libredmm",
    name: "LibreDMM",
    group: "av",
    defaultUrl: "https://www.libredmm.com",
    probePath: "/",
    access: "proxy",
  },
  { id: "miss_av", name: "Miss_av", group: "av", defaultUrl: "https://missav123.com", probePath: "/", access: "proxy_flare" },
  { id: "sevenmmtv", name: "7mmtv", group: "av", defaultUrl: "https://7mmtv.sx/zh", probePath: "/", access: "proxy_adaptive" },
  { id: "iqqtv", name: "Iqqtv", group: "av", defaultUrl: "https://iqq5.xyz/cn", probePath: "/", access: "direct" },
  { id: "theporndb", name: "ThePornDB", group: "western", defaultUrl: "https://api.theporndb.net", probePath: "/", access: "proxy" },
  { id: "airav", name: "Airav", group: "av", defaultUrl: "https://www.airav.wiki", probePath: "/", access: "proxy_adaptive" },
];

export const KNOWN_SOURCES = new Set(SOURCE_CATALOG.map((s) => s.id));

/** 与 api scrape_profiles 一致：短链快源 */
const AV_META: SourceId[] = [
  "libredmm",
  "javbus",
  "dmm",
  "javdb",
  "airav",
];

const UNCENSORED_META: SourceId[] = [
  "carib",
  "javbus",
  "avsox",
  "javdb",
  "airav",
];

const AMATEUR_META: SourceId[] = [
  "libredmm",
  "javbus",
  "dmm",
  "javdb",
  "airav",
];

export const DEFAULT_KIND_SOURCES: Record<
  KindId,
  { meta: SourceId[]; cover: SourceId[] }
> = {
  japan_censored: { meta: [...AV_META], cover: [...AV_META] },
  japan_gravure: { meta: [...AV_META], cover: [...AV_META] },
  japan_uncensored: {
    meta: [...UNCENSORED_META],
    cover: [...UNCENSORED_META],
  },
  japan_amateur: { meta: [...AMATEUR_META], cover: [...AMATEUR_META] },
  fc2: {
    meta: ["fc2", "fd2ppv", "javdb"],
    cover: ["fc2", "fd2ppv", "javbus"],
  },
  china: {
    meta: ["madouqu", "madou", "xiao_huang_shu"],
    cover: ["madouqu", "madou", "javbus"],
  },
  western: {
    meta: ["airav_io", "javdb", "miss_av"],
    cover: ["javbus", "airav_io", "javdb"],
  },
};

/** @deprecated use DEFAULT_KIND_SOURCES */
export const DEFAULT_REGION_SOURCES = DEFAULT_KIND_SOURCES as Record<
  string,
  { meta: SourceId[]; cover: SourceId[] }
>;

export type PartialFromSource = Partial<ScrapeMeta> & { source: string };

const DISABLED_BY_DEFAULT = new Set<SourceId>([
  "mgstage",
  "fc2_hub",
  "theporndb",
]);

export function normalizeSourceList(
  raw: unknown,
  fallback: SourceId[],
): SourceId[] {
  /** 有传入列表时原样保留（设置页为准）；仅空列表才用出厂 fallback，不向用户列表塞默认源 */
  const out: SourceId[] = [];
  const seen = new Set<string>();
  for (const item of Array.isArray(raw) ? raw : []) {
    const id = String(item || "")
      .trim()
      .toLowerCase() as SourceId;
    if (
      !id ||
      !KNOWN_SOURCES.has(id) ||
      seen.has(id) ||
      DISABLED_BY_DEFAULT.has(id)
    ) {
      continue;
    }
    seen.add(id);
    out.push(id);
  }
  if (out.length) return out;
  return fallback.filter((s) => !DISABLED_BY_DEFAULT.has(s));
}

export function detectKind(code: string, region?: string): KindId {
  const c = String(code || "").trim().toUpperCase();
  if (/^FC2/.test(c)) return "fc2";
  const rid = String(region || "").trim();
  if (
    rid === "japan_censored" ||
    rid === "japan_gravure" ||
    rid === "japan_uncensored" ||
    rid === "japan_amateur" ||
    rid === "china" ||
    rid === "western" ||
    rid === "fc2"
  ) {
    return rid;
  }
  return "japan_censored";
}

export function resolveOrders(opts?: {
  kind?: string;
  region?: string;
  code?: string;
  metaSources?: unknown;
  coverSources?: unknown;
}): { kind: KindId; meta: SourceId[]; cover: SourceId[] } {
  const kind = (opts?.kind as KindId) || detectKind(opts?.code || "", opts?.region);
  const def = DEFAULT_KIND_SOURCES[kind] || DEFAULT_KIND_SOURCES.japan_censored;
  return {
    kind,
    meta: normalizeSourceList(opts?.metaSources, def.meta),
    cover: normalizeSourceList(opts?.coverSources, def.cover),
  };
}
