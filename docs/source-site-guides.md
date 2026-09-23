# 数据源站点详解

按设置页 / `SOURCE_CATALOG` **从上往下**，对每个已实现源做「适合什么内容」的说明。  
写法约定：

1. **先看官网实际分区与检索**（本机探针：`data/debug/*_region_probe*.txt`）  
2. 再对照本仓库默认丰富链、货架、权威前缀映射  
3. 番号输入形态见 [region-code-formats.md](./region-code-formats.md)  
4. 匹配问题与修复记在 [source-region-code-audit.md](./source-region-code-audit.md)

六区：`japan_censored`（有码）· `japan_uncensored`（无码）· `japan_amateur`（素人）· `fc2` · `china`（国产）· `western`（欧美）。

| 进度 | id | 文档状态 |
|------|-----|----------|
| 1 | `javbus` | ✅ 本文已写 |
| 2 | `dmm` | ✅ 本文已写 |
| 3 | `libredmm` | ✅ 本文已写 |
| 4 | `airav_io` | ✅ 本文已写 |
| 5 | `avmoo` | ✅ 本文已写 |
| 6 | `jav321` | ✅ 本文已写 |
| 7 | `avbase` | ✅ 本文已写 |
| 8 | `mgstage` | ✅ 本文已写（实站复测） |
| 9 | `freejavbt` | ✅ 本文已写 |
| 10 | `sevenmmtv` | ✅ 本文已写 |
| 11 | `iqqtv` | ✅ 本文已写 |
| — | `avsex` | ❌ **已下线**（强制 Flare，慢源） |
| 12 | `r18dev` | ✅ 本文已写 |
| — | `avwikidb` | ❌ **已下线**（CF 挑战，须过盾） |
| — | `lulubar` | ❌ **已下线**（综合组） |
| U | 无码前缀专用站 ×12 | ✅ 批量连通+样例刮削（见 §U） |
| F | `fc2` / `fd2ppv` | ✅ 实站复测（见 §F）；fd2ppv 详情 403 |
| C | 国产 ×4 | ✅ 批量复测（见 §C）；madou/hscangku 可用 |
| W | `theporndb` / `avheat` | ✅ 实站复测（见 §W）；修 YYYY↔YY 候选 |
| `avsox` | AvSox | ⏸ 保留；空壳须 Flare（未下线） |
| 13 | `javday` | ⏸ **暂跳过**（综合） |
| 14 | `miss_av` | ✅ 本文已写（实站复测；修候选/国产防错绑） |
| 15 | `njav` | ✅ 本文已写（实站复测；FC2/板号直链） |
| 16+ | … | ⏳ |

---

## 1. JavBus（`javbus`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `javbus` |
| 显示名 | JavBus |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.javbus.com` |
| 镜像种子 | `javbus.com`、`seejav.me` 等（见 `SITE_MIRROR`） |
| 访问 | 自适应代理；**需年龄 Cookie**（默认 `existmag=all; age=verified; dv=1`） |
| 官网自称 | 「AV 磁力連結分享 · 日本成人影片資料庫」 |

实现入口：

- 列表 / 搜索 / 详情：`apps/api/app/makers/catalog_routes.py`（`_javbus_*`）  
- 丰富详情桥：`scrape_details` → `_legacy_javbus`  
- 番号候选：`javbus_code_candidates`（`scrape_details/common.py`）

### 官网实际有什么（2026-09 探针）

导航（中文站）结构清晰，**三大内容块**：

| 导航 | URL | 含义 |
|------|-----|------|
| **有碼** | `/` | 日本有码片库首页 |
| **無碼** | `/uncensored` | 日本无码片库 |
| **歐美** | `https://www.javbus.org/` | **独立域名**，不在主站路径里 |

配套页：

- 有码类别 `/genre`、有码女优 `/actresses`  
- 无码类别 `/uncensored/genre`、无码女优 `/uncensored/actresses`  
- 快捷：高清 `/genre/hd`、字幕 `/genre/sub`  
- 多语言：`/en` `/ja` `/ko` 与中文根路径  

货架探针：`/` 与 `/uncensored` 均可列出约 30 条 `movie-box`；年龄 Cookie 无效时会进验证页。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★★ 主战场 | 首页即有码库；本仓库前缀权威站之一；makers 货架 `list=/` |
| **日本无码** | ★★★★☆ 主战场之一 | `/uncensored`；权威脚本为「JavBus 无码 + Caribbeancom」；货架 `list=/uncensored` |
| 日本素人 | ★☆☆☆☆ 不适合当主源 | 站内无「素人」大区；MGStage 类番号实测详情/搜索易空 |
| FC2 | ☆☆☆☆☆ | 规范键检索无结果；应用 FC2 / MissAV 等 |
| 国产 | ☆☆☆☆☆ | 无国产分区；MDSR 等无结果 |
| 欧美 | △ 不在本站主库 | 导航指向 **javbus.org**；本仓库欧美默认链是 ThePornDB，**不要用 javbus.com 当欧美 enrich** |

**一句话**：JavBus = **日本有码 + 日本无码** 的目录 / 详情 / 磁力聚合站；素人 / FC2 / 国产别指望；欧美是另一站点。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | `dmm → libredmm → r18dev → **javbus** → …`（偏元数据/封面链中段） |
| 默认丰富链 · 无码 | `javbus → iqqtv → airav_io → miss_av → avsox`（AvSox 须 Flare 殿后） |
| makers 六区货架 | 仅挂在有码、无码 |
| 前缀权威同步 | `japan_censored` ← JavBus 有码列表；`japan_uncensored` ← JavBus 无码（+ carib） |
| 女优头像兜底 | GFriends 未中时可用 `/searchstar` 一类逻辑（见 actress 模块） |

### 网页实测（规范键）

探针：`data/debug/javbus_region_probe.txt`（经配置 Cookie / 镜像）。

| 区 | 输入 | 搜索 | 直接详情 `/{code}` |
|----|------|------|-------------------|
| 有码 | `SSIS-001` | 有码搜索命中 | ✅ |
| 有码 | `SONE-015` | 空 | 该号本次 404（站内未必收录每一号） |
| 无码 | `HEYZO-2034` | **无码搜索**命中 | ✅ |
| 无码 | `1PON-062014-830` | 空 | ❌ |
| 无码 | `062014_830` | 无码搜索命中 | ✅（站内 date6 常无 `1PON-` 前缀、用下划线） |
| 素人 / FC2 / 国产 / 欧美规范键 | 见探针 | 空 | ❌ |

### 番号与查找注意

详情路径本质是 `GET {base}/{CODE}`，对形态敏感：

| 问题 | 站内习惯 | 本仓库对策 |
|------|----------|------------|
| 有码补零 | 文件名可能 `SONE-15`，站内或为 `SONE-015` | `javbus_code_candidates` + `code_equiv` |
| 分盘字母 | `IPZZ-599C` 不是番号 | 剥成基号再查（与 MDCX 一致） |
| 无码 date6 | 常 `062014_830` / `1pondo-…` / 裸 `011317-002` | 候选列表含品牌 slug 与裸日期 |
| 无码搜索路径 | 需 `/uncensored/search/…` 时更稳 | 详情失败后 search 回退含该路径 |

测源请用 [region-code-formats.md](./region-code-formats.md) 的**规范键**；短号 / 字母尾只做兼容。

### 优缺点（实用向）

**适合**

- 扫有码 / 无码最新列表、按类别 / 女优浏览  
- 补详情：标题、封面、女优、类别、片商、样品图  
- 前缀权威与 makers 货架主数据  

**不适合**

- 素人官方（MGStage 数字板）主刮  
- FC2 / 国产 / 欧美（主站）  
- 当「唯一」有码源（DMM/LibreDMM 在官方元数据上往往更准）  

**运维**

- 必须测通镜像并写入 `activeBase`  
- Cookie 过期 → 年龄门，表现为「未找到」  
- 单号未收录属正常，勿当成解析全挂  

### 相关代码与文档

- `apps/api/app/scrape/source_catalog.py` · `javbus`  
- `apps/api/app/makers/catalog_routes.py` · `KIND_SHELVES` / `_javbus_detail`  
- `apps/api/scripts/sync_prefixes_from_authority_sites.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § JavBus  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 2. DMM / FANZA（`dmm`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `dmm` |
| 显示名 | DMM |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.dmm.co.jp` |
| 实际刮削 API | `https://api.video.dmm.co.jp/graphql`（FANZA 数字内容） |
| 播放/详情页参考 | `https://video.dmm.co.jp/av/content/?id={cid}` |
| 访问 | 自适应；Cookie 默认 `age_check_done=1; ckcy=1; cklg=ja; is_overseas=0` |
| 官网生态 | DMM 综合站 + **FANZA** 成人数字发行（本源只吃后者的 AV 数字商品） |

实现：`apps/api/app/scrape_details/dmm.py`（`guess_dmm_cids` → GraphQL `ppvContent`）。

### 官网实际有什么

FANZA / DMM Digital 成人侧常见分区（站点信息架构，非本仓库全部接入）：

| 分区（概念） | 典型路径 | 与本源关系 |
|--------------|----------|------------|
| **ビデオ（有码 AV）** | `/digital/videoa/` 等 | **本源目标**：有码数字商品 → CID GraphQL |
| 素人系 | `/digital/videoc/` 等 | 站上有，但 **本刮削器不按 videoc 列表扫**；素人默认走 MGStage |
| アニメ / その他 | `/digital/anime/` 等 | 不接入 |
| 海外 | FANZA 另有海外片库 | **不用**本 `dmm` 源；欧美走 ThePornDB |

注意：从境外直连 HTML 首页常落到 **ログイン - FANZA** 或空壳；**可靠路径是 GraphQL + CID**，不是爬列表页。本仓库 makers 货架（`KIND_SHELVES`）**没有**挂 DMM，它只做 enrich 详情。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★★ 官方首选 | 默认 enrich **第 1**；海报字段链第 1；CID 对齐 `std3_dmm` |
| 日本无码 | ☆☆☆☆☆ | HEYZO 等非 FANZA 主卖；实测 GraphQL 未中 |
| 日本素人 | ★☆☆☆☆ | 站上有素人货架，但 MGStage 板号（`259LUXU`）/ 多数素人号 GraphQL 未中；默认链无 dmm |
| FC2 | ☆☆☆☆☆ | 代码显式拒绝 `FC2*` |
| 国产 | ☆☆☆☆☆ | 非 FANZA 品番体系 |
| 欧美 | ☆☆☆☆☆ | 点分番号直接判无效 |

