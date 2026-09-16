# 刮削管线优化总纲（对标 MDCX 优良逻辑）

> **目标**：在**小硬盘**前提下，让「番号 → 多源 → 合并 → 封面 → NFO → 入库 → 女优资产」稳定达到合格，而不是堆文件。  
> **对照**：MDCX（`.refs/mdcx`，主流程 `core/scraper` → `file_crawler` → `image`/`web` → `nfo`/`translate`）。不对比 MDCS。  
> **现状锚点**：`apps/api/app/scrap_library/enrich.py`、`cover_scrape.py`、`embed.py`、策略面板、E2E 标准 `docs/E2E_SCRAPE_STANDARD.md`。  
> **用法**：每节四段——MDCX 做法 → 我们现状 → 差距/风险 → 优化建议。实施时优先「合格率 + 省盘」，少开新资产类型。  
> **审计结论（2026-09-13）**：A–H 共 40 条是「库刮削合格 + 省盘」主干；**I 节（I41–I52，含 I46b）** 为审计后确认值得学习的补充规格。并非 MDCX 全功能镜像，也尚未全部落地。详见文末「深度审计」。

---

## 0. 先定论：裁切要不要 4 种？

### 0.1 现状（4 种）

| 模式 | 行为 | 典型分区默认 |
|---|---|---|
| `smart` | 智能裁剪：I45 比例先验 + 主脸选左/中/右；脸偏 → face | 有码 / 写真 |
| `right` | 横封右侧约 47% 再按比例居中 | （旧默认；现被 smart 覆盖） |
| `face` | OpenCV 主脸锚点裁 | 素人 / FC2 |
| `none` | 不裁 | 无码 / 国产 / 欧美 |

另有比例开关：`full`（2.12/3）/ `emby`（2/3），与裁切模式正交，**不要并进裁切枚举**。

### 0.2 结论：可以合并，推荐对外 3 种

**`right` 不应再作为一等公民暴露给用户。**

理由：

1. **`smart` 已包含侧裁**：按比例与主脸选左/中/右，仅在脸偏时才 face。纯 `right` =「禁用纠偏的残缺 smart」，日常合格率更差（大量 `face_off`）。
2. **有码碟封经验已沉进 `smart`**，不再需要单独「右侧裁剪」按钮。
3. **`face` 仍独立有价值**：素人/FC2 构图乱，侧裁先验可能错误；若强行并进 `smart`，会先裁错再纠，浪费且偶发失败。
4. **`none` 必须保留**：横图本就是成品（无码/欧美），裁成竖海报反而毁信息。

**推荐用户可见枚举：**

```text
smart  — 智能裁剪（左/中/右 + 人脸纠偏；有码/写真默认）
face   — 仅人脸（素人/FC2 默认）
none   — 不裁（无码/国产/欧美默认）
```

实现层可继续保留 `_crop_left` / `_crop_right` / `_crop_center` 私有函数；设置 UI / API / `COVER_CROP_MODES` 去掉 `right`；旧配置 `right` → 迁移为 `smart`（与现 `coverLogicVersion: 4` 同一思路）。

### 0.3 更激进可选：对外只留 2 种

| 模式 | 含义 |
|---|---|
| `auto` | 按分区走默认表（内部仍是 smart/face/none） |
| `none` | 强制不裁 |

适合「几乎不调参」用户；调试与分区差异仍建议保留 3 种。

### 0.4 不建议并成 1 种

全库统一 smart 会误伤无码横图；统一 none 会让有码列表/详情脸偏。分区默认 + 少量模式是正解。

---

## A. 管线骨架与模式

### A1. 端到端阶段划分

| | |
|---|---|
| **MDCX** | 解析番号 → 多站爬虫 → 字段合并（FileScraper）→ thumb/poster/fanart/剧照/预告 → NFO → 重命名/移动。阶段日志清晰。 |
| **我们** | 骨架/checkpoint → 并发拉源 → identity gate → `_merge_got` →（可选 LLM）→ 下封面 `process_cover_bytes` → 写 NFO + `poster.jpg` → embed → 女优资料/头像。 |
| **差距** | 我们对「媒体资产」极简（正确）；阶段日志与 MDCX 的「thumb→cut→poster」粒度还可对齐，便于 E2E。 |
| **建议** | 固定日志阶段名：`parse / gate / merge / cover.pick / cover.download / cover.crop / nfo / embed / actress`。不增加资产类型。 |

### A2. 运行模式

