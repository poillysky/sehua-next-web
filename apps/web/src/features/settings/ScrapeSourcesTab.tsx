"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RefreshCw } from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import {
  patchScrapeSource,
  putScrape,
  testScrapeSources,
  type ScrapeConfig,
  type ScrapeFieldPriority,
  type ScrapeRegionProfile,
  type ScrapeSourceCard,
} from '@/lib/api';
import { formatSourceFieldGroups } from '@/lib/scrapeSourceFields';

const KIND_ROWS: Array<{ id: string; label: string }> = [
  { id: "japan_censored", label: "日本有码" },
  { id: "japan_gravure", label: "日本写真" },
  { id: "japan_uncensored", label: "日本无码" },
  { id: "japan_amateur", label: "日本素人" },
  { id: "fc2", label: "FC2" },
  { id: "china", label: "国产无码" },
  { id: "western", label: "欧美无码" },
];

/** 与任务字段一致：封面 / 中文标题 / 简介 / 制片方 / 女优 / 标签 / 系列 */
const FIELD_ROWS: Array<{ id: keyof ScrapeFieldPriority; label: string }> = [
  { id: "cover", label: "封面图" },
  { id: "titleZh", label: "中文标题" },
  { id: "outline", label: "简介" },
  { id: "studio", label: "制片方" },
  { id: "actors", label: "女优" },
  { id: "tags", label: "标签" },
  { id: "series", label: "系列" },
];

/** 与后端 derive_sources_from_fields 一致：快源靠前 */
function deriveSourcesFromFields(fp: ScrapeFieldPriority): {
  metaSources: string[];
  coverSources: string[];
} {
  const cover = fp.cover || [];
  const seen = new Set<string>();
  const meta: string[] = [];
  for (const key of [
    "cover",
    "series",
    "studio",
    "tags",
    "actors",
    "titleZh",
    "outline",
  ] as const) {
    for (const sid of fp[key] || []) {
      if (seen.has(sid)) continue;
      seen.add(sid);
      meta.push(sid);
    }
  }
  return {
    metaSources: meta.length ? meta : [...cover],
    coverSources: cover.length ? cover : [...meta],
  };
}

const DEFAULT_FIELD_PRIORITY: ScrapeFieldPriority = {
  cover: ["javbus"],
  titleZh: ["iqqtv", "airav_io", "sevenmmtv"],
  outline: ["iqqtv", "airav_io"],
  studio: ["javbus", "airav_io"],
  actors: ["javbus", "airav_io", "sevenmmtv"],
  tags: ["javbus", "airav_io"],
  series: ["javbus", "freejavbt"],
};

function fieldPriorityFromProfile(
  p: ScrapeRegionProfile | undefined,
): ScrapeFieldPriority {
  const fp = p?.fieldPriority;
  if (fp) {
    const legacyPub = (fp as { publisher?: string[] }).publisher;
    const legacyGenres = (fp as { genres?: string[] }).genres;
    return {
      cover: Array.isArray(fp.cover) ? fp.cover : [],
      titleZh: Array.isArray(fp.titleZh) ? fp.titleZh : [],
      outline: Array.isArray(fp.outline)
        ? fp.outline
        : Array.isArray(legacyPub)
          ? legacyPub
          : [],
      studio: Array.isArray(fp.studio) ? fp.studio : [],
      actors: Array.isArray(fp.actors) ? fp.actors : [],
      tags: Array.isArray(fp.tags)
        ? fp.tags
        : Array.isArray(legacyGenres)
          ? legacyGenres
          : [],
      series: Array.isArray(fp.series) ? fp.series : [],
    };
  }
  return { ...DEFAULT_FIELD_PRIORITY };
}

const SOURCE_GROUP_LABEL: Record<string, string> = {
  av: "有码 / 综合",
  uncensored: "无码",
  fc2: "FC2",
  chinese: "国产",
  western: "欧美",
};

/** 访问方式：与 api SOURCE_CATALOG.access 对齐 */
type SourceAccess = "direct" | "proxy" | "proxy_flare";

const ACCESS_FALLBACK: Record<string, SourceAccess> = {
  freejavbt: "proxy",
  madou: "proxy",
  iqqtv: "direct",
  carib: "proxy",
  dmm: "proxy",
  fc2: "proxy",
  jav321: "proxy",
  javbus: "proxy",
  libredmm: "proxy",
  theporndb: "proxy",
  airav_io: "proxy",
  airav: "proxy",
  avbase: "proxy",
  avmoo: "proxy_flare",
  avsox: "proxy_flare",
  javdb: "proxy_flare",
  javlibrary: "proxy_flare",
  miss_av: "proxy_flare",
  sevenmmtv: "proxy",
  fc2_hub: "proxy_flare",
  fd2ppv: "proxy_flare",
  madouqu: "proxy",
  xiao_huang_shu: "proxy",
  mgstage: "proxy_flare",
};

const ACCESS_SECTIONS: Array<{
  id: SourceAccess;
  title: string;
  hint: string;
}> = [
  {
    id: "direct",
    title: "直连",
    hint: "可不配代理；遇墙再开",
  },
  {
    id: "proxy",
    title: "代理直连",
    hint: "需代理，不过 Cloudflare 浏览器盾",
  },
  {
    id: "proxy_flare",
    title: "代理过盾",
    hint: "代理 + FlareSolverr",
  },
];

function resolveAccess(s: { id: string; access?: string }): SourceAccess {
  const raw = String(s.access || ACCESS_FALLBACK[s.id] || "proxy")
    .trim()
    .toLowerCase();
  if (raw === "direct" || raw === "proxy" || raw === "proxy_flare") return raw;
  return "proxy";
}

/** 二级·地区：日 → 中 → 美 */
type SourceRegion = "japan" | "china" | "western";

const REGION_SECTIONS: Array<{ id: SourceRegion; title: string }> = [
  { id: "japan", title: "日本" },
  { id: "china", title: "国产" },
  { id: "western", title: "欧美" },
];

function resolveRegion(s: { id: string; group?: string }): SourceRegion {
  const g = String(s.group || "").toLowerCase();
  if (g === "chinese") return "china";
  if (g === "western") return "western";
  return "japan";
}

/** 三级·元数据语言：中文 vs 地区对应语言 */
type SourceMetaLang = "zh" | "native";

const META_LANG_ORDER: SourceMetaLang[] = ["zh", "native"];

function metaLangTitle(region: SourceRegion, meta: SourceMetaLang): string {
  if (meta === "zh") return "中文";
  if (region === "japan") return "日语";
  if (region === "china") return "中文";
  return "英语";
}

