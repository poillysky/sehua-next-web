/**
 * 与 scrape/src/sourceFields.ts 对齐：各站可贡献的任务字段。
 * 设置页备忘 / 字段优先级选源均以此为准。
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

const C = (...fields: SourceFieldCap[]): ReadonlySet<SourceFieldCap> =>
  new Set(fields);

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
  dmm: C("cover", "titleJa", "outline", "actors", "tags", "studio", "series"),
  fc2: C("cover", "titleJa", "outline", "tags", "studio"),
  fc2_hub: C("cover", "titleZh", "titleJa", "outline", "tags", "studio"),
  fd2ppv: C("cover", "titleJa", "actors", "tags", "studio"),
  freejavbt: C("titleJa", "actors", "tags", "series"),
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
  javdb: C("cover", "titleJa", "actors", "tags", "studio", "series"),
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

const LABELS: Record<SourceFieldCap, string> = {
  cover: "封面",
  titleZh: "中文标题",
  titleJa: "日文标题",
  outline: "简介",
  actors: "女优",
  tags: "标签",
  studio: "制片",
  series: "系列",
  publisher: "发行商",
};

export function sourceHasField(sourceId: string, field: SourceFieldCap): boolean {
  const caps = SOURCE_FIELD_CAPS[sourceId];
  if (!caps) return true;
  return caps.has(field);
}

/** 备忘展示：按能力拆中文 / 日文 / 共通 */
export function formatSourceFieldGroups(sourceId: string): {
  fieldsZh: string;
  fieldsJa: string;
  fieldsCommon: string;
} {
  const caps = SOURCE_FIELD_CAPS[sourceId];
  if (!caps) {
    return { fieldsZh: "—", fieldsJa: "—", fieldsCommon: "—" };
  }
  const zh: SourceFieldCap[] = [];
  const ja: SourceFieldCap[] = [];
  const common: SourceFieldCap[] = [];
  for (const f of caps) {
    if (f === "cover") common.push(f);
    else if (f === "titleZh" || f === "outline") zh.push(f);
    else if (f === "titleJa") ja.push(f);
    else if (f === "tags" || f === "actors") {
      // 中日站都可能有；有 titleZh 的站把标签/女优算中文侧，否则算日文侧
      if (caps.has("titleZh")) zh.push(f);
      else ja.push(f);
    } else if (f === "studio" || f === "series" || f === "publisher") {
      if (caps.has("titleZh") && !caps.has("titleJa")) zh.push(f);
      else ja.push(f);
    }
  }
  const fmt = (xs: SourceFieldCap[]) =>
    xs.length ? xs.map((x) => LABELS[x]).join(" · ") : "无";
  return {
    fieldsZh: fmt(zh),
    fieldsJa: fmt(ja),
    fieldsCommon: fmt(common),
  };
}