| | |
|---|---|
| **MDCX** | 全量刮削、失败重刮、按配置跳过已有字段/图。 |
| **我们** | `incremental` / `overwrite`（策略面板）；checkpoint 续跑；E2E `reuse-merge`。 |
| **差距** | 字段级「只补空」与「强制重下封面」边界偶发不清（坏图被 keep）。 |
| **建议** | 显式三档：`fill_empty` / `refresh_weak`（薄标题、空剧情、坏封面）/ `overwrite_all`。坏封面判定走 `analyze_local_poster`。 |

### A3. 成功/失败收口

| | |
|---|---|
| **MDCX** | 有标题+封面等即可继续；单站失败不整单失败。 |
| **我们** | 区分 miss / fail / invalid_skeleton；身份门禁可清空字段仍保留封面 URL。 |
| **差距** | 「合格」尚未产品化成可配置分数卡。 |
| **建议** | 对齐 E2E 八大块成 `quality_gate`：硬失败（错人、空标题、无可用封面）vs 软提示（未映射中文名）。 |

### A4. 同番号复用

| | |
|---|---|
| **MDCX** | CD1/CD2 等共享刮削结果；本地缓存。 |
| **我们** | 按 code 目录；checkpoint；E2E 默认只拉一遍源。 |
| **差距** | 多盘分集、同号重刮缓存键可再清晰。 |
| **建议** | 缓存键 = `code + strategy_hash`；分集只换文件名不重拉元数据。 |

---

## B. 番号与路由

### B5. 番号识别与规范化

| | |
|---|---|
| **MDCX** | `base/number.py` 强：前缀、FC2、欧美好多种形态。 |
| **我们** | maker/prefix 目录 + maps；骨架号过滤。 |
| **差距** | 边缘形态仍靠 maps/前缀表。 |
| **建议** | 继续以 maps 为权威；MDCX 规则只作「漏检补丁」，不整文件移植。 |

### B6. 分区 / 马赛克路由

| | |
|---|---|
| **MDCX** | 有码/无码/素人/FC2 等影响网站列表与图策略。 |
| **我们** | 七区 + `regionCrop` + 源启用分组。 |
| **差距** | 路由与封面默认已较好；源集合与分区偶有交叉误开。 |
| **建议** | 分区 → 默认源集 + 默认裁切（3 种）写死表；面板只允许微调。 |

### B7. 单源强制 vs 多源字段链

| | |
|---|---|
| **MDCX** | 可指定网站；字段级 website 优先级。 |
| **我们** | 字段级 `field_priority_chain` + trust 分。 |
| **差距** | 我们在质量分/门禁上更强；MDCX 配置面更直观。 |
| **建议** | 保持字段链；设置页展示「该字段实际赢家」便于调优。 |

### B8. 路径辅助判定

| | |
|---|---|
| **MDCX** | 文件夹名可暗示类型。 |
| **我们** | 主要靠 catalog region，不依赖视频路径。 |
| **差距** | 库模式本就不绑视频路径——可忽略。 |
| **建议** | 不引入路径启发式，避免脏目录名污染。 |

---

## C. 多源抓取

### C9. 源启用与分组

| | |
|---|---|
| **MDCX** | 大量 crawlers；可按类型开关。 |
| **我们** | 策略面板启用源；E2E 只测已启用。 |
| **差距** | 可控性已够。 |
| **建议** | 维持；新增源必须挂字段 trust + identity 样本。 |

### C10. 并发与超时

| | |
|---|---|
| **MDCX** | 线程/异步混合，可配。 |
| **我们** | `adaptiveWorkers`；单 URL 超时换源。 |
| **差距** | 封面下载链偶发串行过长（已修部分 DMM→javbus 回落）。 |
| **建议** | 封面：首个「非空、够高」即停；元数据：墙钟上限保 checkpoint。 |

### C11. 失败分类

| | |
|---|---|
| **MDCX** | 日志级区分。 |
| **我们** | miss ≠ fail；老片预期失败。 |
| **差距** | 小。 |
| **建议** | 封面失败单独记 `cover_fail`（与 parse miss 分开），便于批量修图。 |

### C12. 详情页可用性门禁

| | |
|---|---|
| **MDCX** | 依赖爬虫返回完整性。 |
| **我们** | identity gate：错页清空文本字段，封面 URL 可留。 |
| **差距** | 我们更细；仍有漏网（促销 overview、中文咖啡馆错绑等，已部分修）。 |
| **建议** | 门禁规则继续案例驱动进 E2E 标准，不回退成「整源丢弃」。 |

---

## D. 字段合并（质量核心）

### D13. 字段级站点优先级

