/**
 * 各站可贡献的任务字段（与设置页「数据源」备忘登记一致）。
 * 合并元数据时：源未登记的字段一律丢弃，避免误用（如 airav_io 填系列）。
 *
 * titleJa：日文原题（写入 title / originalTitle，不作 titleZh）
 */
export type SourceFieldCap =
  | "cover"
  | "titleZh"
  | "titleJa"
  | "outline"
  | "actors"
  | "tags"
  | "studio"
  | "series"
  | "publisher";

const C = (
  ...fields: SourceFieldCap[]
): ReadonlySet<SourceFieldCap> => new Set(fields);

/** 与 ScrapeSourcesTab SOURCE_NOTES 字段能力对齐 */
export const SOURCE_FIELD_CAPS: Record<string, ReadonlySet<SourceFieldCap>> = {
  airav_io: C("cover", "titleZh", "outline", "actors", "tags", "studio"),
  airav: C("cover", "titleZh", "outline", "actors", "tags", "studio"),
  avbase: C("cover", "titleJa", "outline", "actors", "tags", "studio", "series"),
  avmoo: C("cover", "titleJa", "actors", "tags", "studio", "series", "publisher"),
  avsox: C("cover", "titleJa", "actors", "tags", "studio"),
  carib: C(
    "cover",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  dmm: C(
    "cover",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  fc2: C("cover", "titleJa", "outline", "tags", "studio"),
  fc2_hub: C("cover", "titleZh", "titleJa", "outline", "tags", "studio"),
  fd2ppv: C("cover", "titleJa", "actors", "tags", "studio"),
  freejavbt: C("cover", "titleJa", "actors", "tags", "series"),
  jav321: C(
    "cover",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  javbus: C(
    "cover",
    "titleJa",
    "actors",
    "tags",
    "studio",
    "series",
    "publisher",
  ),
  javdb: C(
    "cover",
    "titleJa",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  javlibrary: C("cover", "titleJa", "actors", "tags", "studio", "publisher"),
  libredmm: C(
    "cover",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "studio",
    "publisher",
  ),
  madou: C("cover", "titleZh", "actors", "tags", "studio"),
  madouqu: C("cover", "titleZh", "actors", "studio"),
  xiao_huang_shu: C("cover", "titleZh", "actors", "studio"),
  mgstage: C(
    "cover",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  miss_av: C(
    "cover",
    "titleZh",
    "titleJa",
    "outline",
    "actors",
    "tags",
    "series",
    "publisher",
  ),
  sevenmmtv: C("cover", "titleZh", "actors", "tags", "studio", "publisher"),
  iqqtv: C(
    "cover",
    "titleZh",
    "outline",
    "actors",
    "tags",
    "studio",
    "series",
  ),
  theporndb: C("cover", "titleJa", "outline", "actors", "studio"),
};

export function sourceHasField(
  sourceId: string | undefined,
  field: SourceFieldCap,
): boolean {
  const id = String(sourceId || "").trim();
  if (!id) return false;
  const caps = SOURCE_FIELD_CAPS[id];
  // 未登记源：保守放行，避免新源被全挡
  if (!caps) return true;
  return caps.has(field);
}

/** 按登记裁剪单次命中：未声明字段清空，避免进入合并池 */
export function sanitizeHitBySourceCaps<T extends { source?: string }>(
  hit: T,
): T {
  const id = String(hit.source || "").trim();
  const caps = SOURCE_FIELD_CAPS[id];
  if (!caps) return hit;
  const h = { ...hit } as T & Record<string, unknown>;

  if (!caps.has("cover")) {
    h.poster = null;
    h.portrait = null;
    h.fanart = [];
  }
  if (!caps.has("titleZh")) {
    h.titleZh = undefined;
  }
  if (!caps.has("titleJa")) {
    // 无日文题能力时，勿把机翻/中文当 originalTitle 主源；保留 title 仅若同时有 titleZh
    if (!caps.has("titleZh")) {
      h.title = "";
      h.originalTitle = undefined;
    } else {
      h.originalTitle = undefined;
    }
  }
  if (!caps.has("outline")) {
    h.plot = "";
  }
  if (!caps.has("actors")) {
    h.actors = [];
  }
  if (!caps.has("tags")) {
    h.genres = [];
  }
  if (!caps.has("studio")) {
    h.studio = undefined;
    h.makers = undefined;
  }
  if (!caps.has("series")) {
    h.series = undefined;
  }
  if (!caps.has("publisher")) {
    h.publisher = undefined;
  }
  return h;
}

const FP_CAP: Record<string, SourceFieldCap> = {
  cover: "cover",
  titleZh: "titleZh",
  outline: "outline",
  actors: "actors",
  tags: "tags",
  studio: "studio",
  series: "series",
  publisher: "publisher",
  poster: "cover",
  extraFanart: "cover",
  title: "titleJa",
  originalTitle: "titleJa",
};

/** 字段优先级里去掉「该站未登记」的源 */
export function filterFieldPriorityByCaps<T extends Record<string, string[] | undefined>>(
  fp: T | undefined,
): T | undefined {
  if (!fp) return fp;
  const out = { ...fp } as T;
  for (const [key, list] of Object.entries(fp)) {
    if (!Array.isArray(list)) continue;
    const cap = FP_CAP[key];
    if (!cap) continue;
    (out as Record<string, string[]>)[key] = list.filter((sid) =>
      sourceHasField(sid, cap),
    );
  }
  return out;
}