**一句话**：DMM 源 = **日本有码 FANZA 数字商品的官方元数据 / 封面**；别的区不要当主源。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | **`dmm` → libredmm → r18dev → javbus → …** |
| 字段 · 海报 | `dmm` 排头（`COVER_LOGIC` / `FIELD_PRIORITY`） |
| 有码 / 无码 / 素人 / … 其它默认链 | **不含** dmm |
| makers 货架 | 不挂 |
| 前缀 | 可写 `dmm_digit`（板号前缀）加速 CID；权威列表仍以 JavBus 等为主 |

### 网页 / API 实测（2026-09）

探针：`data/debug/dmm_region_probe.txt`（`scrape_detail` + Cookie）。

| 区 | 输入 | 结果 |
|----|------|------|
| 有码 | `SSIS-001` | ✅ 日文官名 + 可解析 |
| 有码 | `IPZZ-599` | ✅ |
| 有码 | `IPZZ-599C`（分盘尾） | ✅（已剥基号，同 `IPZZ-599`） |
| 有码 | `SONE-015` | ❌ 本次 CID 均未命中（号可能未上架 / digit 不对） |
| 无码 | `HEYZO-2034` | ❌ |
| 素人 | `HMDN-332` / `LUXU-001` / `259LUXU-001` | ❌ |
| FC2 / 欧美 | — | 格式直接拒绝或空 CID |
| 国产 | `MDSR-0002` | ❌ |

HTML 站内搜索页本次 `cid_hits=0`（登录墙 / 反爬），**以 GraphQL 为准**。

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 输入 | 规范有码键 `PREFIX-NNN`（pad=3）；胶合 `ssni00123` 可还原 |
| CID | `{digit}{series}{zfill5}`，如 `SSNI-123`→`ssni00123`；`ABP-900` 常先试 `118abp00900` |
| digit | 目录 `dmm_digit` → `dmm-series-digit.json` → 常见板号表 |
| 分盘尾 | `…C` / `…A` **不规范**；`_dmm_base_code` 剥掉再查 |
| 失败策略 | GraphQL 全未中 → **`未找到`**（已去掉「假封面 URL 冒充成功」） |
| 无搜索回退 | 与 JavBus 不同，没有 list search 补洞，全靠 CID 猜中 |

测源主输入：`SSIS-001`、`IPZZ-599` 等规范有码键；短号 / 字母尾仅兼容测。

### 优缺点（实用向）

**适合**

- 有码官名、片商、发售日、时长、女优、包装封面（`pl`）  
- 与 LibreDMM / R18.dev 组成有码官方三角  

**不适合**

- 无码专用厂、FC2、国产、欧美  
- 当「全库列表爬虫」（本实现无货架）  
- 素人主刮（请用 MGStage）  

**运维**

- Cookie / 地区限制会导致 HTML 像未登录；详情应看 API  
- 部分号缺 `dmm_digit` 时会多试板号，占超时预算  

### 相关代码与文档

- `apps/api/app/scrape_details/dmm.py`  
- `apps/api/app/prefix/catalog_dmm.py` · `apps/maps/sites/dmm-series-digit.json`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § DMM  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 3. LibreDMM / LibreFanza（`libredmm`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `libredmm` |
| 显示名 | LibreDMM |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.libredmm.com` |
| 页面标题 | **LibreFanza**（FANZA 公开元数据镜像/索引） |
| 访问 | 自适应；一般无需年龄 Cookie |
| 详情 API | `GET /movies/{CODE}.json`；可返回 `processing` 需短轮询 |
| 搜索 API | `GET /search.json?q=`（与详情同构单条） |

实现：`apps/api/app/scrape_details/libredmm.py`。

### 官网实际有什么（2026-09 探针）

站点结构很简单，**不是按「有码/无码/国产」分大区**，而是统一片库：

| 入口 | URL | 含义 |
|------|-----|------|
| Movies | `/movies` | 全库列表（探针见约 **23596** 页，体量极大） |
| Actresses | `/actresses` | 女优索引 |
| 浏览样式 | `?style=fuzzy` / `prefix` | 模糊 / 前缀浏览 |
| 排序 | `order=title` / `release_date` | 标题 / 发售日 |
| Sign in | `/sign_in` | 可选登录（列表可匿名看） |

列表里同时出现：

- 标准有码：`SSIS-001`、`IPZZ-599`、`MBRBH-025`…  
- 素人 / 企划味编号：`HMDN-332`、`LUXU-001`、`13ID-001`…  
- 写真 / 偶像系、VR（`VRKM-…`）等杂项前缀  

**没有**无码专用货架、FC2 专区、国产 / 欧美专区导航。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | 默认 enrich **第 2**（DMM 后）；海报链第 2；JSON 元数据稳 |
| **日本素人** | ★★★★☆ | 默认 enrich **第 2**（MGStage 后）；`HMDN` / `LUXU` 实测可中 |
| 日本无码 | ☆☆☆☆☆ | `HEYZO` / `1PON` 规范键 not_found |
| FC2 | ☆☆☆☆☆ | 未稳定命中 |
| 国产 | ☆☆☆☆☆ | `MDSR` 等空 |
| 欧美 | ☆☆☆☆☆ | 点分键无效 |

**一句话**：LibreDMM = **FANZA 系有码 + 部分素人** 的开源/公开元数据镜像；补 DMM 缺口、素人次选，不负责无码 / FC2 / 国产 / 欧美。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | `dmm → **libredmm** → r18dev → …` |
| 默认丰富链 · 素人 | `mgstage → **libredmm** → jav321 → …` |
| 字段 · 海报 | 紧随 DMM |
| makers 货架 | 不挂（无 KIND_SHELVES） |
| 直连 API 通道 | 与 dmm / r18dev / jav321 同类，走 api 槽 |

### 网页 / API 实测

探针：`data/debug/libredmm_region_probe.txt`。

| 区 | 输入 | `/movies/{code}.json` / scrape |
|----|------|--------------------------------|
| 有码 | `SSIS-001` | ✅ `nid=SSIS-001` |
| 有码 | `IPZZ-599` | ✅ |
| 有码 | `IPZZ-599C` | 直链 processing/空 → 候选剥成 `IPZZ-599` ✅ |
| 有码 | `SONE-015` | processing 后未找到（同号未必入库） |
| 无码 | `HEYZO-2034` / `1PON-…` | ❌ not_found |
| 素人 | `HMDN-332` | ✅ |
| 素人 | `LUXU-001` | ✅ |
| 素人 | `259LUXU-001` | 直链空 → 候选 `LUXU-001` ✅ |
| FC2 / 国产 / 欧美 | 规范键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 主路径 | `/movies/{CODE}.json`，`CODE` 大小写不敏感，建议大写 |
| `processing` | 站内异步建页，需 sleep 重试（实现里最多约 5 轮） |
| 分盘尾 | `…C` **不规范**，必须先剥基号（直查 `IPZZ-599C` 会空） |
| 素人板号 | `259LUXU-001` ↔ `LUXU-001`（剥板 + **加板**均在 `libredmm_code_candidates`） |
| pad | 短号 / 补零靠候选；校验用 `code_equiv` |
| 无码 date6 | 不要指望本站 |

### 优缺点（实用向）

**适合**

- DMM GraphQL 超时 / 缺 digit 时的有码兜底  
- 素人非 MGStage 官页时的元数据 / 封面  
- 大批量列表浏览（公开 movies 索引）  

**不适合**

- 无码专用厂、FC2、国产、欧美  
- 当「唯一」有码源（仍逊于 FANZA 官方 GraphQL）  

**运维**

- `processing` 多会拉长墙钟；单源超时要留余量  
- 与 DMM 数据同源倾向，字段可能高度重叠，合并时靠信任分 / 链顺序  

### 相关代码与文档

- `apps/api/app/scrape_details/libredmm.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § LibreDMM  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 4. AirAV.io（`airav_io`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `airav_io` |
| 显示名 | AirAV.io |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://airav.io/cn`（**简体**；根路径 `/` 为繁体） |
| 曾用壳 | `airav`（airav.wiki）已下线合并至此 |
| 访问 | 自适应 |
| 详情形态 | 搜索 → `/cn/video?hid=…`（hid 不含番号，靠标题匹配） |

实现：`apps/api/app/scrape_details/airav_io.py`；hid 可缓存于 `detail_path_cache`。

### 官网实际有什么（2026-09 探针）

简体导航（`/cn`）：

| 导航 | URL | 含义 |
|------|-----|------|
| **日本AV** | （下拉，站点主品牌） | 自我定位日本 AV / JAV |
| 今日/本周/本月热门 | `/cn/list?sort=3|4|5` | 人气榜 |
| VR | `/cn/tag?id=81` | VR 标签 |
| 发行商 | `/cn/factories` | 厂牌 |
| 女优一览 | `/cn/actors` | 女优 |
| 类型一览 | `/cn/tags` | 题材标签（巨乳/人妻/…），**不是六区导航** |
| 繁體 / 简体 | `/` · `/cn` | 语言切换 |

**没有**「有码 / 无码 / 国产 / 欧美」独立顶栏大区；内容靠搜索与标签混排。库内实际能搜到：有码、无码（HEYZO / 1pondo 下划线形）、FC2-PPV、部分素人、零星「麻豆」关键词片，以及无规范番号的西文标题。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ 中文补全 | 搜索/刮削中文标题强；**不进**有码默认区源链，但进全局 **title / overview / actors** 优先链 |
| **日本无码** | ★★★★☆ | 默认 enrich **第 3**；HEYZO 等可中；date6 规范键弱 |
| **FC2** | ★★★★☆ | 默认 enrich **第 3**；`FC2-PPV-*` 常见；纯 `FC2-{id}` 可能空 |
| 日本素人 | ★★☆☆☆ | 部分号（如 `LUXU-001`）可中；非默认区源 |
| 国产 | ★☆☆☆☆ | 规范番号空；「麻豆」关键词有片，**不能**当国产主源 |
| 欧美 | ☆☆☆☆☆ | `STUDIO.YYYY.MM.DD` 无效；关键词只有模糊西文标题 |