| | |
|---|---|
| **MDCX** | FileScraper：每字段按网站优先级取第一个有效值。 |
| **我们** | 优先级链 + `_score_*`；低分相对最优差 35 跳过。 |
| **差距** | 我们已超 MDCX「首个非空」；需防止分数与链冲突难理解。 |
| **建议** | 文档化「链决定候选序，分决定否决」；面板只读展示。 |

### D14. 身份门禁

| | |
|---|---|
| **MDCX** | 较弱（主要靠网站对错）。 |
| **我们** | 强：错页文本剔除、封面可贡献。 |
| **差距** | 优势项。 |
| **建议** | 保持；新源接入必须带错页样本。 |

### D15. 标题合格

| | |
|---|---|
| **MDCX** | 翻译模块可选；质量启发式较少。 |
| **我们** | thin title、垃圾标题、机翻回退、标题尾女优偏好。 |
| **差距** | 优势项。 |
| **建议** | `refresh_weak` 专门重拉 thin_title。 |

### D16. 剧情合格

| | |
|---|---|
| **MDCX** | 多取第一有效。 |
| **我们** | 广告壳、≈标题惩罚、外文女优串戏惩罚。 |
| **差距** | 优势项。 |
| **建议** | 继续；LLM 只译已校验 `overviewJa`。 |

### D17. 女优合格

| | |
|---|---|
| **MDCX** | 列表合并较简单。 |
| **我们** | identity key、共识投票、别名收敛、人数标尺、软策略不强制中文映射。 |
| **差距** | 优势项；映射表链禁止多跳。 |
| **建议** | 维持 E2E 铁律；批量审计脚本留在 `_gap_reports`。 |

### D18. 标签合格

| | |
|---|---|
| **MDCX** | 映射/翻译。 |
| **我们** | maps + variant-fold + 噪声剔除。 |
| **差距** | 需持续洗表。 |
| **建议** | 刮削时硬 drop 噪声；映射治理与管线分离。 |

### D19. 片商 / 系列 / 日期 / 评分

| | |
|---|---|
| **MDCX** | 官方站优先。 |
| **我们** | 字段链官方前置。 |
| **差距** | 小。 |
| **建议** | studio 显示名继续走 makers maps。 |

### D20. 本地映射兜底

| | |
|---|---|
| **MDCX** | 本地库/历史。 |
| **我们** | `code-titles` / `code-actors` / makers。 |
| **差距** | 兜底顺序要明确「源优先还是本地优先」。 |
| **建议** | 默认：合格源 > 本地映射；仅 thin/空时本地补。 |

### D21. LLM / 翻译边界

| | |
|---|---|
| **MDCX** | 独立 translate 流程。 |
| **我们** | 策略开关；禁对错页/垃圾日文二次译。 |
| **差距** | 小。 |
| **建议** | LLM 永不写女优身份；只动 title/overview 文本。 |

---

## E. 封面与媒体（含省盘）

### E22. URL 策略（pl / ps）

| | |
|---|---|
| **MDCX** | thumb≈`pl`（大横图）；poster 候选常含 `ps`；不够则从 thumb 裁。另可囤 fanart=thumb。 |
| **我们** | `_poster_rank` 偏 pl；`rewrite_cover_url_for_quality` high 时 ps→pl；最终只存一张 `poster.jpg`。 |
| **差距** | 曾误用矮 `ps` 落盘成 147×200；「高画质」语义混了「源分辨率」与「JPEG 压缩」。 |
| **建议** | **下载择优规则（固定）**：① 官方竖图 `ps` 仅当短边≥约定阈值（如 ≥400）才直接用且可 `none`/轻裁；② 否则必须 `pl`（或同等大横图）+ 裁切；③ 过小 ps **直接丢弃**，禁止写入。与 UI `quality high/low` 解耦：high/low 只控压缩与最长边。 |

### E23. 高清增强（Amazon / Google / 官网）

| | |
|---|---|
| **MDCX** | 可选 HD 搜索，体积与耗时都大。 |
| **我们** | 未做。 |
| **差距** | 省盘场景 **默认不做**。 |
| **建议** | 仅「人工补图 / 单号强制」入口；永不进批量 E2E。 |

### E24. 裁切策略（见 §0）

| | |
|---|---|
| **MDCX** | 从 thumb 右裁出 poster（有码惯例）；少有 face 纠偏。 |
| **我们** | smart/right/face/none + 人脸偏离检测。 |
| **差距** | 我们纠偏更强；模式过多。 |
| **建议** | **合并为 3 种对外**（§0.2）；比例 `full/emby` 独立。展示层 `object-position: center`，禁止裁完 CSS 再右偏。 |

### E25. 高度 / 分辨率择优