/** 明确以中文元数据为主的源（含国产站） */
const ZH_META_SOURCE_IDS = new Set([
  "airav_io",
  "airav",
  "iqqtv",
  "sevenmmtv",
  "madou",
  "madouqu",
  "xiao_huang_shu",
]);

function resolveMetaLang(s: { id: string; group?: string }): SourceMetaLang {
  if (String(s.group || "").toLowerCase() === "chinese") return "zh";
  if (ZH_META_SOURCE_IDS.has(s.id)) return "zh";
  return "native";
}

/** 各站备忘：须写清哪些字段中文、哪些日文（封面等无语言写共通） */
const SOURCE_NOTES: Record<
  string,
  {
    blurb: string;
    /** 一句话：输入形态 / 站内形态 / 易错点 */
    codeRule: string;
    tips: string[];
    fieldsZh: string;
    fieldsJa: string;
    fieldsCommon?: string;
  }
> = {
  airav_io: {
    blurb: "偏中文元数据；镜像域名会自动跟随。",
    codeRule: "前缀-数字，至少 3 位（SONE-1→SONE-001）；按标准化番号搜索",
    tips: [
      "代理直连即可，正式刮削不强制过盾",
      "搜索 kw→hid，勿用旧 /video/CODE",
      "详情女優为 /actor?id=；廠商 /tag?fid=",
    ],
    fieldsZh: "标题 · 简介 · 标签 · 女优名",
    fieldsJa: "厂牌名（若有）",
    fieldsCommon: "封面",
  },
  airav: {
    blurb: "入口 airav.wiki；实站常落到 airav.io，与 airav_io 同源不同入口。",
    codeRule: "前缀-数字，至少 3 位；优先 io 搜索，wiki /video/{CODE} 回退",
    tips: [
      "代理直连即可，正式刮削不强制过盾",
      "优先复用 airav.io 搜索 kw→hid；wiki /video/{CODE} 作回退",
      "解析同 airav.io（女優 /actor?id=、標籤 /tag?tid=、廠商 /tag?fid=）",
      "过滤导航垃圾（女優一覽、720p、HD 等）",
    ],
    fieldsZh: "标题 · 简介 · 女优名 · 标签",
    fieldsJa: "厂牌名（若有）",
    fieldsCommon: "封面",
  },
  avbase: {
    blurb: "日文综合库（FANZA/MGS 聚合）；不作中文标题源。",
    codeRule: "前缀-数字，至少 3 位；详情 ID 形如 honnaka:HMN-001",
    tips: [
      "代理直连即可，正式刮削不强制过盾",
      "走 Next.js __NEXT_DATA__",
      "详情 ID 形如 honnaka:HMN-001",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 标签 · 系列 · 制片 · 女优名",
    fieldsCommon: "封面 · 竖封面 · 剧照",
  },
  avmoo: {
    blurb: "有码目录镜像；标签中文，标题/女优/制片多为日文。",
    codeRule: "前缀-数字，至少 3 位（SONE-001）；路径 /cn/movies/",
    tips: [
      "不是 CF 挑战过盾：Quasar SPA，需 FlareSolverr 浏览器渲染 JS",
      "代理/curl 只有空壳（~1.5KB）；正式刮削短 wait + session 复用",
      "入口常跳 tellme.pw → 自动跟镜像（如 avmoo.shop）",
      "新站路径 /cn/movies/",
      "验收 08-15：PASS；冷启动约 30–40s，热 session 第二遍约快 25%（仍非秒级）",
    ],
    fieldsZh: "标签（类别）",
    fieldsJa: "标题 · 女优名 · 系列 · 制片 · 发行商",
    fieldsCommon: "封面 · 剧照 · 时长 · 日期",
  },
  avsox: {
    blurb: "无码目录镜像（与 Avmoo 同系）；标签中文，其余多为日文。",
    codeRule: "无码号如 010115-001（连字符）；与 avmoo 同系标准化",
    tips: [
      "与 avmoo 相同：SPA 渲染，非 CF 过盾；需 FlareSolverr",
      "当前入口 avsox.click",
      "有码区一般不作首选",
      "验收 08-15：PASS（010115-001）；约 37s；代理仅 SPA 空壳",
    ],
    fieldsZh: "标签（类别）",
    fieldsJa: "标题 · 女优名 · 制片",
    fieldsCommon: "封面 · 时长 · 日期",
  },
  carib: {
    blurb: "Caribbeancom 官方无码；全日文（页面 EUC-JP）。",
    codeRule: "必须 MMDDYY-XXX 连字符（010115-001）；下划线会 404",
    tips: [
      "官方日文站，无中文元数据",
      "代理直连即可，一般不必过盾",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 女优名 · 系列 · 标签 · 制片（固定カリビアンコム）",
    fieldsCommon: "封面 · 剧照 · 时长",
  },
  dmm: {
    blurb: "DMM/FANZA 官方；全日文。详情强制日本 IP，非日节点基本刮不到标题。",
    codeRule: "前缀-数字，至少 3 位；CID 由番号猜测（需日本节点）",
    tips: [
      "详情页已迁 video.dmm.co.jp，需 age_check_done Cookie",
      "非日本出口会「地域限制」或跳 accounts 登录域——元数据 FAIL，勿当主源",
      "代理须挂日本节点；普通国际代理不够",
      "受限时改用 LibreDMM 补日文字段；封面 CDN 有时仍可下",
      "禁止把 accounts.dmm.co.jp 当镜像落地",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 标签 · 系列 · 制片 · 女优名（必须日本节点）",
    fieldsCommon: "封面 · 竖封面（CDN，偶不受限）",
  },
  fc2: {
    blurb: "FC2 官方内容站；标题/简介/标签多为日文。",
    codeRule: "FC2-PPV-{数字}（或可解析出的纯数字）→ /article/{id}/",
    tips: [
      "卖家名作 studio/makers（非女优）",
      "下架页「お探しの商品」会空返回",
      "偶遇边缘封锁时可配 FlareSolverr",
    ],
    fieldsZh: "无（偶有中文卖家文案，勿依赖）",
    fieldsJa: "标题 · 简介 · 标签 · 卖家名（studio） · 发售日",
    fieldsCommon: "封面",
  },
  fc2_hub: {
    blurb: "原 FC2hub→javten；聚合站，字段偏日文。默认关闭。",
    codeRule: "FC2-PPV-{数字}；搜索 /en/search?kw= → /en/video/.../id{番号}/",
    tips: [
      "打开 javten.com 过 CF 后常自动跳 /en（或 /cn）",
      "出口易 Edge IP Restricted；需可过盾代理 + FlareSolverr",
      "日常优先官方 fc2，本源作补充",
      "验收 08-15：FAIL；本机/代理 403，Flare 对 javten 常 500/断连（浏览器可开≠刮削可过）",
    ],
    fieldsZh: "标题（部分条目可能中文）",
    fieldsJa: "标题 · 简介 · 标签 · 卖家/导演 · 发售日 · 时长（JSON-LD）",
    fieldsCommon: "封面 · 预览图（gallery）",
  },
  fd2ppv: {
    blurb: "FC2 社区目录（fd2ppv.cc）；标题常日文，女优/标签可补官方空白。",
    codeRule: "FC2-PPV-{数字}；路径 /articles/{数字id}",
    tips: [
      "需 FlareSolverr（文章页代理常 403；首页代理也可能是挑战页）",
      "女优名来自社区关联，可能不准",
      "建议垫后：官方 fc2 优先，本源补 actors/tags",
      "验收 08-15：PASS（FC2-PPV-4961415）；约 90s；deadline 建议 ≥120s",
    ],
    fieldsZh: "无（偶有用户中文编辑，勿依赖）",
    fieldsJa: "标题 · 标签 · 女优名 · 卖家 · 发售日 · 时长",
    fieldsCommon: "封面 · 预览图",
  },
  freejavbt: {
    blurb: "详情页字段全；/zh/ 类别偏中文，标题多为日文。不要用本源封面。",
    codeRule: "前缀-数字；FC2 用完整 FC2-PPV-…（裸数字会跳错号）",
    tips: [
      "优先 /zh/{番号}（番号·日期·时长·导演·系列·类别·女优）",
      "标题常日文 +「免费AV在线看」后缀，已剥离",
      "女优列表常混入男优/监督名，勿单押",
      "类别：zh=中文标签，ja=日文ジャンル",
      "封面不可靠：og 常是播放器截帧，jdbstatic 多为推荐位串号 → 禁止作封面源，封面交给 javbus/jav321 等",
    ],
    fieldsZh: "类别/标签（/zh/）",
    fieldsJa: "标题 · 导演 · 系列 · 女优名（常混男优）",
    fieldsCommon: "发售日 · 时长 · 番号（不要封面）",
  },
  jav321: {
    blurb: "简介常比其它站完整；标题/女优/ジャンル 多为日文。",
    codeRule: "前缀-数字，至少 3 位；POST sn=番号 → /video/{cid}",
    tips: [
      "POST /search sn=番号 → /video/{cid}；无 og 标签，靠 panel 解析",
      "界面有简/繁/英标签，正文几乎不译，勿当中文标题源",
      "新作常缺女优/片商/系列链接（仅有番号·日期·时长·评分·简介）",
      "封面取 DMM pl；竖图 ps；预览 jp-N",
    ],
    fieldsZh: "无（仅 UI 标签可切简繁）",
    fieldsJa: "标题 · 简介 · 女优 · 片商 · 系列 · ジャンル（条目齐全时）",
    fieldsCommon: "封面 · 竖封面 · 预览图 · 发售日 · 时长 · 评分",
  },
  javbus: {
    blurb: "综合快源；默认繁中 UI，标题仍日文，标签偏繁体中文。",
    codeRule: "前缀-数字，至少 3 位；路径 /{番号小写}",
    tips: [
      "路径 /{番号小写}；主站挂了可试镜像 seejav.me",
      "年龄 Cookie：existmag=all; age=verified",
      "无简介；类别在 info 区 span.genre（已排除顶栏高清/字幕）",
      "标题前缀番号已剥离；女优名/制片/系列多为日文",
      "封面为本站 /pics/cover/*，非 DMM CDN",
    ],
    fieldsZh: "标签/类别（繁体）· UI 字段名（發行日期/長度等）",
    fieldsJa: "标题 · 女优名 · 制片 · 系列 · 导演 · 发行商（常英文品牌）",
    fieldsCommon: "封面 · 预览图 · 发售日 · 时长",
  },
  javdb: {
    blurb: "条目较全但强依赖过盾；locale=zh 时标签偏中文，片名常日文。",
    codeRule: "前缀-数字，至少 3 位；搜索 q=标准化番号",
    tips: [
      "搜索 /search?q=&f=all&locale=zh → /v/{id}；强制 FlareSolverr",
      "Cookie：over18=1; locale=zh",
      "出口易被站方封 IP（提示「禁止了你的訪問」3–7 日），需换节点",
      "评分站点多为 5 分制，已×2 映射到 0–10",
      "女优优先 strong.female；失败率高时可关掉本源",
      "验收 08-15：本轮跳过（未测）",
    ],
    fieldsZh: "标签/类别（locale=zh）· UI 字段名",
    fieldsJa: "标题 · 女优名 · 片商 · 系列 · 导演（常日文）",
    fieldsCommon: "封面 · 预览图 · 发售日 · 时长 · 评分",
  },
  javlibrary: {
    blurb: "老牌目录（/cn 简体 UI）；类别偏中文，标题/女优多为日文。",
    codeRule: "前缀-数字，至少 3 位；vl_searchbyid.php 搜标准化番号",
    tips: [
      "搜索 vl_searchbyid.php → 详情已改为 /cn/jav*.html（旧 /?v= 失效）",
      "需 FlareSolverr；过盾偏慢（约 50–60s 常见），勿当失败",
      "同番号优先非蓝光条目；评分约 0–10；封面多为 DMM mono pl",
      "无简介",
      "验收 08-15：PASS（SONE-001）；约 54s；直连/代理探测失败但正式刮削可用",
    ],
    fieldsZh: "类别/标签（简体）· UI 字段名",
    fieldsJa: "标题 · 女优名 · 导演",
    fieldsCommon: "封面 · 发售日 · 时长 · 评分 · 制片/发行商（常英文品牌）",
  },
  libredmm: {
    blurb: "LibreFanza（libredmm.com）；聚合 DMM/MGS 官方 JSON，全日文。",
    codeRule: "前缀-数字，至少 3 位；/movies/{CODE}.json",
    tips: [
      "主路径 /movies/{CODE}.json；冷门可能先 processing 再出数",
      "直连代理即可，一般无需 Flare",
      "封面优先 DMM pl 大图（源常给 ps 竖缩略）",
      "可作 mgstage/dmm 被拦时的补充；剧照 sample_image_urls",
      "无时长字段时常见；评分 review 0–10",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 女优名 · 片商 · 发行 · 导演 · 标签 · 发售日 · 评分",
    fieldsCommon: "封面 · 剧照 · productId",
  },
  madou: {
    blurb: "国产目录站（麻豆社）；标题/标签中文，无日文字段。",
    codeRule: "保留前导零（MD-0362）；搜索宜无横杠 MD0362，带横杠常 0 命中",
    tips: [
      "详情为 /{slug}.html；分类作片商（如麻豆传媒）",
      "标签混女优名与类别，已启发式拆分（可能不准）",
      "无简介/时长/发售日；封面取 /covers/ 全图",
      "直连多可过，遇盾再走 Flare",
    ],
    fieldsZh: "标题 · 女优名（启发式）· 标签 · 片商（分类）",
    fieldsJa: "无",
    fieldsCommon: "封面",
  },
  madouqu: {
    blurb: "国产目录（麻豆区）；标题/女郎中文。代理直连即可。",
    codeRule: "保留前导零；搜索优先带横杠 MD-0362（无连字符易错号）",
    tips: [
      "详情 /video/{番号小写}/",
      "描述含「麻豆女郎」名单；标签多为女优名",
      "一般无 CF：代理直连；勿再强制 Flare（慢且详情常缺封面）",
      "有发售日与封面；类别/简介常无",
      "验收 08-15：代理直连；MD-013 元数据 OK、封面页结构常缺；入口 stdCode 已保留前导零",
    ],
    fieldsZh: "标题 · 女优名 · 片商（分类）",
    fieldsJa: "无",
    fieldsCommon: "封面 · 发售日",
  },
  xiao_huang_shu: {
    blurb: "小黄书 xchina.co；国产/中文 AV 向，字段中文。代理直连即可。",
    codeRule: "保留前导零；站内标签常无横杠 MD0362；须精确标签（MDSR* 不算 MD-001）",
    tips: [
      "搜索 /search.html?keyword= → 详情 /video/id-{hex}.html",
      "一般无 CF：代理直连；勿再强制 Flare",
      "勿把搜索页「站内搜索」当标题",
      "片商取自面包屑/系列（如麻豆传媒）；女优常缺",
      "有发售日、时长、封面；简介多为站介绍勿用",
      "验收 08-15：代理无 CF；HMN-895 ~4.5s PASS；入口 stdCode 已保留前导零",
    ],
    fieldsZh: "标题 · 片商 · 女优名（若有）",
    fieldsJa: "无",
    fieldsCommon: "封面 · 发售日 · 时长",
  },
  mgstage: {
    blurb: "MGS 官方（素人系番号 SIRO / 200GANA / 300MIUM 等）；全日文。",
    codeRule: "素人完整号（SIRO-xxxx / 200GANA-xxx 等）；直达 product_detail/{CODE}",
    tips: [
      "直达 /product/product_detail/{CODE}/；需年龄门 Cookie adc=1",
      "强制 FlareSolverr；过盾须带 domain=.mgstage.com",
      "默认关闭（出口不稳时易卡年龄门）",
      "女优常为素人化名+年龄；标签/片商/系列日文",
      "已取消 LibreDMM 回落：失败即本源失败，勿与独立源 LibreDMM 混淆",
      "「重测/探测」打官网首页过盾（上限~22s）；正式刮削只打 mgstage.com",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 女优名 · 片商 · 系列 · 标签 · 发售日 · 时长 · 评分",
    fieldsCommon: "封面",
  },
  miss_av: {
    blurb: "MissAV 在线站；中文 UI，片名常机翻，详情「标题」多为日文原名。",
    codeRule: "前缀-数字，至少 3 位；路径 /cn/{番号小写}",
    tips: [
      "优先 /cn/{番号小写}；落地带 /dmNNN/ 前缀",
      "强制 FlareSolverr（直连多被 CF 拦）；代理首页有时像「有正文」但不代表可免过盾",
      "女优链接形如「中文 (日文)」；发行商/标签/系列可补",
      "封面 fourhoi.com/{slug}/cover-n.jpg；质量参差，宜作补充源",
      "勿把搜索页「搜尋結果」当详情",
      "验收 08-15：元数据 PASS（SONE-001）约 78s；本轮封面失败（meta_ok_cover_fail）",
    ],
    fieldsZh: "标题（机翻）· 女优名（部分）· 类型 · 简介（机翻）",
    fieldsJa: "标题（详情「标题」字段）· 系列 · 导演",
    fieldsCommon: "封面 · 发售日 · 发行商/标签",
  },
  sevenmmtv: {
    blurb: "7MMTV；中文标题为主，可作中文标题补充。",
    codeRule: "前缀-数字，至少 3 位；搜索 /zh/searchall_search/all/{CODE}/",
    tips: [
      "代理直连即可，正式刮削不强制过盾",
      "搜索走 /zh/searchall_search/all/{CODE}/1.html；必要时 POST 表单",
      "详情优先 censored_content，chinese/破解版次之",
      "女优/片商/发行/导演/时长/发售日可补；封面为站内 webp",
    ],
    fieldsZh: "标题 · 女优名 · 类型（部分）",
    fieldsJa: "片商名（制作商，偶有日文）· 导演",
    fieldsCommon: "封面 · 发售日 · 时长 · 发行商",
  },
  iqqtv: {
    blurb: "iQQTV 中文站；不过盾拿中文标题，适合作 titleZh 快源。",
    codeRule: "前缀-数字，至少 3 位；/cn/search.php?kw=番号",
    tips: [
      "默认镜像 https://iqq5.xyz/cn（域名常换，可在源地址改）",
      "搜索 /cn/search.php?kw=番号 → player.php 详情",
      "跳过「克破/无码破解」壳条目",
      "一般无需 FlareSolverr；被拦时再换镜像或代理",
    ],
    fieldsZh: "标题 · 简介 · 女优 · 标签 · 片商 · 系列",
    fieldsJa: "无",
    fieldsCommon: "封面 · 发售日",
  },
  theporndb: {
    blurb: "ThePornDB REST API；英文元数据，欧美区主用，亦有 /jav 番号库。",
    codeRule: "JAV 用前缀-数字走 /jav?q=；欧美用标题/slug 走 /scenes|/movies",
    tips: [
      "必须配置环境变量 THEPORNDB_API_KEY（Bearer Token）",
      "Token：theporndb.net → User → API Tokens（read 权限即可）",
      "番号样走 /jav?q=；欧美标题走 /scenes 或 /movies",
      "默认关闭；无 Key 时探测为 unknown、刮削空返回",
      "字段全英文；不作中日文标题源",
    ],
    fieldsZh: "无",
    fieldsJa: "无（JAV 条目标题偶有日文罗马字/英文）",
    fieldsCommon: "英文标题 · 女优 · 简介 · 片商(site) · 发售日 · 时长 · 封面 · 评分",
  },
};

function sourceNoteOf(id: string) {
  const base = SOURCE_NOTES[id] || {
    blurb: "通用网络刮削源，可按连通情况调整地址与开关。",
    codeRule: "前缀-数字，至少 3 位（SONE-1→SONE-001）；特殊站见各源备忘",
    tips: ["地址变更后点保存再重测", "字段语种以实际页面为准"],
    fieldsZh: "视站点而定",
    fieldsJa: "视站点而定",
    fieldsCommon: "按「路径优先级」配置",
  };
  const groups = formatSourceFieldGroups(id);
  return {
    ...base,
    // 字段能力以结构化登记为准（与刮削引擎同源）
    fieldsZh: groups.fieldsZh,
    fieldsJa: groups.fieldsJa,
    fieldsCommon: groups.fieldsCommon,
  };
}

function statusLabelOf(s: ScrapeSourceCard): string {
  if (s.status === "ok") return "连通正常";
  if (s.status === "error")
    return friendlySourceError(s.lastError) || "探测异常";
  return "尚未测试";
}

type MainPane = "sources" | "fields";
type ParamPane = "priority" | "retry";

function moveItem(list: string[], index: number, dir: -1 | 1): string[] {
  const j = index + dir;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  const tmp = next[index]!;
  next[index] = next[j]!;
  next[j] = tmp;
  return next;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "尚未测试";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "尚未测试";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return "刚刚";
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

/** 探测错误短文案（WinError 等） */
function friendlySourceError(raw: string | null | undefined): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (/10054|ECONNRESET|ConnectionReset|强迫关闭|forcibly closed/i.test(s)) {
    return "连接被重置";
  }
  if (/10061|ECONNREFUSED|连接被拒绝/i.test(s)) return "无法连接";
  if (/timed?\s*out|探测超时|Timeout/i.test(s)) return "探测超时";
  return s;
}

function PriorityChips({
  order,
  nameOf,
  addable,
  onChange,
}: {
  order: string[];
  nameOf: (id: string) => string;
  addable: Array<{ id: string; name: string }>;
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="scrape-prio-chips">
      <div className="scrape-prio-chips__list">
        {order.length === 0 ? (
          <span className="mute scrape-prio-chips__empty">暂无源</span>
        ) : (
          order.map((id, idx) => (
            <span key={id} className="scrape-prio-chip">
              <button
                type="button"
                className="scrape-prio-chip__btn"
                disabled={idx === 0}
                aria-label="前移"
                onClick={() => onChange(moveItem(order, idx, -1))}
              >
                ‹
              </button>
              <span className="scrape-prio-chip__name">{nameOf(id)}</span>
              <button
                type="button"
                className="scrape-prio-chip__btn"
                disabled={idx === order.length - 1}
                aria-label="后移"
                onClick={() => onChange(moveItem(order, idx, 1))}
              >
                ›
              </button>
              <button
                type="button"
                className="scrape-prio-chip__x"
                aria-label="移除"
                onClick={() => onChange(order.filter((x) => x !== id))}
              >
                ×
              </button>
            </span>
          ))
        )}
      </div>
      {addable.length ? (
        <label className="scrape-prio-add">
          <span className="scrape-prio-add__plus" aria-hidden>
            +
          </span>
          <select
            className="scrape-prio-add__select"
            value=""
            aria-label="添加源"
            onChange={(e) => {
              const v = e.target.value;
              if (v) onChange([...order, v]);
            }}
          >
            <option value="">添加源</option>
            {addable.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}

export function ScrapeSourcesTab({
  cfg,
  origin,
  libraryRoot,
  flareSolverrUrl,
  proxyUrl,
  kindProfiles,
  sources,
  retryDefault,
  onApplied,
    toast,
}: {
  cfg: ScrapeConfig | null;
  origin: string;
  libraryRoot: string;
  flareSolverrUrl: string;
  proxyUrl: string;
  kindProfiles: Record<string, ScrapeRegionProfile>;
  sources: ScrapeSourceCard[];
  retryDefault: number;
  onApplied: (next: ScrapeConfig) => void;
  toast: (msg: string, tone?: "success" | "error" | "info") => void;
}) {
  const [mainPane, setMainPane] = useState<MainPane>("sources");
  const [paramPane, setParamPane] = useState<ParamPane>("priority");
  const [selectedKind, setSelectedKind] = useState(KIND_ROWS[0]!.id);
  const [testing, setTesting] = useState(false);
  const [testingOne, setTestingOne] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editUrl, setEditUrl] = useState("");
  const [localKinds, setLocalKinds] = useState(kindProfiles);
  const [localRetry, setLocalRetry] = useState(retryDefault);
  const autoProbeRef = useRef(false);
  const localKindsRef = useRef(kindProfiles);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalKinds(kindProfiles);
    localKindsRef.current = kindProfiles;
    setLocalRetry(retryDefault);
  }, [kindProfiles, retryDefault]);

  useEffect(() => {
    localKindsRef.current = localKinds;
  }, [localKinds]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  const nameOf = (id: string) =>
    sources.find((s) => s.id === id)?.name || id;

  const latestCheck = useMemo(() => {
    let best: string | null = null;
    for (const s of sources) {
      const t = s.lastCheckedAt;
      if (!t) continue;
      if (!best || Date.parse(t) > Date.parse(best)) best = t;
    }
    return best;
  }, [sources]);

  async function runProbeAll(opts?: { quiet?: boolean }) {
    setTesting(true);
    try {
      const r = await testScrapeSources();
      onApplied(r.data);
      if (!opts?.quiet) {
        toast(r.message || "测试完成", "success");
      }
    } catch (e) {
      if (!opts?.quiet) {
        toast(e instanceof Error ? e.message : "测试失败", "error");
      }
    } finally {
      setTesting(false);
    }
  }

  // 进入页时：未探测过的源自动测一次，联通即绿点
  useEffect(() => {
    if (autoProbeRef.current || testing || !sources.length) return;
    const need = sources.some(
      (s) =>
        s.enabled &&
        (s.status === "unknown" || !s.lastCheckedAt) &&
        s.id !== "forum",
    );
    if (!need) return;
    autoProbeRef.current = true;
    void runProbeAll({ quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅首屏自动探测
  }, [sources]);

  async function onTestAll() {
    await runProbeAll();
  }

  async function onTestOne() {
    if (!editId) return;
    setTestingOne(true);
    try {
      const savedUrl = String(editSource?.baseUrl || "").trim();
      if (editUrl.trim() !== savedUrl) {
        const data = await patchScrapeSource(editId, {
          baseUrl: editUrl.trim(),
        });
        onApplied(data);
      }
      const r = await testScrapeSources([editId]);
      onApplied(r.data);
      toast(r.message || "重测完成", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "重测失败", "error");
    } finally {
      setTestingOne(false);
    }
  }

  async function onToggle(s: ScrapeSourceCard, next: boolean) {
    if (s.id === "forum") return;
    try {
      const data = await patchScrapeSource(s.id, { enabled: next });
      onApplied(data);
    } catch (e) {
      toast(e instanceof Error ? e.message : "更新失败", "error");
    }
  }

  async function onSaveUrl() {
    if (!editId) return;
    try {
      const data = await patchScrapeSource(editId, { baseUrl: editUrl.trim() });
      onApplied(data);
      setEditId(null);
      toast("已更新 URL", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "保存失败", "error");
    }
  }

  function setKindField(
    kind: string,
    field: keyof ScrapeFieldPriority,
    order: string[],
  ) {
    setLocalKinds((prev) => {
      const cur = prev[kind] || {
        libraryRoot: "",
        writeTree: null,
        writeEmby: null,
        metaSources: [],
        coverSources: [],
      };
      const fp = { ...fieldPriorityFromProfile(cur), [field]: order };
      const derived = deriveSourcesFromFields(fp);
      const next = {
        ...prev,
        [kind]: {
          ...cur,
          fieldPriority: fp,
          metaSources: derived.metaSources,
          coverSources: derived.coverSources,
        },
      };
      localKindsRef.current = next;
      schedulePersistParams(next);
      return next;
    });
  }

  function buildNormalizedKinds(
    kinds: Record<string, ScrapeRegionProfile>,
  ): Record<string, ScrapeRegionProfile> {
    const normalizedKinds: Record<string, ScrapeRegionProfile> = {};
    for (const row of KIND_ROWS) {
      const cur = kinds[row.id];
      const fp = fieldPriorityFromProfile(cur);
      const derived = deriveSourcesFromFields(fp);
      normalizedKinds[row.id] = {
        libraryRoot: cur?.libraryRoot || "",
        writeTree: cur?.writeTree ?? null,
        writeEmby: cur?.writeEmby ?? null,
        fieldPriority: fp,
        metaSources: derived.metaSources,
        coverSources: derived.coverSources,
      };
    }
    return normalizedKinds;
  }

  async function persistParams(
    kinds: Record<string, ScrapeRegionProfile>,
    opts?: { quiet?: boolean },
  ) {
    const lib = libraryRoot.trim();
    const normalizedKinds = buildNormalizedKinds(kinds);
    const next = await putScrape({
      enabled: true,
      origin: origin.trim() || "http://127.0.0.1:9210",
      ...(lib ? { libraryRoot: lib } : {}),
      flareSolverrUrl: flareSolverrUrl.trim(),
      proxyUrl: proxyUrl.trim(),
      coverDownloadStrategy:
        cfg?.coverDownloadStrategy === "size" ? "size" : "priority",
      exportFastConcurrency: cfg?.exportFastConcurrency,
      exportSlowConcurrency: cfg?.exportSlowConcurrency,
      exportConcurrency: cfg?.exportConcurrency,
      posterCrop: cfg?.posterCrop,
      metadataOptimize: cfg?.metadataOptimize,
      kindProfiles: normalizedKinds,
      regionProfiles: normalizedKinds,
      fieldPriority: fieldPriorityFromProfile(
        normalizedKinds.japan_censored,
      ),
      retry: { defaultRetry: localRetry },
      sources,
    });
    onApplied(next);
    if (!opts?.quiet) toast("参数配置已保存", "success");
  }

  function schedulePersistParams(kinds: Record<string, ScrapeRegionProfile>) {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      void (async () => {
        setSaving(true);
        try {
          await persistParams(kinds, { quiet: true });
          toast("字段优先级已自动保存", "success");
        } catch (e) {
          toast(e instanceof Error ? e.message : "自动保存失败", "error");
        } finally {
          setSaving(false);
        }
      })();
    }, 480);
  }

  async function onSaveParams() {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    setSaving(true);
    try {
      await persistParams(localKindsRef.current);
    } catch (e) {
      toast(e instanceof Error ? e.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  }

  const enabledSources = sources.filter(
    (s) => s.enabled && s.id !== "forum",
  );
  const visibleSources = sources.filter((s) => s.id !== "forum");
  const sourcesByAccess = useMemo(() => {
    type MetaBuckets = Record<SourceMetaLang, ScrapeSourceCard[]>;
    type RegionBuckets = Record<SourceRegion, MetaBuckets>;
    const emptyMeta = (): MetaBuckets => ({ zh: [], native: [] });
    const emptyRegion = (): RegionBuckets => ({
      japan: emptyMeta(),
      china: emptyMeta(),
      western: emptyMeta(),
    });
    const buckets: Record<SourceAccess, RegionBuckets> = {
      direct: emptyRegion(),
      proxy: emptyRegion(),
      proxy_flare: emptyRegion(),
    };
    for (const s of sources) {
      if (s.id === "forum") continue;
      buckets[resolveAccess(s)][resolveRegion(s)][resolveMetaLang(s)].push(s);
    }
    return buckets;
  }, [sources]);
  const editSource = visibleSources.find((s) => s.id === editId) || null;
  const selectedProfile = localKinds[selectedKind];
  const selectedFields = fieldPriorityFromProfile(selectedProfile);

  function renderSourceCard(s: (typeof visibleSources)[number]) {
    const st =
      s.status === "ok"
        ? "ok"
        : s.status === "error"
          ? "error"
          : "unknown";
    return (
      <div key={s.id} className="scrape-src-card">
        <div className="scrape-src-card__row">
          <div className="scrape-src-card__headline">
            <button
              type="button"
              className="scrape-src-card__top"
              onClick={() => {
                setEditId(s.id);
                setEditUrl(s.baseUrl || "");
              }}
            >
              <span
                className={`scrape-src-dot scrape-src-dot--${st}`}
                aria-hidden
              />
              <span className="scrape-src-card__name">{s.name}</span>
            </button>
            <label
              className="scrape-src-card__switch"
              onClick={(e) => e.stopPropagation()}
            >
              <input
                type="checkbox"
                checked={Boolean(s.enabled)}
                disabled={s.id === "forum"}
                onChange={(e) => void onToggle(s, e.target.checked)}
                aria-label={`启用 ${s.name}`}
              />
            </label>
          </div>
          <div className="scrape-src-card__main">
            {s.baseUrl ? (
              <a
                className="scrape-src-card__url allow-select"
                href={s.baseUrl}
                target="_blank"
                rel="noopener noreferrer"
                title={`打开 ${s.baseUrl}`}
              >
                {s.baseUrl}
              </a>
            ) : (
              <span className="scrape-src-card__url mute">
                （论坛封面 / 无 URL）
              </span>
            )}
            {(s.cooldownRemainingSec || 0) > 0 ||
            (s.status === "error" && s.lastError) ? (
              <span className="scrape-src-card__meta">
                {(s.cooldownRemainingSec || 0) > 0 ? (
                  <span className="scrape-src-card__cd">
                    CD: {s.cooldownRemainingSec}s
                  </span>
                ) : null}
                {s.status === "error" && s.lastError ? (
                  <span className="scrape-src-card__err">
                    {friendlySourceError(s.lastError)}
                  </span>
                ) : null}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
    <div className="scrape-sources">
      <div className="scrape-src-main-tabs" role="tablist" aria-label="数据源页">
        {(
          [
            ["sources", "数据源管理"],
            ["fields", "字段优先级"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={mainPane === k}
            className={
              mainPane === k
                ? "scrape-src-main-tabs__btn scrape-src-main-tabs__btn--active"
                : "scrape-src-main-tabs__btn"
            }
            onClick={() => setMainPane(k)}
          >
            {label}
          </button>
        ))}
      </div>

      {mainPane === "sources" ? (
        <>
      <div className="scrape-src-head">
        <div className="scrape-src-head__left">
          <p className="scrape-src-head__title">连通状态</p>
          <p className="scrape-src-head__sub mute">
            {relativeTime(latestCheck)}
            {cfg?.sourcesLastAutoTestAt
              ? ` · 自动 ${relativeTime(cfg.sourcesLastAutoTestAt)}`
              : " · 每日自动测"}
          </p>
        </div>
        <button
          type="button"
          className="scrape-src-head__test"
          disabled={testing || !cfg}
          onClick={() => void onTestAll()}
        >
          <RefreshCw size={14} strokeWidth={2.2} />
          {testing ? "测试中" : "测试全部"}
        </button>
      </div>

      <div className="scrape-src-sections">
        {ACCESS_SECTIONS.map((sec) => {
          const byRegion = sourcesByAccess[sec.id];
          const rows = REGION_SECTIONS.flatMap((region) =>
            META_LANG_ORDER.flatMap((meta) => byRegion[region.id][meta]),
          );
          if (!rows.length) return null;
          const okN = rows.filter((s) => s.status === "ok").length;
          const errN = rows.filter((s) => s.status === "error").length;
          return (
            <section key={sec.id} className="scrape-src-section">
              <div className="scrape-src-section__head">
                <div className="scrape-src-section__titles">
                  <h3 className="scrape-src-section__title">
                    <span className="scrape-src-section__level mute">链接</span>
                    {sec.title}
                  </h3>
                  <p className="scrape-src-section__hint mute">{sec.hint}</p>
                </div>
                <span
                  className={
                    errN
                      ? "scrape-src-section__stat scrape-src-section__stat--warn"
                      : "scrape-src-section__stat"
                  }
                >
                  {okN}/{rows.length}
                </span>
              </div>
              <div className="scrape-src-section__body">
                {REGION_SECTIONS.map((region) => {
                  const byMeta = byRegion[region.id];
                  const regionRows = [...byMeta.zh, ...byMeta.native];
                  if (!regionRows.length) return null;
                  const regionOk = regionRows.filter(
                    (s) => s.status === "ok",
                  ).length;
                  return (
                    <div
                      key={`${sec.id}-${region.id}`}
                      className="scrape-src-region"
                    >
                      <div className="scrape-src-region__head">
                        <h4 className="scrape-src-region__title">
                          <span className="scrape-src-region__level mute">
                            地区
                          </span>
                          {region.title}
                        </h4>
                        <span className="scrape-src-region__stat mute">
                          {regionOk}/{regionRows.length}
                        </span>
                      </div>
                      {META_LANG_ORDER.map((meta) => {
                        const metaRows = byMeta[meta];
                        if (!metaRows.length) return null;
                        const metaOk = metaRows.filter(
                          (s) => s.status === "ok",
                        ).length;
                        return (
                          <div
                            key={`${sec.id}-${region.id}-${meta}`}
                            className="scrape-src-meta"
                          >
                            <div className="scrape-src-meta__head">
                              <h5 className="scrape-src-meta__title">
                                <span className="scrape-src-meta__level mute">
                                  元数据
                                </span>
                                {metaLangTitle(region.id, meta)}
                              </h5>
                              <span className="scrape-src-meta__stat mute">
                                {metaOk}/{metaRows.length}
                              </span>
                            </div>
                            <div className="scrape-src-grid">
                              {metaRows.map(renderSourceCard)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
        </>
      ) : null}

      {mainPane === "fields" ? (
        <>
      <div className="scrape-param-block">
        <div className="scrape-param-tabs" role="tablist">
          {(
            [
              ["priority", "路径优先级"],
              ["retry", "重试"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={paramPane === k}
              className={
                paramPane === k
                  ? "scrape-param-tabs__btn scrape-param-tabs__btn--active"
                  : "scrape-param-tabs__btn"
              }
              onClick={() => setParamPane(k)}
            >
              {label}
            </button>
          ))}
        </div>

        {paramPane === "priority" ? (
          <div className="settings-form-card settings-form-card--flush scrape-param-card">
            <p className="scrape-param-hint mute">
              改字段自动保存 · 进行中任务从下一番号起生效 · 快源靠前 · 过盾垫后
            </p>
            <div className="scrape-prio-layout">
              <div className="scrape-prio-kind-tabs" role="tablist" aria-orientation="vertical">
                {KIND_ROWS.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    role="tab"
                    aria-selected={selectedKind === row.id}
                    className={
                      selectedKind === row.id
                        ? "scrape-prio-kind-tabs__btn scrape-prio-kind-tabs__btn--active"
                        : "scrape-prio-kind-tabs__btn"
                    }
                    onClick={() => setSelectedKind(row.id)}
                  >
                    {row.label}
                  </button>
                ))}
              </div>
              <div className="scrape-prio-fields">
                {FIELD_ROWS.map((row) => {
                  const order = selectedFields[row.id] || [];
                  const used = new Set(order);
                  const addable = enabledSources
                    .filter((s) => !used.has(s.id))
                    .map((s) => ({ id: s.id, name: s.name }));
                  return (
                    <div key={row.id} className="scrape-prio-row">
                      <div className="scrape-prio-row__label">{row.label}</div>
                      <PriorityChips
                        order={order}
                        nameOf={nameOf}
                        addable={addable}
                        onChange={(next) =>
                          setKindField(selectedKind, row.id, next)
                        }
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ) : null}

        {paramPane === "retry" ? (
          <div className="settings-form-card settings-form-card--flush scrape-param-card">
            <p className="scrape-param-hint mute">默认失败重试次数</p>
            <label className="settings-inline">
              <span className="settings-inline__label">重试</span>
              <input
                className="settings-inline__input"
                type="number"
                min={0}
                max={8}
                value={localRetry}
                onChange={(e) =>
                  setLocalRetry(
                    Math.max(0, Math.min(8, Number(e.target.value) || 0)),
                  )
                }
              />
            </label>
          </div>
        ) : null}
      </div>

      <div className="settings-actions settings-actions--panel">
        <button
          type="button"
          className="btn settings-actions__primary"
          disabled={saving}
          onClick={() => void onSaveParams()}
        >
          {saving ? "保存中…" : "保存参数"}
        </button>
      </div>
        </>
      ) : null}
    </div>

    {editId && editSource && typeof document !== "undefined"
      ? createPortal(
          <AppPush
            title={editSource.name}
            onBack={() => {
              if (testingOne) return;
              setEditId(null);
            }}
          >
            <div className="scrape-src-edit">
              <section className="scrape-src-edit__hero">
                <div className="scrape-src-edit__hero-row">
                  <span
                    className={`scrape-src-dot scrape-src-dot--${
                      editSource.status === "ok"
                        ? "ok"
                        : editSource.status === "error"
                          ? "error"
                          : "unknown"
                    }`}
                    aria-hidden
                  />
                  <div className="scrape-src-edit__hero-text">
                    <p className="scrape-src-edit__id allow-select">
                      {editSource.id}
                    </p>
                    <p className="scrape-src-edit__group mute">
                      {SOURCE_GROUP_LABEL[editSource.group] ||
                        editSource.group ||
                        "未分组"}
                      {editSource.enabled ? " · 已启用" : " · 已关闭"}
                    </p>
                  </div>
                  <span
                    className={`scrape-src-edit__pill scrape-src-edit__pill--${
                      editSource.status === "ok"
                        ? "ok"
                        : editSource.status === "error"
                          ? "error"
                          : "unknown"
                    }`}
                  >
                    {statusLabelOf(editSource)}
                  </span>
                </div>
                {(editSource.cooldownRemainingSec || 0) > 0 ? (
                  <p className="scrape-src-edit__cd-line mute">
                    冷却中 {editSource.cooldownRemainingSec}s
                  </p>
                ) : null}
              </section>

              <section className="scrape-src-edit__group-card">
                <label className="scrape-src-edit__row scrape-src-edit__row--stack">
                  <span className="scrape-src-edit__lab">站点地址</span>
                  <input
                    className="scrape-src-edit__input allow-select"
                    value={editUrl}
                    onChange={(e) => setEditUrl(e.target.value)}
                    placeholder="https://"
                    data-autofocus="true"
                    autoCapitalize="off"
                    autoCorrect="off"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </label>
                <div className="scrape-src-edit__row">
                  <span className="scrape-src-edit__lab">上次探测</span>
                  <span className="scrape-src-edit__val allow-select">
                    {relativeTime(editSource.lastCheckedAt)}
                  </span>
                </div>
                {editSource.lastError && editSource.status === "error" ? (
                  <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                    <span className="scrape-src-edit__lab">最近错误</span>
                    <span className="scrape-src-edit__err allow-select">
                      {friendlySourceError(editSource.lastError)}
                    </span>
                  </div>
                ) : null}
              </section>

              {(() => {
                const note = sourceNoteOf(editSource.id);
                return (
                  <section className="scrape-src-edit__group-card">
                    <header className="scrape-src-edit__sec-head">
                      <span className="scrape-src-edit__sec-title">备忘</span>
                    </header>
                    <p className="scrape-src-edit__blurb">{note.blurb}</p>
                    <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                      <span className="scrape-src-edit__lab">番号规则</span>
                      <span className="scrape-src-edit__val">{note.codeRule}</span>
                    </div>
                    <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                      <span className="scrape-src-edit__lab">中文元数据</span>
                      <span className="scrape-src-edit__val">{note.fieldsZh}</span>
                    </div>
                    <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                      <span className="scrape-src-edit__lab">日文元数据</span>
                      <span className="scrape-src-edit__val">{note.fieldsJa}</span>
                    </div>
                    {note.fieldsCommon ? (
                      <div className="scrape-src-edit__row scrape-src-edit__row--stack">
                        <span className="scrape-src-edit__lab">共通 / 其它</span>
                        <span className="scrape-src-edit__val">
                          {note.fieldsCommon}
                        </span>
                      </div>
                    ) : null}
                    {note.tips.length ? (
                      <ul className="scrape-src-edit__tips">
                        {note.tips.map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ul>
                    ) : null}
                  </section>
                );
              })()}

              <div className="scrape-src-edit__ops">
                {editSource.baseUrl || editUrl.trim() ? (
                  <a
                    className="btn scrape-src-edit__open"
                    href={editUrl.trim() || editSource.baseUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开
                  </a>
                ) : null}
                <button
                  type="button"
                  className="btn scrape-src-edit__retest"
                  disabled={testingOne || testing}
                  onClick={() => void onTestOne()}
                >
                  <RefreshCw size={14} strokeWidth={2.2} />
                  {testingOne ? "重测中…" : "重测"}
                </button>
                <button
                  type="button"
                  className="btn settings-actions__primary scrape-src-edit__save"
                  disabled={testingOne}
                  onClick={() => void onSaveUrl()}
                >
                  保存
                </button>
              </div>
            </div>
          </AppPush>,
          document.querySelector(".settings-screen-root") || document.body,
        )
      : null}
    </>
  );
}