**一句话**：AirAV.io = **中文标题 / 剧情 / 标签聚合**，主战场是有码补中文 + 无码 / FC2 兜底；不是官方权威，也不是国产 / 欧美库。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 无码 | `javbus → iqqtv → **airav_io** → miss_av → avsox` |
| 默认丰富链 · FC2 | `fc2 → fd2ppv → **airav_io** → miss_av → freejavbt` |
| 默认丰富链 · 有码 / 素人 | **不含**（有码靠字段链吃中文） |
| 字段优先 | title / overview 排头；actors 第二档；**海报大幅降权**（`SOURCE_FIELD_BIAS` 负分） |
| 中文源集合 | `_CN_TEXT_SOURCE_IDS` 含本源 |

### 网页搜索 + scrape 实测

探针：`data/debug/airav_io_region_probe.txt`、`…_probe2.txt`、`airav_io_scrape_probe.txt`。

| 区 | 输入 | 搜索 | `scrape_detail` |
|----|------|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` | 有中文卡 | ✅ 中文标题 |
| 有码 | `SONE-015` | 空 | — |
| 无码 | `HEYZO-2034` | 有 | ✅ |
| 无码 | `1PON-062014-830` | 空 | —（站内多见 `1pondo_MMDDYY_NNN`） |
| 素人 | `LUXU-001` | 有 | ✅ |
| 素人 | `HMDN-332` / `259LUXU-001` | 易空 | — |
| FC2 | `FC2-PPV-4564537` | 有 | ✅ |
| FC2 | `FC2-976194` | 空 | ❌（缺 PPV / 未收录） |
| 国产 | `MDSR-0002` | 空 | ❌ |
| 欧美 | `BLACKED.2026.01.15` | 无规范命中 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | `search_result?kw=` 多候选 → 标题 **精确/等价**（`code_equiv` / date6）→ `hid` 详情 |
| 候选 | `airav_io_code_candidates`：pad / 剥板号 / FC2-PPV / date6 裸 `YYMMDD_NNN` + `1pondo_…` |
| 详情 URL | `/cn/video?hid=`，必须强制 `/cn` 以免繁体页 |
| FC2 | 优先 `FC2-PPV-{id}`；目录归一 `FC2-{id}` 时要能对应 PPV slug |
| 无码 date6 | 规范 `1PON-…` 常空；须搜 `062014_830` / `1pondo_…` |
| 垃圾条目 | 实现会拒「无码破解 / 流出」等 junk 标题 |
| 错页风险 | 历史 E2E：中文镜站簇可能抢锚；合并靠身份门禁 + 字段分 |

测源：有码用 `SSIS-001`；无码用 `HEYZO-2034`；FC2 用带 **PPV** 的号。

### 优缺点（实用向）

**适合**

- 给有码补**简体标题 / 剧情 / 标签**  
- 无码、FC2 元数据兜底  
- 女优中文名线索  

**不适合**

- 当有码 / 无码官方权威（封面差、易机翻或繁简混）  
- 国产规范番号、欧美点分键  
- 海报主选（bias 为负）  

**运维**

- 务必用 `/cn`；配置写成 `https://airav.io` 时实现会改写到 `/cn`  
- hid 缓存可加速，坏缓存需回落搜索  

### 相关代码与文档

- `apps/api/app/scrape_details/airav_io.py`  
- `apps/api/app/core/detail_path_cache.py`  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 5. Avmoo（`avmoo`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `avmoo` |
| 显示名 | Avmoo |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://avmoo.shop`（探针 `/cn`） |
| 访问 | **`proxy_flare`**（SPA；空壳须 FlareSolverr + `waitInSeconds`） |
| 家族 | **AIO 三站**（页面内 `window.__AIO_SITE_URLS__`） |

AIO 分工（同源前端，不同 `js-module`）：

| 键 | 域名 | 本仓库 id | 官网 meta 自称 |
|----|------|-----------|----------------|
| **jav** | `avmoo.shop` | `avmoo` | Japanese **adult** videos（有码向） |
| **javu** | `avsox.click` | `avsox` | Japanese **uncensored** adult videos |
| **wav** | `avheat.shop` | `avheat` | adult videos（目录进 **欧美** 组） |

实现：`scrape_details/avmoo.py` → `aio_common.scrape_aio_family`（与 AvSox / AVHeat 共用解析）。

### 官网实际有什么（2026-09 探针）

无 Flare 时只拿到 **~1.5KB SPA 壳**（`#jav-site-index` + loader）；导航与路由从官方 `/res/js` webpack chunk 还原（见 `data/debug/avmoo_chunk_scan.txt`、`avmoo_region_probe.txt`）。

简体顶栏（`/{lang}`，`lang ∈ {ja,en,tw,cn}`）：

| 导航 | URL | 含义 |
|------|-----|------|
| **影片** | `/cn` | 片库首页 |
| **已发行** | `/cn/released` | 按发售 |
| **热门** | `/cn/popular` | 人气 |
| **女优** | `/cn/actresses` | 女优列表 / `/cn/actresses/:id` |
| **类别** | `/cn/genres` | 题材类（主题/角色/…），**不是六区导航** |
| 搜索 | `/cn/search/{q}` | 番号 / 关键词 |
| 详情 | `/cn/movies/{movieId}` | 哈希 id，非番号路径 |

**没有**站内「无码 / 素人 / 国产 / 欧美」大区。无码入口在文案「更多无码影片」一类 **外链到 AvSox（javu）**，不在本域路径。

封面 CDN 常见 `netcdn.space`；解析侧可镜像到 `pics.dmm.co.jp`（`mirror_netcdn_to_dmm`）。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ 内容主库 | 自称日本 AV；顶栏即有码向片库。**不进**默认 enrich 区源（Flare 成本高、信任分中档） |
| 日本无码 | ☆☆☆☆☆ **别用本站** | 无码在姊妹站 **AvSox**；默认链已用 `avsox` |
| 日本素人 | ★☆☆☆☆ | 无素人专区；偶然有号也不当主源（素人默认是 MGS 链） |
| FC2 | ☆☆☆☆☆ | 非 FC2 库 |
| 国产 | ☆☆☆☆☆ | 非国产库 |
| 欧美 | ☆☆☆☆☆ | 欧美在姊妹站 **AVHeat**（`avheat`） |

**一句话**：Avmoo = AIO 家族的 **日本有码目录 / 详情 SPA**；无码去 AvSox，欧美去 AVHeat；本仓库默认丰富链**不挂**它，需要时手加或吃字段优先链。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 六区 | **均不含** `avmoo` |
| 默认丰富链 · 无码 | 用姊妹 **`avsox`**（链尾）；首选 `javbus` / `iqqtv` |
| 字段优先 · title | 中后段（在 avbase 之后） |
| 字段优先 · poster | 中后段（与 avsox 同档偏后） |
| `SOURCE_TRUST` | 74（低于 javbus / jav321） |
| `SOURCE_FIELD_BIAS` | actors / tags **+4**；poster **0** |
| 访问策略 | 先普通拉取；`is_aio_thin_shell` 则 Flare + wait≈3s |

### 网页搜索 + scrape 实测

探针：`data/debug/avmoo_region_probe.txt`（结构 + Flare 宕机时 scrape）。

| 方式 | 结果 |
|------|------|
| 壳 / meta / JS 路由 | ✅ 确认有码向 jav 站 + 三站分工 |
| 无 Flare 的 `scrape_detail` | ❌ 六区样例全部「搜索无结果」（空壳无卡片） |
| Flare 开启后 | 预期 `/cn/search/{CODE}` → 选 `movie-card` → `/cn/movies/{id}`（与 aio 解析一致）；**本次探针机 Flare 未起，未复测命中表** |

历史 E2E（`docs/E2E_SCRAPE_STANDARD.md`）：有码号可 scrape OK，但曾出现 **错页**（如 ABF-005 灌入无关女优/剧情）→ 合并侧靠标题门禁 / identity gate，不能只信品番字符串。

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | `std_code` → `/cn/search/{query}` → `pick_aio_movie_path`（span 展示番号优先，折叠全等，禁裸 substring） |
| 无码 date6 候选 | `aio_common`：`date6_search_variants`（裸 `062014_830` / 品牌 slug）+ 旧式 `BRAND-YYMMDD-NNN`→裸 `YYMMDD-NNN`；主要为 **AvSox** |
| pad | 搜索词叠 `append_std_pad_variants`（有码短号） |
| 详情 URL | 只有 `movieId`，番号在详情 `detail-label` / 卡片 span |
| 错页 | 品番一致仍可能脏数据；合并勿盲信 |
| 运维依赖 | **FlareSolverr 必开**；仅 curl/代理只会吃空壳 |

测源（Flare 正常时）：有码用 `SSIS-001` / `IPZZ-599`。不要用本源测无码 / FC2 / 国产 / 欧美。

### 优缺点（实用向）

**适合**

- 有码元数据 / 女优 / 标签补强（手加源或字段链）  
- 与 DMM 封面同源倾向时的备选海报  

**不适合**

- 默认批量 enrich 主链（Flare 慢、信任一般）  
- 无码 / 欧美（请用 `avsox` / `avheat`）  
- 当权威发售日 / 官方剧情源  

**运维**

- `access=proxy_flare`；面板 Flare 地址不可达时本源等于失效  
- 与 AvSox / AVHeat 共享解析代码，改 `aio_common` 会三站一起变  

### 相关代码与文档