| | |
|---|---|
| **MDCX** | 大 thumb 再裁，海报通常够高。 |
| **我们** | 曾被小 ps 坑。 |
| **差距** | 缺「下载后最小边」硬门禁。 |
| **建议** | `min_short_edge`（建议 400～480）；不达标换下一候选；全部失败则 keep 旧图。 |

### E26. 空图 / 坏图

| | |
|---|---|
| **MDCX** | 有 NOW PRINTING 等处理。 |
| **我们** | blank 像素检测 + `analyze_local_poster`（blank/landscape/face_off）。 |
| **差距** | 批量修图失败率仍高（432 fail）——多因源图策略。 |
| **建议** | 修图脚本强制 pl 候选；失败分类：`too_small` / `blank` / `download` / `opencv`。 |

### E27. 落盘文件集（省盘关键）

| | |
|---|---|
| **MDCX** | thumb + poster + fanart + extrafanart（可选 trailer）——**磁盘重**。 |
| **我们** | 仅 `{code}.nfo` + `poster.jpg`（+ 女优头像另树）。 |
| **差距** | **我们更符合小硬盘**；不要向 MDCX 看齐多文件。 |
| **建议** | 政策冻结：禁止默认落 thumb/fanart。需要横图时运行时从 poster 不回切；列表用服务端缩略（已有 JPEG q≈78）。 |

### E28. 压缩与尺寸上限

| | |
|---|---|
| **MDCX** | 偏原图质量。 |
| **我们** | high: q90 + `subsampling=0`；low: 最长边 960、q72。 |
| **差距** | high 对海报偏奢侈；`subsampling=0` 体积大。 |
| **建议** | 新增默认档 **`compact`（推荐省盘默认）**：最长边 720～800、JPEG q 78～82、`subsampling=2`(4:2:0)、`optimize=True`。`high` 留给极少数收藏。批量 `recompress_posters` 只改体积不改构图。 |

### E29. 失败保留旧图

| | |
|---|---|
| **MDCX** | 常见「失败不覆盖」。 |
| **我们** | 部分路径会写坏图；需统一。 |
| **差距** | 中等。 |
| **建议** | 写盘事务：`poster.jpg.part` → 校验（非 blank、短边、可选 face）→ replace；失败删 part，保留旧文件。 |

### E30. 女优头像体积

| | |
|---|---|
| **MDCX** | 另有演员图逻辑。 |
| **我们** | actress avatar 独立。 |
| **差距** | 应单独 compact，勿用封面 high。 |
| **建议** | 头像最长边 ≤512、q≈80。 |

---

## F. NFO / 入库 / 展示

### F31. NFO 完整度与增量写

| | |
|---|---|
| **MDCX** | 字段齐全；可按开关写。 |
| **我们** | 分行易读 NFO；incremental 补空。 |
| **差距** | weak 字段刷新策略要产品化（见 A2）。 |
| **建议** | NFO 与 poster 事务尽量同成功同失败。 |

### F32. 向量重嵌入

| | |
|---|---|
| **MDCX** | 无对等（面向本地媒体库）。 |
| **我们** | embed 依赖 NFO 文本。 |
| **差距** | 仅改封面不应强制重嵌；改标题/女优/标签应重嵌。 |
| **建议** | 触发条件按字段脏标记。 |

### F33. 展示层二次偏移

| | |
|---|---|
| **MDCX** | 本地播放器读成品图。 |
| **我们** | 曾 CSS `object-position: right` 叠加右裁。 |
| **差距** | 已改为 center。 |
| **建议** | 回归：列表/拼贴/详情一律 center；服务端 `rp=1` 裁切与入库裁切参数一致。 |

---

## G. 合格验收与治理

### G34. 单条 checklist / 分数卡

对齐 E2E 八大块：解析、合并、映射、标签、封面、NFO、embed、女优资产。输出 `hard_fail[]` / `soft[]`。

### G35. 库级审计

已有：`analyze_local_poster`、actress 审计、library quality。固化为定期任务：thin_title、空剧情、face_off、短边过小、JPEG 过大。

### G36. 批量修复

| 类型 | 策略 |
|---|---|
| 脸偏 | 本地重跑 smart（有 pl 源图时）或强制 pl 重下 |
| 过小图 | 强制 pl + 裁切 |
| 体积过大 | 仅 recompress compact |
| 薄标题 | `refresh_weak` 重合并 |

### G37. 配置版本与迁移

继续 `coverLogicVersion`：v3 建议 = 去掉对外 `right` + 引入 `compact` 默认 + `min_short_edge`。

---

## H. 运维与稳定性

