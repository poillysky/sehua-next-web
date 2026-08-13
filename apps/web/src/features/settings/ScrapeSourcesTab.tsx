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
  cover: ["javbus", "freejavbt"],
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

/** 各站备忘：须写清哪些字段中文、哪些日文（封面等无语言写共通） */
const SOURCE_NOTES: Record<
  string,
  { blurb: string; tips: string[]; fieldsZh: string; fieldsJa: string; fieldsCommon?: string }
> = {
  airav_io: {
    blurb: "偏中文元数据；镜像域名会自动跟随。",
    tips: [
      "易遇 Cloudflare，需 FlareSolverr",
      "搜索 kw→hid，勿用旧 /video/CODE",
      "详情女優为 /actor?id=；廠商 /tag?fid=",
    ],
    fieldsZh: "标题 · 简介 · 标签 · 女优名",
    fieldsJa: "厂牌名（若有）",
    fieldsCommon: "封面",
  },
  airav: {
    blurb: "入口 airav.wiki；实站 302→airav.io（/video?jid=番号），与 airav_io 同源不同入口。",
    tips: [
      "强制 FlareSolverr",
      "解析复用 airav.io 详情（女優 /actor?id=、標籤 /tag?tid=、廠商 /tag?fid=）",
      "过滤导航垃圾（女優一覽、720p、HD 等）",
    ],
    fieldsZh: "标题 · 简介 · 女优名 · 标签",
    fieldsJa: "厂牌名（若有，多为日文）",
    fieldsCommon: "封面",
  },
  avbase: {
    blurb: "日文综合库（FANZA/MGS 聚合）；不作中文标题源。",
    tips: [
      "Cloudflare 过盾，需 FlareSolverr",
      "走 Next.js __NEXT_DATA__",
      "详情 ID 形如 honnaka:HMN-001",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 标签 · 系列 · 制片 · 女优名",
    fieldsCommon: "封面 · 竖封面 · 剧照",
  },
  avmoo: {
    blurb: "有码目录镜像；标签中文，标题/女优/制片多为日文。",
    tips: [
      "入口常跳 tellme.pw → 自动跟镜像（如 avmoo.shop）",
      "新站 /cn/movies/，需 FlareSolverr + 等待渲染",
    ],
    fieldsZh: "标签（类别）",
    fieldsJa: "标题 · 女优名 · 系列 · 制片 · 发行商",
    fieldsCommon: "封面 · 剧照 · 时长 · 日期",
  },
  avsox: {
    blurb: "无码目录镜像（与 Avmoo 同系）；标签中文，其余多为日文。",
    tips: [
      "当前入口 avsox.click",
      "需 FlareSolverr；详情 SPA 需等待",
      "有码区一般不作首选",
    ],
    fieldsZh: "标签（类别）",
    fieldsJa: "标题 · 女优名 · 制片",
    fieldsCommon: "封面 · 时长 · 日期",
  },
  carib: {
    blurb: "Caribbeancom 官方无码；全日文（页面 EUC-JP）。",
    tips: [
      "番号形如 010115-001（连字符）；下划线会 404",
      "官方日文站，无中文元数据",
      "代理直连即可，一般不必过盾",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 女优名 · 系列 · 标签 · 制片（固定カリビアンコム）",
    fieldsCommon: "封面 · 剧照 · 时长",
  },
  dmm: {
    blurb: "DMM/FANZA 官方；全日文。封面 CDN 常可用，详情需日本 IP。",
    tips: [
      "详情页已迁 video.dmm.co.jp，需 age_check_done Cookie",
      "非日本出口易「地域限制」——只拿得到封面/竖封面",
      "日文元数据完整时：标题/简介/标签/系列/制片/女优",
      "受限时请改日本代理，或改用 LibreDMM 作日文字段补充",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 标签 · 系列 · 制片 · 女优名（需日本节点）",
    fieldsCommon: "封面 · 竖封面（CDN，常不受限）",
  },
  fc2: {
    blurb: "FC2 官方内容站；标题/简介/标签多为日文。",
    tips: [
      "仅 FC2 / FC2-PPV 番号",
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
    tips: [
      "仅 FC2 / FC2-PPV；搜索 kw→/video/{vid}/id{number}/",
      "当前常见出口易 Cloudflare Edge IP Restricted",
      "需可过盾的出口 + FlareSolverr；无稳定镜像",
      "日常优先用官方 fc2，本源作补充",
    ],
    fieldsZh: "标题（部分条目可能中文）",
    fieldsJa: "标题 · 简介 · 标签 · 卖家/导演 · 发售日 · 时长（JSON-LD）",
    fieldsCommon: "封面 · 预览图（gallery）",
  },
  fd2ppv: {
    blurb: "FC2 社区目录（fd2ppv.cc）；标题常日文，女优/标签可补官方空白。",
    tips: [
      "仅 FC2 / FC2-PPV；路径 /articles/{数字id}",
      "需 FlareSolverr（Cloudflare）",
      "女优名来自社区关联，可能不准",
      "建议垫后：官方 fc2 优先，本源补 actors/tags",
    ],
    fieldsZh: "无（偶有用户中文编辑，勿依赖）",
    fieldsJa: "标题 · 标签 · 女优名 · 卖家 · 发售日 · 时长",
    fieldsCommon: "封面 · 预览图",
  },
  freejavbt: {
    blurb: "详情页字段全；/zh/ 类别偏中文，标题多为日文。",
    tips: [
      "优先 /zh/{番号}（番号·日期·时长·导演·系列·类别·女优）",
      "标题常日文 +「免费AV在线看」后缀，已剥离",
      "女优列表常混入男优/监督名，勿单押",
      "类别：zh=中文标签，ja=日文ジャンル",
      "FC2 用完整番号；裸数字会跳错号",
    ],
    fieldsZh: "类别/标签（/zh/）",
    fieldsJa: "标题 · 导演 · 系列 · 女优名（常混男优）",
    fieldsCommon: "封面 · 发售日 · 时长 · 番号",
  },
  jav321: {
    blurb: "简介常比其它站完整；标题/女优/ジャンル 多为日文。",
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
    tips: [
      "搜索 /search?q=&f=all&locale=zh → /v/{id}；强制 FlareSolverr",
      "Cookie：over18=1; locale=zh",
      "出口易被站方封 IP（提示「禁止了你的訪問」3–7 日），需换节点",
      "评分站点多为 5 分制，已×2 映射到 0–10",
      "女优优先 strong.female；失败率高时可关掉本源",
    ],
    fieldsZh: "标签/类别（locale=zh）· UI 字段名",
    fieldsJa: "标题 · 女优名 · 片商 · 系列 · 导演（常日文）",
    fieldsCommon: "封面 · 预览图 · 发售日 · 时长 · 评分",
  },
  javlibrary: {
    blurb: "老牌目录（/cn 简体 UI）；类别偏中文，标题/女优多为日文。",
    tips: [
      "搜索 vl_searchbyid.php → 详情已改为 /cn/jav*.html（旧 /?v= 失效）",
      "需 FlareSolverr；过盾偏慢（探测约 30–60s），勿当失败",
      "同番号优先非蓝光条目；评分约 0–10；封面多为 DMM mono pl",
      "无简介",
    ],
    fieldsZh: "类别/标签（简体）· UI 字段名",
    fieldsJa: "标题 · 女优名 · 导演",
    fieldsCommon: "封面 · 发售日 · 时长 · 评分 · 制片/发行商（常英文品牌）",
  },
  libredmm: {
    blurb: "LibreFanza（libredmm.com）；聚合 DMM/MGS 官方 JSON，全日文。",
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
    tips: [
      "搜索 ?s= 要用无连字符（MD0362）；带横杠常 0 命中",
      "勿用全局 stdCode：会吞前导零（MD-0362→MD-362）",
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
    blurb: "国产目录（麻豆区）；标题/女郎中文，强依赖过盾。",
    tips: [
      "详情 /video/{番号小写}/；搜索优先带横杠（MD-0362），无连字符易错号",
      "保留前导零（勿用全局 stdCode 吞零）",
      "描述含「麻豆女郎」名单；标签多为女优名",
      "强制 FlareSolverr；源站偶发 CF 520 会空返回",
      "有发售日与封面；类别/简介常无",
    ],
    fieldsZh: "标题 · 女优名 · 片商（分类）",
    fieldsJa: "无",
    fieldsCommon: "封面 · 发售日",
  },
  xiao_huang_shu: {
    blurb: "小黄书 xchina.co；国产/中文 AV 向，字段中文。",
    tips: [
      "搜索 /search.html?keyword= → 详情 /video/id-{hex}.html",
      "保留前导零（MD-0362）；勿用会吞零的 stdCode",
      "强制 FlareSolverr；勿把搜索页「站内搜索」当标题",
      "片商取自面包屑/系列（如麻豆传媒）；女优常缺",
      "有发售日、时长、封面；简介多为站介绍勿用",
    ],
    fieldsZh: "标题 · 片商 · 女优名（若有）",
    fieldsJa: "无",
    fieldsCommon: "封面 · 发售日 · 时长",
  },
  mgstage: {
    blurb: "MGS 官方（素人系番号 SIRO / 200GANA / 300MIUM 等）；全日文。",
    tips: [
      "直达 /product/product_detail/{CODE}/；需年龄门 Cookie adc=1",
      "强制 FlareSolverr；过盾须带 domain=.mgstage.com",
      "默认关闭（出口不稳时易卡年龄门）；可用 LibreDMM 槽位回退",
      "女优常为素人化名+年龄；标签/片商/系列日文",
    ],
    fieldsZh: "无",
    fieldsJa: "标题 · 简介 · 女优名 · 片商 · 系列 · 标签 · 发售日 · 时长 · 评分",
    fieldsCommon: "封面",
  },
  miss_av: {
    blurb: "MissAV 在线站；中文 UI，片名常机翻，详情「标题」多为日文原名。",
    tips: [
      "优先 /cn/{番号小写}；落地带 /dmNNN/ 前缀",
      "强制 FlareSolverr（直连多被 CF 拦）",
      "女优链接形如「中文 (日文)」；发行商/标签/系列可补",
      "封面 fourhoi.com/{slug}/cover-n.jpg；质量参差，宜作补充源",
      "勿把搜索页「搜尋結果」当详情",
    ],
    fieldsZh: "标题（机翻）· 女优名（部分）· 类型 · 简介（机翻）",
    fieldsJa: "标题（详情「标题」字段）· 系列 · 导演",
    fieldsCommon: "封面 · 发售日 · 发行商/标签",
  },
  sevenmmtv: {
    blurb: "7MMTV；中文标题为主，可作中文标题补充。",
    tips: [
      "搜索走 /zh/searchall_search/all/{CODE}/1.html；必要时 POST 表单",
      "详情优先 censored_content，chinese/破解版次之",
      "强制 FlareSolverr；POST 需先过盾拿 cf_clearance",
      "女优/片商/发行/导演/时长/发售日可补；封面为站内 webp",
    ],
    fieldsZh: "标题 · 女优名 · 类型（部分）",
    fieldsJa: "片商名（制作商，偶有日文）· 导演",
    fieldsCommon: "封面 · 发售日 · 时长 · 发行商",
  },
  iqqtv: {
    blurb: "iQQTV 中文站；不过盾拿中文标题，适合作 titleZh 快源。",
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
  const editSource = visibleSources.find((s) => s.id === editId) || null;
  const selectedProfile = localKinds[selectedKind];
  const selectedFields = fieldPriorityFromProfile(selectedProfile);

  return (
    <>
    <div className="scrape-sources">
      <div className="scrape-src-head">
        <div className="scrape-src-head__left">
          <p className="scrape-src-head__title">数据源管理</p>
        </div>
        <div className="scrape-src-head__ops">
          <span className="mute scrape-src-head__time">
            状态更新：{relativeTime(latestCheck)}
            {cfg?.sourcesLastAutoTestAt
              ? ` · 自动：${relativeTime(cfg.sourcesLastAutoTestAt)}`
              : " · 每天自动测（串行）"}
          </span>
          <button
            type="button"
            className="btn btn-ghost scrape-src-head__test"
            disabled={testing || !cfg}
            onClick={() => void onTestAll()}
          >
            <RefreshCw size={13} strokeWidth={2} />
            {testing ? "测试中…" : "测试全部"}
          </button>
        </div>
      </div>

      <div className="scrape-src-grid">
        {visibleSources.map((s) => {
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
        })}
      </div>

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