- `apps/api/app/scrape_details/avmoo.py`  
- `apps/api/app/scrape_details/aio_common.py`  
- 姊妹站目录项：`avsox`、`avheat`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § Avmoo  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 6. Jav321（`jav321`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `jav321` |
| 显示名 | Jav321 |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.jav321.com`（简体；`en.` / `jp.` / `tw.` 子域） |
| 访问 | `proxy_adaptive`；**NEVER_FLARE**（稳定 curl/代理，不走 Flare） |
| 官网自称 | 标题「JAV321 dmm」——偏 DMM/有码 + 站内分类聚合 |

实现：`apps/api/app/scrape_details/jav321.py`（POST `/search` `sn=`，对齐 MDCS）。

### 官网实际有什么（2026-09 探针）

顶栏（`data/debug/jav321_nav_types.txt`）：

| 导航 | URL | 含义 |
|------|-----|------|
| **AV** | `/best_seller/1/…` · `/type/1/1` | 有码主库（人气/畅销） |
| **素人** | `/best_seller/2/…` · `/type/2/1` | 素人专区 |
| **シリーズ** | `/series_title_list/1` | 系列 |
| **ジャンル** | `/genre_list` | 题材（巨乳/人妻/…），不是六区 |
| Search | 表单 → **POST** `/search`（`sn=`） | 品番检索主路径 |
| Language | `www` 简 / `tw` 繁 / `jp` / `en` | 语言镜 |

首页另有区块链到：

| 区块 | URL | 含义 |
|------|-----|------|
| **無修正** | `/type/3/1` | 无码列表（有栏目） |
| 動画 | `/type/4/1` | 站内「動画」类 |
| **洋物ポルノ** | `/type/5/1` | 欧美栏目 |

详情形态：`/video/{slug}`；面板 `.panel-info` 含品番 / メーカー / 女优 / 标签 / 剧情。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | 默认 enrich 链；`SSIS-001` / `IPZZ-599` 实测 OK；库有缺口（如 `SONE-015` 未找到） |
| **日本素人** | ★★★★☆ | 顶栏有「素人」；默认 enrich **第 3**；`LUXU-001` / `HMDN-332` OK；板号 `259LUXU-*` 须与站内 `LUXU-*` 等价 |
| 日本无码 | ★☆☆☆☆ | 有「無修正」栏目，但 HEYZO / 1pondo 样例 **未找到**；不要当无码主源 |
| FC2 | ☆☆☆☆☆ | 实测空 |
| 国产 | ☆☆☆☆☆ | 实测空 |
| 欧美 | ★☆☆☆☆ | 有「洋物」栏目；`STUDIO.YYYY.MM.DD` 规范键无效，不当欧美 enrich |

**一句话**：Jav321 = **有码 + 素人** 的 DMM 向元数据站；无码/FC2/国产/欧美别指望。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | `… → javbus → **jav321** → avbase → mgstage` |
| 默认丰富链 · 素人 | `mgstage → libredmm → **jav321** → …` |
| 默认丰富链 · 无码 / FC2 / 国产 / 欧美 | **不含** |
| `SOURCE_TRUST` | 78 |
| `SOURCE_FIELD_BIAS` | tags **+10**、actors **+8**、title **+6**、poster **+2**（标签/女优偏强） |
| 封面 | CDN 偏慢，下载逻辑里作 **慢主机殿后**，避免挤掉 miss_av 等兜底 |

### 网页搜索 + scrape 实测

探针：`data/debug/jav321_region_probe.txt`、`jav321_nav_types.txt`。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` | ✅ |
| 有码 | `SONE-015` | ❌ 未找到（库缺口） |
| 无码 | `HEYZO-2034` / `1PON-062014-830` | ❌ |
| 素人 | `LUXU-001` / `HMDN-332` | ✅ |
| 素人 | `259LUXU-001` | ✅（修 `code_equiv` 板号后） |
| FC2 / 国产 / 欧美 | 样例键 | ❌ |

GET `/search?sn=` 往往只有壳；**必须以 POST `sn=`**（实现已如此）。

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | 多候选 `POST /search` `sn=`（`jav321_code_candidates`）→ `.panel-info` 品番 **`code_equiv`** |
| 候选 | pad / 素人加剥板 / FC2-PPV / date6 裸日期 |
| 素人板号 | 站内常写 `luxu-001`；查询 `259LUXU-001` / `HMDN-332`（加板）均可 |
| 错页史 | E2E ABF-005：站内品番标错仍可能返回脏剧情 → 合并靠标题门禁 |
| 封面 | 本站图慢；prestige 等路径可尝试镜像到 mgstage CDN（`enrich_cover`） |

测源：有码 `SSIS-001`；素人 `LUXU-001`（及板号 `259LUXU-001`）。

### 优缺点（实用向）

**适合**

- 有码 / 素人标题、女优、**标签**补强  
- 不依赖 Flare 的稳定拉取  

**不适合**

- 无码 / FC2 / 国产 / 欧美主源  
- 海报首选（慢 CDN + bias 不高）  
- 当唯一权威（曾有品番标错脏页）  

**运维**

- 勿对 jav321 开 Flare（`NEVER_FLARE`）  
- 封面并发需给兜底源留席  

### 相关代码与文档

- `apps/api/app/scrape_details/jav321.py`  
- 测试：`app/tests/test_jav321_avbase_candidates.py`  
- `code_equiv` 板号：`scrape_details/common.py`；测试 `app/tests/test_code_equiv_board_prefix.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § Jav321  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 7. AVBase（`avbase`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `avbase` |
| 显示名 | AVBase |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.avbase.net` |
| 访问 | `proxy_adaptive`（Next.js；页内 `__NEXT_DATA__` JSON） |
| 官网自称 | 「AV検索データベース \| アダルトビデオの情報基地！」 |

实现：`apps/api/app/scrape_details/avbase.py`（直链 `/works/{CODE}` → 否则 `/works?q=` 再进详情）。

### 官网实际有什么（2026-09 探针）

顶栏 / 首页（`data/debug/avbase_region_probe.txt`）：

| 导航 | URL | 含义 |
|------|-----|------|
| **本日発売** | `/works/date` | 按发售日 |
| **新着作品** | `/works/recent` | 新作 |
| **作品コメント** | `/comments/works` | 评论 |
| **詳細検索** | `/search` | 高级搜索 |
| 女优榜 | `/talents/popular` 等 | 人气女优 |
| 作品 | `/works/{work_id}` | 详情（`work_id` 多为规范番号） |
| 搜索 | `/works?q=` | 关键字 / 品番 |

实体页：`/makers/…`、`/labels/…`、`/series/…`、`/talents/…`（挂在作品卡上，**无**独立「无码 / 素人 / FC2」大区）。

试探路径 `/uncensored` `/amateur` `/fc2` → **404**。首页混有 FANZA 有码、部分素人、VR、同人/gyutto 等，靠搜索聚合，不是六区货架。

搜索噪声：同品番可能出现 `secondface:SSIS-001` 一类带源前缀的异源条目；实现**拒绝**冒号前缀 `work_id`，只认正牌键。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | 默认 enrich 链末段；`SSIS-001` / `IPZZ-599` ✅；库有缺口（`SONE-015` ❌） |
| **日本素人** | ★★★★☆ | 默认 enrich；`LUXU-001` / `HMDN-332` / `259LUXU-001` ✅ |
| 日本无码 | ☆☆☆☆☆ | HEYZO / 1pondo / Caribbean 样例 ❌；无无码专区 |
| FC2 | ☆☆☆☆☆ | 样例 ❌ |
| 国产 | ☆☆☆☆☆ | 样例 ❌ |
| 欧美 | ☆☆☆☆☆ | 点分键 ❌ |

**一句话**：AVBase = **日本有码 + 素人** 的 Next 元数据库（FANZA 产品信息聚合）；无码 / FC2 / 国产 / 欧美不当主源。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | `… → jav321 → **avbase** → mgstage` |
| 默认丰富链 · 素人 | `… → freejavbt → **avbase** → iqqtv` |
| 默认丰富链 · 无码等 | **不含** |
| `SOURCE_TRUST` | 76 |
| `SOURCE_FIELD_BIAS` | actors/tags 中档；poster 弱 |
| 字段优先 · tags | 与 javbus / freejavbt 并列前置 |

### 网页搜索 + scrape 实测

探针：`data/debug/avbase_region_probe.txt`。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` | ✅ |
| 有码 | `SONE-015` / `SONE-15` | ❌ 未收录 |
| 无码 | HEYZO / 1PON / CARIB | ❌ |
| 素人 | `LUXU-001` / `HMDN-332` / `259LUXU-001` | ✅ |
| FC2 / 国产 / 欧美 | 样例键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | 多候选 `/works/{CODE}` → `/works?q=`（`avbase_code_candidates`） |
| 候选 | pad / 素人加剥板 / FC2-PPV / date6 |
| 匹配 | `match_avbase_work_id` → **`code_equiv`**；`source:CODE` 前缀条目拒 |
| 产品 | 多 `products` 时偏好 FANZA + `pl.jpg` 封面 |
| 日期 | 可能是 ISO 或 JS `Date` 字符串，解析侧已兼容 |

测源：有码 `SSIS-001`；素人 `LUXU-001`。

### 优缺点（实用向）

**适合**

- 有码 / 素人元数据、女优、标签补强  
- 结构化 JSON，解析稳  

**不适合**

- 无码 / FC2 / 国产 / 欧美  
- 海报首选（bias 低）  
- 当唯一权威（库缺口、搜索噪声）  

**运维**

- 依赖 `__NEXT_DATA__`；前端改版要同步解析  
- 代理可达；本探针未强制 Flare  

### 相关代码与文档

- `apps/api/app/scrape_details/avbase.py`  
- 测试：`app/tests/test_avbase_work_id_match.py`、`test_jav321_avbase_candidates.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § AVBase  
- 番号格式：[region-code-formats.md](./region-code-formats.md)

---