### H38. 代理 / Cookie / 过盾

学 MDCX 的可配性；批量任务必须可中断、可续跑。

### H39. 限速与退避

封面 CDN 限速单独于元数据；429/超时换镜像，不死磕。

### H40. 可观测性

阶段日志 + E2E 报告字段 `cover: {url, w, h, crop, bytes, issues}`。

---

## I. 值得学习的补充方面（择优吸收）

> 源自对 MDCX 的深度审计：质量相关、且符合「库刮削 + 小硬盘」的逻辑。不移植重命名/多图/烧角标/Emby/默认 Amazon。

### I41. 字段级语言偏好

| | |
|---|---|
| **MDCX** | `FieldConfig`：每字段可配 `site_priority` + `language` + `translate`。若 `translate=true` 取首源再译；否则必须命中指定语言，否则该字段失败。 |
| **我们** | 标题/剧情用中文池优先 + 质量分 + LLM 门禁；**未**产品化为「每字段语言策略」。 |
| **差距** | 调参靠代码启发式，面板看不到「该字段要中文还是官日」。 |
| **建议** | 策略增加 `fieldLanguage: { title, overview, … }`：`prefer_zh`（默认）/ `prefer_ja` / `zh_or_translate`。与现有中文池、`llmTranslateOnJunk` 共用，不另起合并引擎。 |

### I42. actors 与 all_actors 分离

| | |
|---|---|
| **MDCX** | `actors`（展示/刮削主列表）与 `all_actors`（尽力收集的全员）；后者可写 NFO `actor_all`。 |
| **我们** | 合并后单一 `actors` 列表；人数以身份去重为准。 |
| **差距** | 大乱交等「栏里很多人、标题只点名几个」时，展示与检索需求不同。 |
| **建议** | 合并产出 `actors`（共识主演，墙面/卡片）+ `actorsAll`（全源并集去重，详情可展开）。合格判定仍看 `actors`；`actorsAll` 不阻断。E2E：主演人数跟标题标尺，全员允许更大。 |

### I43. 标题后处理规则（与尾名偏好互斥）

| | |
|---|---|
| **MDCX** | `FieldRule.DEL_ACTOR`：按演员别名表剥离标题尾名；`DEL_NUM`：去标题番号前缀；`DEL_CHAR`：演员名去括号。 |
| **我们** | 标题尾女优用于**补演员**；清洗半截括号等。缺少可配的「写回标题时是否剥尾名」。 |
| **差距** | 两种目标相反：MDCX 要干净标题；我们有时靠尾名救演员。混用会互相拆台。 |
| **建议** | 显式两阶段：① merge 前可用尾名补演员；② 定稿后可选 `stripTitleActorSuffix` / `stripTitleCodePrefix`（默认关或仅中文长标题开）。`DEL_CHAR` 并入现有 `_clean_actors`。 |

### I44. FC2 卖家规则

| | |
|---|---|
| **MDCX** | `FieldRule.FC2_SELLER`：FC2 可用卖家名填充演员位。 |
| **我们** | FC2 区路由与裁切有；卖家→演员未产品化。 |
| **差距** | 大量 FC2 无女优名，只靠卖家可检索。 |
| **建议** | 仅 `region=fc2`：无合格女优时，用卖家写入 `actors`（标记 `actorRole=seller`）或单独 `seller` 字段；**禁止**把卖家并进日本有码女优身份表。 |

### I45. 比例先验自动裁切

| | |
|---|---|
| **MDCX** | `cut_thumb_to_poster`：未指定 cut 时，`h/w≥1.4` → 不裁；`≥1` → 中裁；否则右裁。另有少数固定分辨率特判（脆，不学）。 |
| **我们** | 按**分区**默认 smart/face/none；不看单张图比例。 |
| **差距** | 有码区偶发已是竖图仍走右裁；无码区偶发横封人物偏也从不裁。 |
| **建议** | 作为 `auto`/`smart` 的前置：竖图（prop≥1.4）直接 `none` 或仅居中；横图按主脸选左/中/右。固定像素表不移植。对外仍建议 3 种：`smart` / `face` / `none`（`auto`=分区默认+比例先验）。 |

### I46. 官网升清（非 Amazon/Google）

| | |
|---|---|
| **MDCX** | `HDPicSource`：poster/thumb/Amazon/official/Google；`_get_big_thumb/_get_big_poster` 多路升清。 |
| **我们** | CDN 内 pl/ps 改写；无官网/Amazon/Google。 |
| **差距** | 老片 CDN 只剩小图时无退路；Amazon/Google 贵且不稳。 |
| **建议** | 可选 `coverEnhance: off | official`（默认 off）。仅在短边不达标时试官方站大图；**禁止**默认 Amazon/Google。与 E22 `min_short_edge`、E29 keep 旧图联动。 |

