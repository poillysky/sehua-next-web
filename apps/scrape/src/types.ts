export type SourceRun = {
  id: string;
  ok: boolean;
  ms: number;
  mode: "meta" | "cover";
  error?: string;
  /** cid-retry / region-blocked / parallel 等补充说明 */
  detail?: string;
};

export type ScrapeMeta = {
  code: string;
  title: string;
  /** 中文标题（色花堂/Airav/Javdb 等） */
  titleZh?: string;
  originalTitle?: string;
  plot?: string;
  premiered?: string;
  /** 发行方（レーベル / 发行商） */
  publisher?: string;
  /** 制片方（メーカー / 制作商） */
  studio?: string;
  makers?: string[];
  actors?: string[];
  genres?: string[];
  runtime?: number | null;
  /** 0–10 用户评分（若源提供） */
  userRating?: number | null;
  director?: string;
  series?: string;
  /** DMM CID / 发行码（如 53dv01588） */
  productId?: string;
  poster?: string | null;
  /** 竖版海报 URL（DMM ps）；缺省时可由 pl 右侧裁剪 */
  portrait?: string | null;
  fanart?: string[];
  source: string;
  scrapeKind?: string;
  sourcesTried?: string[];
  /** 各数据源尝试结果（含耗时） */
  sourceRuns?: SourceRun[];
  /** 各字段最终取自哪个源 */
  fieldSources?: Record<string, string>;
  /** 字段最终来源 + 对应 sourceRun 耗时（供 UI 如实展示） */
  fieldTimings?: Record<
    string,
    { id: string; ms: number; ok: boolean; mode?: string }
  >;
  scrapedAt: string;
  coverLocal?: string | null;
  /** 按海报剪裁配置生成的竖版海报本地路径（导出 Emby 优先） */
  posterLocal?: string | null;
  ok: boolean;
  message?: string;
};

/** 字段优先级（任务字段）；空数组=未配置，回退全局 kind 链 */
export type FieldPriority = {
  cover?: string[];
  /** 中文标题（色花堂优先） */
  titleZh?: string[];
  /** 简介 / 剧情 */
  outline?: string[];
  /** 制片方（メーカー / 制作商） */
  studio?: string[];
  actors?: string[];
  /** 标签 / 类型（genres） */
  tags?: string[];
  /** 系列 */
  series?: string[];
  /** 以下仅兼容旧配置 / 内部合并，UI 不再暴露 */
  title?: string[];
  publisher?: string[];
  originalTitle?: string[];
  poster?: string[];
  extraFanart?: string[];
  userRating?: string[];
  premiered?: string[];
  runtime?: string[];
  director?: string[];
};

/** 缩略图下载策略：priority=按源优先级；size=全候选比文件大小 */
export type CoverDownloadStrategy = "priority" | "size";

export type PosterCropMode = "right" | "none" | "face";
export type PosterCropRatioId = "full" | "emby";

export type PosterCropConfig = {
  byKind?: Record<string, PosterCropMode | string>;
  ratio?: PosterCropRatioId | string;
  cropDownloadedPoster?: boolean;
  preferCropIfBetter?: boolean;
};

export type ScrapeRequest = {
  code?: string;
  preferCoverUrl?: string;
  /** 色花堂/论坛帖标题，作中文标题兜底（对齐 mdc-ng 色花堂源） */
  preferTitle?: string;
  /** 色花堂帖内【出演女优】 */
  preferActors?: string[];
  /** 本地高质量元数据种子（不含封面；poster 一律网络） */
  preferLocal?: {
    titleZh?: string;
    actors?: string[];
    outline?: string;
    tags?: string[];
    studio?: string;
    series?: string;
  };
  force?: boolean;
  /** 刮削方案：japan_censored / japan_uncensored / fc2 / china / western */
  kind?: string;
  region?: string;
  metaSources?: string[];
  coverSources?: string[];
  fieldPriority?: FieldPriority;
  coverDownloadStrategy?: CoverDownloadStrategy;
  posterCrop?: PosterCropConfig;
  /** 导出双通道：fast=快源 / slow=慢源（过盾）；分队列互不堵 */
  channel?: "fast" | "slow" | string;
};