## 8. MGStage（`mgstage`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `mgstage` |
| 显示名 | MGStage |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.mgstage.com` |
| 访问 | `proxy_adaptive`；**须 Cookie `adc=1`**（目录 `defaultCookie`） |
| 官网自称 | 「エロ動画・アダルトビデオ - **MGS動画＜プレステージ グループ＞**」 |

实现：`apps/api/app/scrape_details/mgstage.py`（对齐 MDCS）。

### 官网实际有什么（2026-09-23 实页）

| 能力 | URL / 选择器 | 含义 |
|------|----------------|------|
| 年龄门 | Cookie `adc=1` | 无则易挡 |
| 详情 | `/product/product_detail/{CODE}/` | 素人多为 **数字板号**（`259LUXU-001`） |
| 搜索 | `/search/cSearch.php?search_word=…&type=top` | 裸 `LUXU-001` 实测 **空结果**；`259LUXU-001` 有链 |
| 元数据表 | `.detail_data th/td` | 品番、出演、メーカー、レーベル、シリーズ、日付、時間、ジャンル |
| 封面 | `#EnlargeImage` / `image.mgstage.com` | 官方图 |

无「无码 / FC2 / 国产 / 欧美」大区；主库 = Prestige 系有码 + 素人配信系列。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本素人** | ★★★★★ | 默认 enrich **第 1**；`259LUXU` / `328HMDN` / `SIRO` 实测 OK |
| **日本有码** | ★★★★☆ | 默认 enrich 末段；`ABP-001` OK；`SSIS-001` 等非 MGS 号空 |
| 日本无码 | ☆☆☆☆☆ | HEYZO 等空 |
| FC2 / 国产 / 欧美 | ☆☆☆☆☆ | 空 |

**一句话**：MGStage = **素人官方（数字板号）+ Prestige 系有码**；测源请用板号或依赖候选扩展。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 素人 | **`mgstage` →** libredmm → jav321 → … |
| 默认丰富链 · 有码 | `… → avbase → **mgstage**` |
| `SOURCE_TRUST` | **95** |
| `SOURCE_FIELD_BIAS` | poster **+28**、studio/maker **+14**、date **+12** |
| Cookie | 空则目录默认 `adc=1` |

### 网页搜索 + scrape 实测

探针：`data/debug/mgstage_region_probe.txt`（连通恢复后）。

| 区 | 输入 | 结果 |
|----|------|------|
| 素人 | `259LUXU-001` | ✅ ラグジュTV |
| 素人 | `LUXU-001` | ✅（`mgstage_code_candidates` → `259LUXU-*`） |
| 素人 | `HMDN-332` | ✅（→ `328HMDN-332`） |
| 素人 | `SIRO-1234` | ✅（无板号亦可） |
| 有码 | `ABP-001` | ✅ プレステージ |
| 有码 | `SSIS-001` | ❌ 非本站库 |
| 无码 / FC2 | 样例 | ❌ |

首页曾短暂 403；恢复后上述样例可复现。

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | 多候选直链 → 搜索 → `_pick_detail_href`（`code_equiv`，禁首链兜底） |
| 板号 | 裸字母号站内常搜不到；用目录 `japan_amateur` 反查 `259LUXU` 等，失败再用内置兜底表 |
| 品番校验 | 页内品番与查询 **`code_equiv`** |
| 预告片 | `sampleRespons` 函数保留，scrape **不调用** |

### 优缺点（实用向）

**适合**：素人官方元数据/封面；Prestige 有码片商与大海报。  
**不适合**：FANZA 独占有码、无码、FC2、国产、欧美。  
**运维**：必 `adc=1`；出口不稳时会整源 403。

### 相关代码与文档

- `apps/api/app/scrape_details/mgstage.py`（`mgstage_code_candidates`）  
- 测试：`test_mgstage_code_candidates.py`、`test_mgstage_pick_href.py`、`test_soup_reuse_and_mgstage_table.py`  
- [region-code-formats.md](./region-code-formats.md) § 素人 · [source-region-code-audit.md](./source-region-code-audit.md) § MGStage  

---

## 9. FreeJavBT（`freejavbt`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `freejavbt` |
| 显示名 | FreeJavBT |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://www.freejavbt.com` |
| 访问 | `proxy_adaptive` |
| 官网自称 | 「FREE JAV BT \| 每日更新」 |

实现：`apps/api/app/scrape_details/freejavbt.py`（直链 `/{CODE}` / `/zh|ja|en/{CODE}`）。

### 官网实际有什么（2026-09 探针）

多语言顶栏（`/en` `/zh` `/ja` …）分区清晰：

| 导航 | URL 形态 | 含义 |
|------|----------|------|
| **Censored / 有修正** | `/…/censored` | 有码 |
| **Uncensored / 無修正** | `/…/uncensored` | 无码 |
| **Western / 西洋** | `/…/western` | 欧美 |
| **FC2** | `/…/fc2` | FC2 |
| 搜索 | `/…/search/{kw}` | 前缀/关键字（如 LUXU、ARA、SIRO） |
| 榜 / 女优 / 系列 | `/rank/…` `/actress` `/series/…` | 附属 |

详情多为 `/{CODE}`（无语言前缀也可）；软 404 页标题「You May Like / 猜你喜欢 / 你可能喜欢」。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | `SSIS` / `IPZZ` / `ABP` 实测 OK；字段链 tags 强 |
| **日本无码** | ★★★☆☆ | 有专区；`HEYZO` OK；date6（1pondo）弱 |
| **日本素人** | ★★★★☆ | 默认 enrich（女优）；`LUXU` OK；须剥 `259LUXU` |
| **FC2** | ★★★☆☆ | 有专区；`FC2-{id}` 可中（实现会试 PPV）；库存参差 |
| 国产 | ☆☆☆☆☆ | `MDSR` 空 |
| 欧美 | ★☆☆☆☆ | 有 Western 栏目；点分规范键无效 |

**一句话**：FreeJavBT = **有码 / 无码 / 素人 / FC2 聚合页**（偏播放与标签）；信任分一般，海报降权，适合补女优/标签。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 素人 | `… → **freejavbt** → avbase → iqqtv` |
| 默认丰富链 · 有码 / 无码 / FC2 | **不含**（可手加） |
| `SOURCE_TRUST` | 62 |
| `SOURCE_FIELD_BIAS` | tags **+14**、title **+6**、poster **-8** |
| 字段优先 · tags | 与 javbus / avbase 并列前置 |

### 网页搜索 + scrape 实测

探针：`data/debug/freejavbt_region_probe.txt`。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` / `ABP-001` | ✅ |
| 无码 | `HEYZO-2034` | ✅ |
| 无码 | `1PON-062014-830` | ❌ |
| 素人 | `LUXU-001` / `259LUXU-001` | ✅（后者经剥板号） |
| 素人 | `HMDN-332` | ❌ |
| FC2 | `FC2-976194` | ✅ |
| FC2 | `FC2-PPV-4564537` | ❌ |
| 国产 / 欧美 | 样例键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | 多语言 path 试 `/{slug}`；页内须 `page_mentions_code` |
| 素人板号 | 剥板 `259LUXU`→`LUXU`；加板 `HMDN`→`328HMDN`（`append_amateur_board_variants`） |
| 无码 date6 | 候选含裸 `062014_830` / `1pondo_…`（直链试 path） |
| FC2 | 候选 `FC2-PPV-*` / `FC2-*` / 裸数字 id |
| 软 404 | 「You May Like / 猜你喜欢 / 你可能喜欢」跳过续试，勿当硬失败打断 |
| 女优 | 标题点名优先；过滤男优名表 `AV_MAN_NAMES` |

测源：有码 `SSIS-001`；素人 `LUXU-001`；无码 `HEYZO-2034`；FC2 `FC2-976194`。

### 优缺点（实用向）

**适合**：有码/素人标签与女优补强；部分无码与 FC2 兜底。  
**不适合**：官方权威、海报首选、国产、欧美点分键。  
**运维**：页面广告/推荐区多；解析已尽量避开 related sidebar。

### 相关代码与文档

- `apps/api/app/scrape_details/freejavbt.py`  
- 测试：`app/tests/test_freejavbt_code_candidates.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § FreeJavBT  

---

## 10. 7MMTV（`sevenmmtv`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `sevenmmtv`（别名 `7mmtv` / `mmtv`） |
| 显示名 | 7MMTV |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://7mmtv.sx/zh` |
| 访问 | `proxy_adaptive` |
| 官网自称 | 「7mmtv.sx - Watch JAV Online」 |

实现：`apps/api/app/scrape_details/sevenmmtv.py`（搜索 → 详情；路径缓存）。

### 官网实际有什么（2026-09 探针）

中文顶栏分区与规模（`/zh/`，数量随站点变动）：

| 导航 | URL 形态 | 含义 |
|------|----------|------|
| **有碼AV** | `/zh/censored_list/…` | 有码主库 |
| **素人AV** | `/zh/amateurjav_list/…` | 素人（SIRO / LUXU / 200GANA…） |
| **無碼AV** | `/zh/uncensored_list/…` | 无码（含 HEYZO / 1pondo / **FC2** maker） |
| **中字AV** | `/zh/chinese_list/…` | 中文字幕拷贝 |
| **無碼破解** | `/zh/reducing-mosaic_list/…` | 去码镜像（选链时降权） |
| **國產影片** | `/zh/amateur_list/…` | 国产（注意：与「素人AV」URL 前缀不同） |
| 搜索 | `/zh/searchall_search/all/{kw}/1.html` | 全站搜索 |

详情 URL：`/{type}_content/{id}/{slug}.html`（如 `censored_content/…/SSIS-001.html`、`amateurjav_content/…/328HMDN-332.html`、`uncensored_content/…/fc2-ppv-976194.html`）。  
国产常见 `amateur_content/{id}/content.html`（slug **无番号**）。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | `SSIS` / `IPZZ` 实测 OK；优先 `censored` 再中字 |
| **日本无码** | ★★★☆☆ | 有专区；新号 `HEYZO-3941` OK；旧号/date6 库存弱 |
| **日本素人** | ★★★★☆ | 专区 + 板号 slug（`328HMDN` / `259LUXU`）；须 `code_equiv` |
| **FC2** | ★★★★☆ | 挂在无码 maker；搜索常须**裸数字 id** |
| 国产 | ★★☆☆☆ | 有「國產影片」库；URL 常无番号，当前实现拒收防错绑 |
| 欧美 | ☆☆☆☆☆ | 无可用分区；点分键无效 |