### I46b. 全源封面候选保序试下（thumb_list）

| | |
|---|---|
| **MDCX** | 字段赢家之外，**所有来源**的 thumb URL 进 `thumb_list`，下载时按序尝试直到 `check_pic` 通过。 |
| **我们** | `posterCandidates` 有合并，但下载链偶发未「校验通过即停」或过早锁死矮 ps。 |
| **差距** | 中等；与 E22/E25/E29 直接相关。 |
| **建议** | 固定流程：合并保序候选（官方 CDN 前置）→ 逐个下载 → blank/短边校验 → 裁切 → 成功即停；失败保留旧 `poster.jpg`。写入 E2E `cover.tried[]`。 |

### I47. 角标策略（UI badge，不烧图）

| | |
|---|---|
| **MDCX** | `add_mark` 把字幕/有码/破解/流出/无码/HD **烧进** poster/thumb。 |
| **我们** | 无烧图；分区本身表达有码/无码。 |
| **差距** | 中字/破解/HD 等信号若只有烧图会毁省盘图库，且无法撤销。 |
| **建议** | **学信号、不学烧图**。NFO/库字段存 `badges[]`（`cnsub`/`leak`/`uncensored`/`hd`…），列表/详情用 CSS badge。永远不修改 `poster.jpg` 像素加角标。 |

### I48. 双语标题 / 剧情展示

| | |
|---|---|
| **MDCX** | `OutlineShow`：可显示来源、中日并排或日中并排。 |
| **我们** | 常存 `titleJa` / `overviewJa`；展示多为单语定稿。 |
| **差距** | 机翻中文可对照日文官名验毒；详情页少一键对照。 |
| **建议** | 详情：定稿标题下可展开「日文原题/原剧情」；设置 `outlineShow: zh | zh_jp | jp_zh`。列表仍只显示定稿，省空间。 |

### I49. 字段级重刮档（对齐 ReadMode / Whole / None）

| | |
|---|---|
| **MDCX** | `ReadMode`（有 NFO 更新 / 无 NFO 刮 / 再下图 / 只更 NFO）；`WholeField`（有值也重刮）；`NoneField`（仅空补）。 |
| **我们** | 粗粒度 `incremental` / `overwrite`。 |
| **差距** | 无法「只重封面」「只补剧情」「薄标题才重合并」。 |
| **建议** | 产品化三档 + 字段掩码：`fill_empty`（=NoneField）/ `refresh_weak`（thin_title、空剧情、坏封面、脸偏）/ `overwrite`；高级可选 `forceFields: ['poster','overview',…]`（=WholeField）。与 A2、G36 同一套。 |

### I50. 字幕 / 清晰度 / 马赛克 facet（不注入标签）

| | |
|---|---|
| **MDCX** | `TagInclude` 可把演员/系列/片商/cnword/mosaic/definition **写入 tag**。 |
| **我们** | 标签去噪严格；演员/片商进 tag 视为污染。 |
| **差距** | 中字/4K/破解仍有检索价值，但塞进 genre 会脏。 |
| **建议** | **不学注入 tag**。独立可选字段或 facet：`cnsub` / `definition` / `mosaic`；来源优先元数据，其次标题/磁链弱信号。过滤 UI 用 facet，不进 `tags[]`。 |

### I51. 女优头像源策略（对标 GFriends 思路）

| | |
|---|---|
| **MDCX** | GFriends / 本地演员库 / 网络图；Emby 补照片（Emby 写回不学）。 |
| **我们** | `actress_avatar` / bio 多源；体积与超时仍是痛点。 |
| **差距** | 缺清晰「源优先级 + 命中缓存 + 失败短路 + compact」。 |
| **建议** | 固定链：本地缓存 → 可信头像库（若引入 GFriends 类索引）→ 站点资料页；最长边≤512、q≈80；单人总超时上限；E2E step6 可跳过。禁止为头像拉 Amazon。 |

### I52. runtime / director / score（有则写，不阻断）

| | |
|---|---|
| **MDCX** | NFO 常规字段；可进 Whole/None 控制。 |
| **我们** | 合并与 NFO 偏 title/actors/overview/studio/date/tags/poster；director/runtime/score 弱。 |
| **差距** | 详情信息量略少；不影响「合格」主链路。 |
| **建议** | 字段链官方源优先写入；空不失败、不重试轰炸。不进硬门禁；质量卡仅 soft。 |

---

## 实施进度（代码落地）

| 优先级 | 项 | 状态 | 说明 |
|---|---|---|---|
| P1 | 裁切合并（去 `right`）+ I45 比例先验 | **已完成** | 对外仅 smart/face/none；`right`→smart；竖图/近方图先验；`coverLogicVersion: 3` |
| P2 | 下载门禁 + I46b | **已完成** | `minShortEdge`(默认400)、弃过小 ps、候选保序试下、失败 keep 旧图 |
| P3 | 省盘 `compact` | **已完成** | 默认画质 compact（边~780 / q80 / 4:2:0）；保留 high/low |
| P4 | I49 `refresh_weak` | **已完成** | fillMode 三档；缺口队列 + 强制写回 |
| P5 | I41 + I43 | **已完成** | `fieldLanguage`；`stripTitleActorSuffix` / `stripTitleCodePrefix`（默认关） |
| P6 | I42 / I44 / I52 | **已完成** | `actorsAll`；FC2 `seller`；`director`/`runtime`/`score` 写入 NFO |
| P7 | I47 / I48 / I50 | **已完成** | `badges[]` + `cnsub`/`definition`/`mosaic` 独立字段；`outlineShow` 策略；不烧图、不脏 genre |
| P8 | I46 official / I51 | **已完成** | `coverEnhance: off\|official`；头像落盘最长边 512 / q80 |
| P9 | G34 质量门禁 API | **已完成** | `GET /scrap-library/embed/quality/gate` |
| P10 | 批量 recompress + 设置细控件 + 详情双语 | **已完成** | 策略面板：语言/剥标题/升清/双语/FC2；`POST …/posters/recompress`；详情 `outlineShow` |
| P11 | facet UI + 门禁入口 + forceFields + 矩阵同步 | **已完成** | 详情/海报角标；库内 signal 筛选；设置抽检门禁；增量 `forceFields`；附录矩阵改为已落地 |

---

## 实施优先级（建议顺序）

1. ~~**裁切合并**~~ **已完成**  
2. ~~**下载门禁 + I46b**~~ **已完成**  
3. ~~**省盘 compact**~~ **已完成**（含批量 recompress）  
4. ~~**`refresh_weak` / I49**~~ **已完成**  
5. ~~**I41 + I43**~~ **已完成**  
6. ~~**I42 / I44 / I52**~~ **已完成**  
7. ~~**I47 / I48 / I50**~~ **已完成**  
8. ~~**I46 official / I51**~~ **已完成**  
9. ~~**质量门禁 API（G34）**~~ **已完成**  
10. ~~**设置细控件 + 详情双语**~~ **已完成**  
11. ~~**facet UI / 门禁入口 / forceFields**~~ **已完成**  
12. **永不做**：默认 thumb+fanart+剧照；默认 Amazon/Google HD；角标烧进 poster；Emby 写回。

---

## 与现有文档关系

| 文档 | 关系 |
|---|---|
| `docs/E2E_SCRAPE_STANDARD.md` | 单号合格操作手册与案例账 |
| **本文** | 架构级对标 MDCX 的优化总纲与取舍（A–H 主干 + I 择优补充） |
| `docs/scrape-maps.md` | 映射表治理 |

---

## 附录：推荐默认表（裁切 3 种后）

| 分区 | crop | 说明 |
|---|---|---|
| japan_censored | smart | 碟封右主视觉 + 纠偏；竖图可由 I45 改 none |
| japan_gravure | smart | 同有码 |
| japan_amateur | face | 构图乱 |
| fc2 | face | 同素人；女优空时见 I44 |
| japan_uncensored | none | 横图成品 |
| china | none | 横图成品 |
| western | none | 横图成品 |

比例默认 `full`（2.12/3）；压缩默认 `compact`；落盘仅 `poster.jpg`。

---

## 深度审计：方面表是否「覆盖 / 吸收」MDCX 全部优良逻辑？

### 总判决

| 问题 | 答案 |
|---|---|
| 方面表是否包含与 MDCX 对比的**所有方面**？ | **否。** A–H 覆盖元数据/封面主链；I 节补值得学习的缺口；大量「视频文件管家」能力刻意不进表。 |
| 是否已**吸收** MDCX 所有优秀逻辑？ | **否（也不该 100%）。** 质量主链与 I 节择优项已落地；视频管家/多图/烧角标等刻意不移植。 |
| 是否应该追求 100% 移植？ | **否。** 优秀逻辑要**择优吸收**（见 I 节），不是镜像。 |

对照源：`.refs/mdcx/mdcx/core/{scraper,file_crawler,image,web,nfo,translate,utils}.py`、`base/{image,web,number,file}.py`、`config/{enums,models}.py`。