**一句话**：7MMTV = **中文向聚合库**（有码 / 素人 / 无码+FC2 + 国产栏目）；信任中等，海报降权，标题/标签可补中文。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 各区 | **不含**（可手加；属中文文本源集合） |
| `SOURCE_TRUST` | 60 |
| `SOURCE_FIELD_BIAS` | title **+10**、tags **+18**、overview **+8**、poster **-10** |
| 字段优先 · title | 中文链前置之一（airav / iqqtv / miss_av 之后） |

### 网页搜索 + scrape 实测

探针：`data/debug/sevenmmtv_region_probe.txt`。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` | ✅（优先 censored） |
| 无码 | `HEYZO-3941` | ✅ |
| 无码 | `HEYZO-2034` / `1PON-062014-830` | ❌（库存/检索弱） |
| 素人 | `HMDN-332` | ✅（slug `328HMDN-332`） |
| 素人 | `259LUXU-1896` | ✅ |
| 素人 | `LUXU-001` / `259LUXU-001` | ❌（早期号无索引） |
| FC2 | `FC2-976194` / `FC2-PPV-4564537` | ✅（搜裸 id / PPV） |
| 国产 / 欧美 | 样例键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | 候选词搜 `searchall` / `searchform` / POST → `pick_sevenmmtv_detail_href` |
| 素人板号 | slug 常带板号；挑选用 `code_equiv`（勿仅 `endswith` fold） |
| 无码 date6 | `sevenmmtv_code_candidates` 含裸 `062014_830` / 品牌 slug |
| FC2 | `sevenmmtv_code_candidates` 含 `FC2-PPV-*` 与**裸数字**；站内 slug 多 `fc2-ppv-{id}` |
| 去码镜像 | `reducing-mosaic_content` 分最低，避免抢有码正片 |
| 国产 | `…/content.html` 无番号 → **不选**（防错绑） |
| 缓存 | `detail_path_cache`；页内番号校验失败回落搜索 |

测源：有码 `SSIS-001`；素人 `HMDN-332` 或 `259LUXU-1896`；无码 `HEYZO-3941`；FC2 `FC2-976194`。

### 优缺点（实用向）

**适合**：中文标题/标签补强；有码+素人+FC2 聚合兜底。  
**不适合**：官方权威、海报首选、欧美、依赖无番号 URL 的国产精准刮。  
**运维**：镜像域名见 catalog `SOURCE_MIRRORS`；页面广告多，选链已按分区打分。

### 相关代码与文档

- `apps/api/app/scrape_details/sevenmmtv.py`（`sevenmmtv_code_candidates` / `_href_matches_code`）  
- 测试：`app/tests/test_sevenmmtv_code_candidates.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § 7MMTV  

---

## 11. iQQTV（`iqqtv`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `iqqtv` |
| 显示名 | iQQTV |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://iqq5.xyz/cn`（实现默认根 `iqqk4.quest`；镜像见 catalog） |
| 访问 | `proxy_adaptive` |
| 官网自称 | 「iQQTV - …线上成人A片高清直播」 |

实现：`apps/api/app/scrape_details/iqqtv.py`（`/jp|/cn` 搜索 → `player.php?uuid=`；中文优先）。

### 官网实际有什么（2026-09 探针）

顶栏/入口（`/cn/`，`iqq5.xyz` / `iqqk4.quest` 均可）：

| 导航 | URL 形态 | 含义 |
|------|----------|------|
| **日本** | `search.php?s_type=jp&…` | 有码向日本区 |
| **无码** | `s_type=scate` / `category.php?scate=1` | 无码 |
| **国产** | `zone_index.php?zone=1` | 国产专区 |
| **欧美** | `s_type=us` / `?cat=us` | 欧美 |
| **中文** | `s_type=tag`（中文字幕标签） | 标签筛选 |
| 搜索 | `/cn\|jp/search.php?kw=` | 关键字 |

详情：`/cn|jp/player.php?uuid=…&cat=…`（uuid 稳定，可缓存）。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★★ | 中文标题/剧情主源之一；`SSIS`/`IPZZ` 实测 OK |
| **日本无码** | ★★★★☆ | HEYZO OK；date6 须搜 `062014_830` / `_1pondo_…` |
| **日本素人** | ★★★★☆ | 默认 enrich 链尾；须剥 `259LUXU`；部分前缀库存空 |
| **FC2** | ★★★☆☆ | 站内有大量 FC2；搜 `FC2-PPV-*` / 裸 id；旧号可能无索引 |
| 国产 | ★★☆☆☆ | 有专区；样例番号检索弱 |
| 欧美 | ★☆☆☆☆ | 有栏目；点分规范键无效 |

**一句话**：iQQTV = **中文标题/剧情/标签强源**（有码主补 + 素人链尾）；海报严重降权。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 素人 | `… → freejavbt → avbase → **iqqtv**` |
| 默认丰富链 · 无码 | `javbus → **iqqtv** → airav_io → miss_av → avsox` |
| 默认丰富链 · 有码/FC2/国产/欧美 | **不含**（可手加；有码吃字段链） |
| `SOURCE_TRUST` | 68 |
| `SOURCE_FIELD_BIAS` | overview **+28**、title **+24**、tags **+30**、actors **+6**、poster **-20** |
| 字段优先 · title/overview | 中文链前置（紧随 airav_io） |

### 网页搜索 + scrape 实测

探针：`data/debug/iqqtv_region_probe.txt`（基址 `https://iqq5.xyz/cn`）。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` | ✅ |
| 无码 | `HEYZO-2034` / `HEYZO-3941` | ✅ |
| 无码 | `1PON-062014-830` | ✅（经 date6 候选） |
| 素人 | `LUXU-001` / `259LUXU-001` / `259LUXU-1896` | ✅（板号剥+页校验） |
| 素人 | `HMDN-332` | ❌ |
| FC2 | `FC2-PPV-4564537` | ✅ |
| FC2 | `FC2-976194` | ❌（库存） |
| 国产 / 欧美 | 样例键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 流程 | `iqqtv_code_candidates` → `/jp/search.php?kw=` → `get_iqqtv_real_url` → CN/JP player |
| 素人板号 | `259LUXU-001` 搜空，须剥 `LUXU-001`；详情标题用 `code_equiv` |
| 无码 date6 | 站内尾号 `_1pondo_062014_830`；搜 `062014_830` |
| FC2 | 候选 `FC2-PPV-*` / `FC2PPV-*` / 裸数字；标题匹配勿再「剥 FC2 后残留 `-id`」 |
| 页校验 | `_iqqtv_page_mentions`：标准 mentions + 标题等价 |
| Junk | 标题含「无码破解/流出」等跳过 |

测源：有码 `SSIS-001`；素人 `259LUXU-001`；无码 `1PON-062014-830`；FC2 `FC2-PPV-4564537`。

### 优缺点（实用向）

**适合**：中文标题/剧情/标签；有码与素人补强；部分无码与 FC2。  
**不适合**：海报首选、官方权威、欧美点分键、依赖冷门国产番号。  
**运维**：多镜像轮换；同站双页曾打满连接槽，实现已中文优先少打日文。

### 相关代码与文档

- `apps/api/app/scrape_details/iqqtv.py`（`iqqtv_code_candidates` / `match_iqqtv_number`）  
- 测试：`app/tests/test_iqqtv_code_candidates.py`  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § iQQTV  

---

## 12. R18.dev（`r18dev`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `r18dev` |
| 显示名 | R18.dev |
| 分组 | 有码 AV（`av`） |
| 默认地址 | `https://r18.dev` |
| 访问 | `proxy_adaptive`（**非 Flare**；HTML 首页可被 CF，JSON 走面板代理） |
| 官网能力 | FANZA/DMM 系 **JSON API**（`dvd_id` / `combined=content_id`） |

实现：`apps/api/app/scrape_details/r18dev.py`。

### 官网实际有什么（2026-09 探针）

无传统「分区导航」——以 API 为主：

| 接口 | URL 形态 | 含义 |
|------|----------|------|
| DVD 检索 | `/videos/vod/movies/detail/-/dvd_id={series}{5位}/json` | 例 `ssis00001` |
| 详情合并 | `/videos/vod/movies/detail/-/combined={content_id}/json` | 厂牌前缀 + 品番（见 `r18-content-id-prefixes.json`） |

字段含日/英标题、女优、片商、发行日、jacket、样片、分类等。实现将 `mosaic` 固定标 **有码**（FANZA 数字盘库）。

直连无代理时首页/JSON 可 **403 CF HTML**；本仓库 `fetch_json(source_id=r18dev)` + 代理通道实测可用。调度：同站 API 单飞 + ≥0.45s 间距。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★★ | 默认 enrich 链；海报/厂牌/日期权威之一 |
| **日本素人** | ★★★☆☆ | 部分 FANZA 上架素人（如 `HMDN`）可中；MGS 独占（LUXU）无 |
| 日本无码 | ☆☆☆☆☆ | 非库 |
| FC2 | ☆☆☆☆☆ | 非库 |
| 国产 | ☆☆☆☆☆ | 非库 |
| 欧美 | ☆☆☆☆☆ | 非库 |

**一句话**：R18.dev = **FANZA 有码 JSON 镜像**（免 Flare、官方向元数据/海报）；默认有码链第三顺位。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 有码 | `dmm → libredmm → **r18dev** → javbus → …` |
| 其它区默认链 | **不含** |
| `SOURCE_TRUST` | 93 |
| `SOURCE_FIELD_BIAS` | poster **+20**、studio/date **+12**、actors **+10** |
| 字段优先 · poster | dmm / libredmm / **r18dev** / javbus / mgstage |

### 网页搜索 + scrape 实测

探针：`data/debug/r18dev_region_probe.txt`（经 `scrape_detail` / 代理）。