### 按 MDCX 模块：覆盖矩阵

图例：✅ 已较好覆盖/超越 · 🟡 有提及但浅或未落地 · 📌 已写入 I 节 · 🚫 产品形态应跳过

#### 1) `FileScraper` / 字段聚合

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| 每字段 `site_priority` | D13 | ✅ |
| 字段级 language + translate | I41 | ✅ |
| 全源 `thumb_list` 保序试下 | I46b / E22 | ✅ |
| `actor_amazon` 供搜图 | E23 | 🚫 默认 |
| `actors` vs `all_actors` | I42 | ✅ |
| `originaltitle` / 年从 release | D15/D19 | ✅ |
| 单站强制爬取 | B7 | ✅ |

#### 2) `deal_some_field` / `FieldRule`

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| `DEL_ACTOR` / `DEL_NUM` | I43 | ✅ |
| `DEL_CHAR` | I43 / D17 | ✅ |
| `FC2_SELLER` | I44 | ✅ |

#### 3) 封面 `web.py` + `cut_thumb_to_poster`

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| thumb→右/中/不裁 | E24 / §0 | ✅（我们有人脸） |
| 比例先验自动 cut | I45 | ✅ |
| 固定分辨率特判 | — | 🚫 |
| q95 + subsampling=0 | E28 | ✅→改 compact |
| `check_pic` 成功门禁 | E26/E29/I46b | ✅ |
| 官网升清 | I46 | ✅ |
| Amazon/Google HD | E23 | 🚫 默认 |
| 失败不覆盖 | E29 | ✅ |
| fanart/extrafanart/trailer | E27 | 🚫 |
| `add_mark` 烧图 | I47 | ✅ 学信号不烧图 |

#### 4) 翻译

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| 多翻译引擎 | D21 | ✅ |
| 演员/标签映射 | D17/D18/D20 | ✅ |
| 双语 outline 展示 | I48 | ✅ |

#### 5) NFO / ReadMode / Whole·None

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| NfoInclude 大全 | F31 / I52 | ✅ 次要字段 |
| ReadMode / Whole / None | I49 / A2 | ✅ fillMode + forceFields |

#### 6) `TagInclude`

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| 注入 tag | D18 | 🚫 默认 |
| cnword/mosaic/definition 信号 | I50 | ✅ 独立 facet + 筛选 |

#### 7) 演员图 / Emby

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| GFriends 等头像源 | I51 / E30 | ✅ 压缩落盘 |
| Emby 写回 | — | 🚫 |

#### 8) 视频文件管家

| MDCX 逻辑 | 状态 |
|---|---|
| 重命名/软链/网盘/清垃圾/预告主题视频 | 🚫 |
| 文件名 4K/中字弱信号 | I50 可选 |
| `cd_part` | A4 浅 |
| runtime 来自视频 | 无视频则跳过；源站 runtime → I52 |

#### 9) 运维 / 桌面

| MDCX 逻辑 | 映射 | 状态 |
|---|---|---|
| remain/again_search/success_list | A2/H | 🟡 |
| proxy/cookie/镜像 | H38 | 🟡 |
| 定时刮削、Qt UI | 🚫 |

### 我们已超越 MDCX（不必「吸收」回去）

1. **身份门禁**（错页清文本、封面可留）  
2. **标题/剧情质量分**（thin、机翻垃圾、串戏惩罚）  
3. **女优身份共识 + 别名收敛铁律**  
4. **智能裁剪（左/中/右 + 人脸纠偏）**（MDCX 仅 right/center/no；我们用主脸补 left）  
5. **miss≠fail / invalid_skeleton** 统计口径  
6. **单海报 + 省盘** 产品策略（MDCX 多图是反面教材）

### 「吸收进度」粗估（质量相关子集）

| 桶 | 约占质量相关逻辑 | 我们状态 |
|---|---|---|
| 已对齐或超越 | ~55% | 字段链+门禁+女优+裁切+省盘+I 节择优 |
| 文档已写、**本轮代码已落地**（P1–P11） | ~20% | 含 facet UI / forceFields / 门禁入口 |
| 运维浅层 / 可选增强 | ~5% | proxy 镜像、定时、可观测细节 |
| 明确不移植 | ~20% | 多图/预告/烧角标/重命名软链/Emby/Amazon 默认 |

### 一句话

**A–H 是库刮削优化主干；I 节是审计后确认「值得学习」的补充规格。**  
验收吸收度看矩阵与 I 节落地情况，而不是 MDCX 功能完成度。