| 区 | 输入 | `scrape_detail` |
|----|------|-----------------|
| 有码 | `SSIS-001` / `IPZZ-599` / `SONE-001` / `ABP-123` | ✅ |
| 有码 | `SONE-015` / `SONE-15` | ❌（本号库存/API 无可靠命中） |
| 素人 | `HMDN-332` | ✅ |
| 素人 | `LUXU-001` / `259LUXU-001` | ❌（MGS 独占，不在 FANZA） |
| 无码 / FC2 / 国产 / 欧美 | 样例键 | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| DVD id | 去横线后数字 **补 5 位**（`SSIS-001`→`ssis00001`） |
| content_id | 厂牌前缀表 + 3/5 位变体 |
| 匹配 | `dvd_id` 用 `code_equiv`；仅 `content_id` 时比系列+数字 |
| 板号 | `r18dev_code_candidates` 剥 `259LUXU`→`LUXU`；空响应不得放行 |
| 错配防护 | API 模糊返回（如搜 `sone00015` 却给 `sone00105`）须拒收 |

测源：有码 `SSIS-001`；可选手测素人 `HMDN-332`。勿用本源测无码/FC2/国产/欧美。

### 优缺点（实用向）

**适合**：有码海报、厂牌、日期、女优；与 DMM/LibreDMM 互补。  
**不适合**：无码、FC2、国产、欧美、多数 MGS 独占素人。  
**运维**：勿当 Flare 源；尊重 API 限速；HTML 壳 403 不代表 JSON 不可用。

### 相关代码与文档

- `apps/api/app/scrape_details/r18dev.py`（`r18dev_code_candidates` / `_r18_detail_matches_code`）  
- 映射：`r18-content-id-prefixes.json`  
- 测试：`app/tests/test_r18dev_code_candidates.py`、`test_direct_api_slot.py`（限速）  
- 审计：[source-region-code-audit.md](./source-region-code-audit.md) § R18.dev  

---

## U. 无码前缀专用站（批量 · 2026-09 复测）

不进无码默认 UI 链；刮削时由 `uncensored_official_for_code` **按番号前缀自动插入**兜底链前（`enrich_strategy.UNCENSORED_OFFICIAL_SOURCE_IDS`）。

访问均为 **`proxy_adaptive`**（非 Flare）。探针：`data/debug/uncensored_official_probe.txt`。

| id | 前缀 | 样例番号 | 首页 | scrape + 封面 |
|----|------|----------|------|----------------|
| `heyzo` | `HEYZO` | HEYZO-2034 | ✅ | ✅ |
| `1pondo` | `1PON` | 1PON-062014-830 | ✅ | ✅ |
| `pacopacomama` | `PACO` | PACO-122615-557 | ✅ | ✅ |
| `carib` | `CARIB` | CARIB-010117-339 | ✅ | ✅ |
| `10musume` | `10MU` | 10MU-122817-01 | ✅ | ✅ |
| `kin8` | `KIN8` | KIN8-3500 | ✅ | ✅ |
| `h0930` | `H0930` | H0930-ki260908 | ✅ | ✅ |
| `h4610` | `H4610` | H4610-ki260908 | ✅ | ✅ |
| `c0930` | `C0930` | C0930-hitozuma1369 | ✅ | ✅ |
| `tokyohot` | `TOKYOHOT` | TOKYOHOT-N1234 | ✅ | ✅ |
| `nyoshin` | `NYOSHIN` | NYOSHIN-2500 | ✅ | ✅ |
| `heydouga` | `HEYDOUGA` | HEYDOUGA-4030-001 | ✅ | ✅ |

前缀路由实测全部命中预期源；**无需改匹配器**。

**AvSox（`avsox`）**：同区通用兜底，`proxy_flare`。本次保留；直连/代理拿空壳或 403，详情须 Flare（与 Avmoo 同族）。默认无码链已改为 `javbus → iqqtv → … → avsox`，Flare 未起时只影响链尾。

---

## F. FC2 / FC2-PPV（`fc2` · `fd2ppv`）

探针：`data/debug/fc2_fd2ppv_probe.txt`。

### FC2（`fc2`）· 官网

| 项 | 内容 |
|----|------|
| 地址 | `https://adult.contents.fc2.com` |
| 访问 | `proxy_adaptive` + Cookie `adult_check=1` |
| 详情 | `/article/{id}/` |

| 检查 | 结果 |
|------|------|
| 首页 | ✅ ~230KB，无 CF |
| `FC2-1545500` | ✅ 有封面 |
| `FC2-PPV-4564537` | ✅（归一 `FC2-4564537`） |
| `FC2-4980536` | ✅ |
| `FC2-976194` 等 | ❌ 未找到（库存） |

**结论**：官方 FC2 可用，作默认 FC2 链主源合适。

### FC2-PPV（`fd2ppv`）· fd2ppv.cc

| 项 | 内容 |
|----|------|
| 地址 | `https://fd2ppv.cc` |
| 访问 | `proxy_adaptive`（目录标注）；详情路径实际遇 CF |
| 详情 | `/articles/{id}` |

| 检查 | 结果 |
|------|------|
| 首页列表 | ✅（设置页「测通」指此） |
| `/articles/{id}` | ❌ **HTTP 403**（`Just a moment`）；首页链出的新号同样失败 |

**结论**：列表能开、详情过不了盾；当前 enrich 当详情源等于失效。默认链仍为 `fc2 → fd2ppv → airav_io`，fd2ppv 环会空跑失败。是否下线待定（用户未裁定）。

实现：`scrape_details/fc2.py`、`fd2ppv.py`。

---

## C. 国产源（批量 · 2026-09 复测）

默认 enrich 链：`madouqu → xiao_huang_shu → madou → miss_av`（`hscangku` 故意不进默认）。  
探针：`data/debug/china_sources_probe.txt`。

| id | 地址 | 访问 | 首页 | 样例 scrape |
|----|------|------|------|-------------|
| **`madou`** | madou.club | adaptive | ✅ 「麻豆社…」 | `MDX-0001` / `MDSR-0002` / `MDX-0006` **全 ✅** |
| `madouqu` | madouqu.com | adaptive（标） | ❌ **403 CF** `Just a moment` | 全 ❌ 未找到 |
| `xiao_huang_shu` | xchina.co | adaptive | ❌ **403 Access denied**（CF 拒访，非仅 JS 挑战） | 全 ❌ |
| `hscangku` | hsck.net | adaptive | ⚠ 极薄页 (~423B) | `MDX-0006` / `MDSR-0002` ✅；`MDX-0001` ❌ |

**结论**

- **Madou**：当前国产主可用源。  
- **Madouqu / 小黄书**：现网过不了（挑战 / 拒访）；默认链前两环会空跑。是否按过盾规则下线待裁定。  
- **黄色仓库**：能刮部分号，首页壳异常；注释里曾慢+Flare，本次未强制 Flare 也能中。

---

## W. 欧美源（ThePornDB + AVHeat · 2026-09 复测）

默认 enrich 链：`theporndb → avheat`（API 权威 + Flare 聚合兜底）。  
探针：`data/debug/western_sources_probe.txt`。

| id | 地址 | 访问 | 首页 | 样例 scrape |
|----|------|------|------|-------------|
| **`theporndb`** | theporndb.net → **api.theporndb.net** | adaptive + **API Key** | ✅ 站点壳通 | `BLACKED.2026.01.15` / `.26.01.15` / `PURETABOO…` / `VIXEN…` **全 ✅** |
| **`avheat`** | avheat.shop（AIO **wav**） | **`proxy_flare`**（SPA） | 壳 ~1.5KB；curl 直连 403 | `WeLiveTogether.12.02.23` / `…2012.02.23` / `BrazzersExxtra.26.07.09` / `…2026.07.09` **✅**；`BLACKED…` 站内无货 ❌；有码 `SSIS` ❌ |

**站内番号形态**

- 规范键：`STUDIO.YYYY.MM.DD`（见 [region-code-formats.md](./region-code-formats.md)）  
- **AVHeat 识别码多为两位年** `STUDIO.YY.MM.DD`（如 `BrazzersExxtra.26.07.09`）  
- 已修：`western_code_candidates` + `code_equiv` YYYY↔YY；`aio_common` / `theporndb` 搜索均试双形态

**结论**

- **ThePornDB**：欧美主源（REST）；须填 API Key；厂牌别名见 `western-studio-search-aliases.json`。  
- **AVHeat**：AIO 欧美姊妹站；详情须 Flare；库存偏 RealityKings / Brazzers 子系列等，**不是 Blacked 全库镜像**；不当有码源。

实现：`scrape_details/theporndb.py`、`avheat.py` → `aio_common`；测试 `test_western_code_candidates.py`。

---

## 14. MissAV（`miss_av`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `miss_av`（别名 `missav`） |
| 显示名 | MissAV |
| 分组 | 综合（`general`） |
| 默认地址 | `https://missav123.com`（镜像 `missav.ws` / `.live` / `.ai` 等） |
| 访问 | `proxy_adaptive`（**非**强制 CF；curl+代理可过，**不算**删站条件的「真 Flare」） |
| 官网自称 | 「MissAV \| 免费高清AV在线看」 |

实现：`apps/api/app/scrape_details/miss_av.py`（`/cn/{slug}` 直链 → 搜索回退）。

### 官网实际有什么（2026-09 探针）

顶栏 / 分区（`/cn/`，多镜像同源）：

| 导航 | URL 形态 | 含义 |
|------|----------|------|
| **中文字幕** | `/cn/chinese-subtitle` | 中字拷贝 |
| **无码流出** | `/cn/uncensored-leak` | 流出/破解（选链降权） |
| **FC2** | `/cn/fc2` | FC2 专区 |
| **麻豆传媒** | `/cn/madou` | 国产麻豆向 |
| **女优 / 类型** | `/cn/actresses` `/cn/genres` | 附属 |
| **新作 / 热门** | `/cn/release` `/cn/today-hot` | 列表 |
| 详情 | `/cn/{slug}` | 小写连字符；FC2 为 `fc2-ppv-{id}` |

「素人 / 无码影片」部分入口为 `#` 占位，实际靠搜索与标签页。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | `SSIS` / `IPZZ` / `SONE-001` / `ABP` 通；短号库存弱（`SONE-15` 空） |
| **日本无码** | ★★★☆☆ | `HEYZO` 通；date6 须裸日期 slug（`062014_830`）；部分 Carib 样例空 |
| **日本素人** | ★★★★☆ | `LUXU` / `259LUXU` / `HMDN` 通（板号 `code_equiv`） |
| **FC2** | ★★★★★ | 专区；`fc2-ppv-{id}` 优先（裸 `fc2-{id}` 常 404） |
| **国产** | ★★★☆☆ | 麻豆栏目；`MDX-0001` 通；须防 `MDX-001` 日系错绑 |
| 欧美 | ☆☆☆☆☆ | 点分键无效 |

**一句话**：MissAV = **播放向综合库**（有码/素人/FC2 强，无码 date6 要剥品牌，国产可兜底）；海报降权，进无码/素人/国产默认链。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 · 无码 / 素人 | 含 `miss_av`（封面/标题兜底） |
| 默认丰富链 · 国产 | `… → madou → **miss_av**` |
| `SOURCE_TRUST` | 55 |
| `SOURCE_FIELD_BIAS` | title **+14**、tags **+22**、overview **+12**、poster **-8** |

### 网页 + scrape 实测

探针：`data/debug/miss_av_region_probe.txt`（禁 Flare 亦通）。

| 区 | 输入 | 结果 |
|----|------|------|
| 有码 | `SSIS-001` / `IPZZ-599` / `SONE-001` / `ABP-001` | ✅ |
| 有码 | `SONE-15` | ❌ 库存空（pad 候选已试） |
| 无码 | `HEYZO-2034` / `1PON-062014-830` | ✅（后者经 `062014_830`） |
| 无码 | `CARIB-011317-002` | ❌ 样例空 |
| 素人 | `LUXU-001` / `259LUXU-001` / `HMDN-332` | ✅ |
| FC2 | `FC2-976194` / `FC2-PPV-976194` | ✅ |
| 国产 | `MDX-0001` | ✅ 麻豆；拒日系 `MDX-001` |
| 国产 | `MDSR-0002` | ❌ |
| 欧美 | `BLACKED…` | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 候选 | `miss_av_code_candidates`：pad / 剥板号 / FC2-PPV / date6 裸 `YYMMDD_NNN` |
| 详情校验 | 页内「番号:」与候选 `code_equiv` **或** fold 全等（date6 裸页） |
| 国产 | `code_equiv` **禁止**国产前缀走剥零桶（`MDX-0001`≠`MDX-001`） |
| 流出后缀 | `-uncensored-leak` 等选链降权 |
| mosaic | URL/文案启发式，HEYZO 等可能标成「有码」——勿当权威分区 |

### 相关代码与文档

- `apps/api/app/scrape_details/miss_av.py`  
- 测试：`test_miss_av_code_candidates.py`  
- [region-code-formats.md](./region-code-formats.md) · [source-region-code-audit.md](./source-region-code-audit.md) § MissAV  

---

## 15. NJAV / 123AV（`njav`）

### 基本信息

| 项 | 内容 |
|----|------|
| 目录 id | `njav` |
| 显示名 | NJAV（现域 **123AV**） |
| 分组 | 综合（`general`） |
| 默认地址 | `https://123av.com/ja`（镜像 `njav.tv` 仍指向同站） |
| 访问 | `proxy_adaptive`（curl+代理可过，**非**强制 CF 过盾） |
| 官网自称 | 「123AV - 無料JAV・日本AVをHDでオンライン視聴」 |

实现：`apps/api/app/scrape_details/njav.py`（缓存 → `/v/{slug}` 直链 → 搜索）。

### 官网实际有什么（2026-09 探针）

日文顶栏：

| 导航 | URL | 含义 |
|------|-----|------|
| **検閲済み** | `/ja/censored` | 有码 |
| **無検閲** | `/ja/uncensored` | 无码 |
| **無検閲リーク** | `/ja/uncensored-leaked` | 流出（选链降权） |
| **FC2** | `/ja/makers/fc2` | FC2 maker |
| **ジャンル / 女優** | `/ja/genres` `/ja/actresses` | 附属 |
| 搜索 | `/ja/search?keyword=` | 关键词 |
| 详情 | `/ja/v/{slug}` | 小写连字符 |

无独立「国产 / 欧美」大区。

### 六区适合度（结论）

| 区 | 适合度 | 说明 |
|----|--------|------|
| **日本有码** | ★★★★☆ | `SSIS` / `IPZZ` / `SONE-001` / `ABP` 通；短号库存弱 |
| **日本无码** | ★★★☆☆ | `HEYZO` 通；样例 date6 空；有无码/流出栏 |
| **日本素人** | ★★★☆☆ | 站内多为**数字板号** slug（`328HMDN-332`）；须加板号候选；冷门 `LUXU-001` 可空 |
| **FC2** | ★★★★☆ | maker 专区；须 `fc2-ppv-{id}`（裸 `fc2-{id}` 404） |
| 国产 | ★☆☆☆☆ | **号碰撞**：`MDX-0001` 命中日系旧片，非麻豆；勿当国产源 |
| 欧美 | ☆☆☆☆☆ | 点分键无效 |

**一句话**：123AV = **日文播放综合库**（有码/无码/FC2）；素人靠板号直链；**不要**当国产 enrich。

### 本仓库怎么用它

| 用途 | 行为 |
|------|------|
| 默认丰富链 | **不含**（可手加；信任分一般） |
| `SOURCE_TRUST` | 55 |
| `SOURCE_FIELD_BIAS` | title **+6**、tags **+8**、poster **-10** |

### 网页 + scrape 实测

探针：`data/debug/njav_region_probe.txt`。

| 区 | 输入 | 结果 |
|----|------|------|
| 有码 | `SSIS-001` / `IPZZ-599` / `SONE-001` / `ABP-001` | ✅ |
| 有码 | `SONE-15` | ❌ |
| 无码 | `HEYZO-2034` | ✅ |
| 无码 | `1PON-062014-830` | ❌ |
| 素人 | `HMDN-332` | ✅（经 `328HMDN-332`） |
| 素人 | `LUXU-001` / `259LUXU-001` | ❌ 库存空（搜索勿模糊取错号） |
| FC2 | `FC2-976194` / `FC2-PPV-976194` | ✅ |
| 国产 | `MDX-0001` | ⚠ 通但为**日系**同号，非麻豆 |
| 欧美 | `BLACKED…` | ❌ |

### 番号与查找注意

| 规则 | 说明 |
|------|------|
| 候选 | `njav_code_candidates`：pad、素人**加**板号、无码 date6 裸日期、FC2-PPV |
| 流程 | 路径缓存 → `/v/{slug}` 多试 → 多关键词搜索 + `code_equiv` 挑链 |
| 流出后缀 | `-uncensored-leaked` 降权 |
| 国产 | 与日系共号时会命中日片；默认链不含本源 |

### 相关代码与文档

- `apps/api/app/scrape_details/njav.py`  
- 测试：`test_njav_code_candidates.py`  
- [source-region-code-audit.md](./source-region-code-audit.md) § NJAV  

---

## 修订记录

| 日期 | 变更 |
|------|------|
| 2026-09-23 | 建册；完成 JavBus（含官网导航与本地检索探针） |
| 2026-09-23 | 完成 DMM / FANZA（GraphQL 六区实测 + 分区说明） |
| 2026-09-23 | 完成 LibreDMM / LibreFanza（站点结构 + JSON 六区实测） |
| 2026-09-23 | 完成 AirAV.io（导航 + 搜索/刮削六区实测；原 wiki 已合并） |
| 2026-09-23 | 完成 Avmoo（AIO 三站壳/JS 导航还原；Flare 宕机故 scrape 命中表未复测） |
| 2026-09-23 | 完成 Jav321（导航/type 分区 + 六区 scrape；修 `code_equiv` 素人板号） |
| 2026-09-23 | **下线 JavLibrary**（CF/Flare 不通；目录与刮削实现已删） |
| 2026-09-23 | 完成 AVBase（导航 + `__NEXT_DATA__` 六区 scrape；`work_id` 改 `code_equiv`） |
| 2026-09-23 | 完成 MGStage（实站复测；`mgstage_code_candidates` 板号扩展） |
| 2026-09-23 | 完成 FreeJavBT（四分区导航 + 六区 scrape；剥素人板号候选） |
| 2026-09-23 | 完成 7MMTV（分区导航 + 六区 scrape；板号/`code_equiv` + FC2 裸 id 候选） |
| 2026-09-23 | 完成 iQQTV（分区导航 + 六区 scrape；剥板号/date6/FC2 候选 + 页校验） |
| 2026-09-23 | **下线 AVSex**（强制 CF/Flare 过盾；慢源，已从 catalog 与刮削实现移除） |
| 2026-09-23 | 完成 R18.dev（JSON API 六区 scrape；修空响应误匹配 + 板号候选） |
| 2026-09-23 | **下线 AVWikiDB**（CF JS 挑战；非 im-curl 可过，须 Flare，已从 catalog 与刮削实现移除） |
| 2026-09-23 | 无码 12 前缀专用站批量复测全通；FC2 官网可用 / fd2ppv 详情 403；AvSox 保留空壳 |
| 2026-09-23 | 国产批量：madou 全通；madouqu/小黄书 403；hscangku 部分可刮 |
| 2026-09-23 | 欧美：ThePornDB API 通；AVHeat Flare 可刮；修 `western_code_candidates` YYYY↔YY |
| 2026-09-23 | **下线 LuluBar**（综合组；从 catalog / scrape_details / 测试移除） |
| 2026-09-23 | JavDay 暂跳过；完成 MissAV（候选/date6/国产防错绑 + 六区实测） |
| 2026-09-23 | 补综合多类型遗漏：`airav_io` 多候选搜索；`njav`/`freejavbt`/`sevenmmtv` 加 date6 |
| 2026-09-23 | 完成 NJAV/123AV（FC2-PPV / 素人板号直链 + 六区实测） |
| 2026-09-23 | 增强：`jav321`/`avbase` 多候选；`aio` date6+pad；`libredmm`/`freejavbt` 加板号 |
| 2026-09-23 | 全局区源 v10：无码 `javbus→iqqtv→…→avsox`；FC2/欧美补兜底；前端 restore 对齐 |
| 2026-09-23 | 有码字段优先 v11：中文标题/简介/标签（AirAV·iQQTV 打头）；封面 FANZA 权威 |
