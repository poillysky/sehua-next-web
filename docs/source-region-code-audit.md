# 数据源 × 六区 × 番号匹配审计

按 `SOURCE_CATALOG` **从上往下、一次一站**核对：

1. 该站适合收集 / 丰富哪些区（**先看官网**，详解见 [source-site-guides.md](./source-site-guides.md)）  
2. 这些区的番号规则能否对上（避免查不到）——**输入形态见 [region-code-formats.md](./region-code-formats.md)**  
3. **发现问题立刻修**，再进入下一站（需人工说「开始下一个」）

六区：`japan_censored`（有码）· `japan_uncensored`（无码）· `japan_amateur`（素人）· `fc2` · `china`（国产）· `western`（欧美）。

权威映射参考：`apps/api/scripts/sync_prefixes_from_authority_sites.py`  
默认丰富链：`apps/api/app/scrap_library/enrich_strategy.py`（`_DEFAULT_REGION_SOURCES`）  
货架：`apps/api/app/makers/catalog_routes.py`（`KIND_SHELVES`）  
目录顺序：`apps/api/app/scrape/source_catalog.py`

---

## 进度总表

| # | id | 标签 | 状态 | 适合区（结论） |
|---|-----|------|------|----------------|
| 1 | `javbus` | JavBus | ✅ 已审已修 | 有码、无码 |
| 2 | `dmm` | DMM | ✅ 已审已修 | **仅有码** |
| 3 | `libredmm` | LibreDMM | ✅ 已审已修 | 有码、素人 |
| 4 | `airav_io` | AirAV.io | ✅ 站点详解已写 | 有码中文补全；无码/FC2 默认链；素人弱；国产/欧美不适合 |
| 5 | `avmoo` | Avmoo | ✅ 站点详解已写 | **仅有码向**（AIO jav）；默认 enrich 不挂；无码→`avsox`，欧美→`avheat` |
| 6 | `jav321` | Jav321 | ✅ 已审已修 | **有码、素人**；无码栏目弱；FC2/国产/欧美不适合 |
| — | `javlibrary` | JavLibrary | ❌ **已下线** | CF/Flare 不通，从 catalog 与 `scrape_details` 移除 |
| 7 | `avbase` | AVBase | ✅ 已审已修 | **有码、素人**；无码/FC2/国产/欧美不适合 |
| 8 | `mgstage` | MGStage | ✅ 已审已修 | **素人主源**、Prestige 有码；无码/FC2/国产/欧美不适合 |
| 9 | `freejavbt` | FreeJavBT | ✅ 已审已修 | 有码/无码/素人/FC2 聚合；国产不适合；欧美栏目弱 |
| 10 | `sevenmmtv` | 7MMTV | ✅ 已审已修 | 有码/素人/无码+FC2 中文聚合；国产栏目弱匹配；欧美不适合 |
| 11 | `iqqtv` | iQQTV | ✅ 已审已修 | **中文标题/剧情**；有码/素人/无码/FC2；国产弱；欧美不适合 |
| — | `avsex` | AVSex | ❌ **已下线** | 强制 Flare 过盾；慢源，从 catalog / scrape_details 移除 |
| 12 | `r18dev` | R18.dev | ✅ 已审已修 | **仅有码**（FANZA JSON）；部分素人可中；无码/FC2/国产/欧美不适合 |
| — | `avwikidb` | AVWikiDB | ❌ **已下线** | CF JS 挑战（代理+impersonate 仍 Just a moment）；须过盾，已移除 |
| U | 无码前缀专用 ×12 | heyzo…heydouga | ✅ 批量复测 | 全 `proxy_adaptive`；前缀自动挂；样例 scrape 全通 |
| — | `avsox` | AvSox | ⏸ 保留 | 空壳须 Flare；未下线 |
| F | `fc2` | FC2 官网 | ✅ 复测 | 首页+详情可用 |
| F | `fd2ppv` | FC2-PPV | ⚠ 复测 | 首页 OK；**详情 403 CF**（待裁定是否下线） |
| C | `madou` | Madou | ✅ 复测 | 国产主可用；MDX/MDSR 样例全通 |
| C | `madouqu` | Madouqu | ⚠ 复测 | **CF Just a moment**；默认链首位失效 |
| C | `xiao_huang_shu` | 小黄书 | ⚠ 复测 | **Access denied**；默认链第二位失效 |
| C | `hscangku` | 黄色仓库 | ✅ 部分 | 不进默认链；部分号可刮 |
| W | `theporndb` | ThePornDB | ✅ 已审已修 | **欧美主源**（REST+API Key）；YYYY/YY 均可 |
| W | `avheat` | AVHeat | ✅ 已审已修 | AIO 欧美；须 Flare；站内多为 YY；非 Blacked 全库 |
| — | `lulubar` | LuluBar | ❌ **已下线** | 综合组移除；catalog / scrape_details 已删 |
| 13 | `javday` | JavDay | ⏸ **暂跳过** | 综合；先跳过（后补） |
| 14 | `miss_av` | MissAV | ✅ 已审已修 | 综合强；FC2/素人/有码；date6 裸日期；国产防 MDX 错绑 |
| 15 | `njav` | NJAV/123AV | ✅ 已审已修 | 有码/无码/FC2；素人须加板号；国产号碰撞勿用 |
| 16+ | … | （见 catalog） | ⏳ 待审 | — |

---

## 站点记录

### 1. JavBus（`javbus`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | **有码**（主权威，列表 `/`）；**无码**（主权威之一，列表 `/uncensored`） |
| 不适配 | 素人 / FC2 / 国产 / 欧美 |
| 查找方式 | `GET {base}/{CODE}`；失败后再 `/search` + `/uncensored/search` |
| 番号风险 | 旧实现仅 `upper()` 一次：有码 pad（`SONE-15`≠`SONE-015`）、无码 date6（`1PON-062014-830` vs `062014_830` / `1pondo-…`、`CARIB-…` vs 裸 `011317-002`）易 404 |

**已修**

- `javbus_code_candidates`（`scrape_details/common.py`）：补零变体 + date6 / 品牌 slug  
- `_javbus_detail`（`makers/catalog_routes.py`）：多候选路径 + search 回退 + slug 用 `code_equiv`  
- 测试：`app/tests/test_javbus_code_candidates.py`

---

### 2. DMM（`dmm`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | **仅日本有码**（默认 enrich 链第 1） |
| 不适配 | 无码 / 素人 / FC2 / 国产 / 欧美（FC2 显式拒绝；非 FANZA 有码数字板） |
| 查找方式 | GraphQL `ppvContent(id=cid)`；CID ≈ `{digit}{series}{zfill5}`（如 `SSNI-123`→`ssni00123`） |
| 番号风险 | 分盘尾缀 `IPZZ-599C` 被 gate 判无效；短号/gate 与 guess 不一致；无数据时拼封面 URL 冒充命中；目录 `dmm_digit` 未优先 |

**已修**

- `_dmm_base_code`：剥尾缀后再造 CID  
- gate 与 guess 对齐（`\d{1,6}`）  
- 目录非空 `dmm_digit` 优先  
- 去掉「仅封面」假成功 → 明确 `未找到`  
- 测试：`app/tests/test_dmm_code_canon.py`

---

### 3. LibreDMM（`libredmm`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | **有码**（默认链第 2）；**素人**（默认链第 2，MGStage 之后） |
| 不适配 | 无码 / FC2 / 国产 / 欧美 |
| 查找方式 | `{base}/movies/{CODE}.json`（可 `processing` 轮询）；回退 `search.json?q=`（返回与详情同构） |
| 番号风险 | 单次 upper 路径；`IPZZ-599C` 实测 not_found；命中用 `code_key` 不认补零；素人需 `LUXU-001` 与 `259LUXU-001` 两形 |

**已修**

- `libredmm_code_candidates` + 多候选请求 + `code_equiv` 校验  
- 顺带修 `_parse_std` 分集正则：旧 `(?:EP\|E)?` 会把 `SONE-15` 误剥成 `SONE`（`search/av.py`）  
- 测试：`app/tests/test_libredmm_code_candidates.py`

---

### 4. AirAV.io（`airav_io`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | 有码**中文补全**；无码 / FC2 **默认链**；素人弱 |
| 不适配 | 国产规范号、欧美点分键 |
| 查找方式 | `search_result?kw=` → 标题等价匹配 → `/cn/video?hid=` |
| 番号风险 | 纯 `FC2-{id}` 可能空；无码 date6 / `1PON-…` 弱；junk 标题需拒 |

**本次**：详解已写；未改匹配器（既有 hid 缓存 + 标题门禁）。详见 [source-site-guides.md](./source-site-guides.md) §4。

---

### 5. Avmoo（`avmoo`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（AIO · `jav`） |
| 适合区 | **有码向内容**（非默认 enrich）；字段链 title/poster 中后段 |
| 不适配 | 无码（用 `avsox`）、欧美（用 `avheat`）、素人 / FC2 / 国产 |
| 查找方式 | `/cn/search/{CODE}` → `/cn/movies/{movieId}`（SPA，须 Flare） |
| 番号风险 | 空壳无 Flare=全失败；历史错页（E2E ABF-005）；`pick_aio_movie_path` 已禁裸 substring |

**本次**：站点详解已写（壳 + JS 导航 + 三站分工）。Flare 宕机未跑通命中表；**匹配器无需新改**（`aio_common` 已有折叠全等 / date6 候选，主要为 AvSox 场景）。

---

### 6. Jav321（`jav321`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | **有码**（默认链）；**素人**（默认链第 3） |
| 不适配 | 无码（有栏目但样例空）、FC2 / 国产 / 欧美 |
| 查找方式 | `POST {base}/search` body `sn=` → `.panel-info` 品番 + `code_equiv` |
| 番号风险 | 素人 `259LUXU-001` 站内品番为 `luxu-001`，旧 `code_equiv` 拒；历史错页（ABF-005） |

**已修**

- `code_equiv`：`parse_maker_code` 剥素人板号后按 `std_code_key` 比键（`259LUXU-001` ≡ `LUXU-001`；国产 `91CM` 不误剥）  
- 测试：`app/tests/test_code_equiv_board_prefix.py`

### JavLibrary（`javlibrary`）· 已下线

| 项 | 内容 |
|----|------|
| 原因 | 主站与镜像均 Cloudflare；本机 FlareSolverr 不可达，无法稳定拉页 |
| 处置 | 删除 `scrape_details/javlibrary.py`；从 `SOURCE_CATALOG` / 字段优先 / enrich providers / 相关脚本移除 |

### AVSex（`avsex`）· 已下线

| 项 | 内容 |
|----|------|
| 原因 | `access=proxy_flare` 强制过盾；直连 CF 403，且过盾慢源策略不保留 |
| 处置 | 删除 `scrape_details/avsex.py`；从 catalog / 字段优先 / settings / enrich 中文源集合 / e2e 样例移除 |

### AVWikiDB（`avwikidb`）· 已下线

| 项 | 内容 |
|----|------|
| 原因 | CF JS 挑战（`Just a moment`）；代理 + curl_cffi impersonate 仍无法过，须 Flare |
| 处置 | 删除 `scrape_details/avwikidb.py`；从 mirrors / 字段优先 / settings / enrich meta 集合 / e2e 移除 |

---

### 7. AVBase（`avbase`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV |
| 适合区 | **有码**、**素人**（均在默认 enrich 链） |
| 不适配 | 无码 / FC2 / 国产 / 欧美 |
| 查找方式 | `/works/{CODE}` → `__NEXT_DATA__`；回退 `/works?q=` |
| 番号风险 | 旧 `work_id` 全等拒板号/pad；搜索噪声 `source:CODE` |

**已修**

- `match_avbase_work_id` → `code_equiv`；冒号前缀 `work_id` 拒绝  
- 测试：`app/tests/test_avbase_work_id_match.py`

---

### 8. MGStage（`mgstage`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（Prestige / 素人配信） |
| 适合区 | **素人**（默认链第 1）；**有码** Prestige 系（默认链末段） |
| 不适配 | 无码 / FC2 / 国产 / 欧美；非 MGS 有码号（如 SSIS） |
| 查找方式 | `/product/product_detail/{CODE}/` → 搜索；Cookie `adc=1` |
| 番号风险 | 裸 `LUXU-001` 搜索空；须 `259LUXU-001` 等板号 |

**已修**

- `_pick_detail_href` / 品番校验：`code_equiv`  
- `mgstage_code_candidates`：目录反查板号（`LUXU`→`259LUXU`，`HMDN`→`328HMDN`）+ 兜底表  
- 测试：`test_mgstage_code_candidates.py`、`test_mgstage_pick_href.py`

---

### 9. FreeJavBT（`freejavbt`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（站内另有无码/欧美/FC2 分区） |
| 适合区 | 有码、无码（弱）、素人、FC2（库存参差）；默认 enrich 挂素人 |
| 不适配 | 国产；欧美点分键 |
| 查找方式 | `/{CODE}` 多语言前缀；FC2 试 PPV 形 |
| 番号风险 | `259LUXU-001` 软 404，须剥 `LUXU-001`；旧逻辑遇软 404 直接 raise |

**已修**

- `freejavbt_code_candidates`：剥素人板号 + FC2 变体  
- 软 404 识别补 EN/ZH「You May Like / 猜你喜欢」；失败续试下一候选  
- 测试：`app/tests/test_freejavbt_code_candidates.py`

---

### 10. 7MMTV（`sevenmmtv`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（站内另有素人/无码/中字/国产/去码） |
| 适合区 | 有码、素人、无码（库存新号）、FC2；中文标题/标签 |
| 不适配 | 欧美；国产（URL 常无番号，拒收防错绑） |
| 查找方式 | `searchall` / `searchform` / POST → `*_content/{id}/{slug}.html` |
| 番号风险 | slug 带板号（`328HMDN-332`）时旧 `folded endswith` 漏选；FC2 搜 `FC2-976194` 空，须裸 `976194` |

**已修**

- `pick`：slug 用 `code_equiv`（板号 / FC2-PPV）  
- `sevenmmtv_code_candidates`：剥板号 + FC2 PPV + **裸数字 id**  
- 测试：`app/tests/test_sevenmmtv_code_candidates.py`

---

### 11. iQQTV（`iqqtv`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（站内日本/无码/国产/欧美分区） |
| 适合区 | 有码（中文主补）、素人（默认链）、无码、FC2（库存参差） |
| 不适配 | 欧美点分键；国产样例弱 |
| 查找方式 | `/jp/search.php?kw=` → `player.php?uuid=`（CN 优先） |
| 番号风险 | `259LUXU` 须剥板；date6 须 `062014_830`；FC2 须 PPV/裸 id；详情 `page_mentions_code` 不认等价形 |

**已修**

- `iqqtv_code_candidates`：剥板号 + FC2PPV + date6（`_1pondo_…`）  
- `match_iqqtv_number` / `_iqqtv_page_mentions`：`code_equiv` + date6 标题形  
- 测试：`app/tests/test_iqqtv_code_candidates.py`

---

### 12. R18.dev（`r18dev`）

| 项 | 内容 |
|----|------|
| 组 | 有码 AV（FANZA JSON） |
| 适合区 | **有码**（默认 enrich）；部分 FANZA 素人 |
| 不适配 | 无码 / FC2 / 国产 / 欧美；多数 MGS 独占素人 |
| 查找方式 | `dvd_id={series}{5位}/json` → `combined={content_id}/json` |
| 番号风险 | 板号无法 `letter+digits` 解析时旧逻辑对空响应 `return True`；短号须 pad |

**已修**

- `_r18_detail_matches_code`：空响应拒收；`dvd_id` 用 `code_equiv`；板号先剥再比 content_id  
- `r18dev_code_candidates`：剥板号 + pad  
- 测试：`app/tests/test_r18dev_code_candidates.py`

---

### U. 无码前缀专用站（批量）

| 项 | 内容 |
|----|------|
| 成员 | heyzo / 1pondo / pacopacomama / carib / 10musume / kin8 / h0930 / h4610 / c0930 / tokyohot / nyoshin / heydouga |
| 挂载 | `uncensored_official_for_code` 按前缀注入（不进无码 UI 默认链） |
| 访问 | 全部 `proxy_adaptive` |
| 复测 | 12/12 首页 OK + 样例 scrape 有封面；前缀路由全 OK |
| 匹配 | **无需改** |

探针：`data/debug/uncensored_official_probe.txt`。详解表见 [source-site-guides.md](./source-site-guides.md) §U。

### AvSox（`avsox`）· 保留

| 项 | 内容 |
|----|------|
| 组 | 无码通用兜底（默认链首） |
| 访问 | `proxy_flare` |
| 现状 | 空壳 / 403；须 Flare；用户要求先保留 |

### F. FC2 / fd2ppv

| 源 | 结论 |
|----|------|
| `fc2` | 官网可用；样例多号可刮；库存 miss 属正常 |
| `fd2ppv` | 首页测通；**详情 CF 403**；enrich 当详情源失效；是否下线待定 |

探针：`data/debug/fc2_fd2ppv_probe.txt`。

### C. 国产

| 源 | 结论 |
|----|------|
| `madou` | ✅ 首页+详情可用（MDX/MDSR） |
| `madouqu` | ❌ CF 挑战；默认链首失效 |
| `xiao_huang_shu` | ❌ Access denied；默认链次失效 |
| `hscangku` | ⚠ 部分可刮；不进默认 |

探针：`data/debug/china_sources_probe.txt`。默认链建议改以 `madou` 打头（待你确认后再改代码）。

### W. 欧美

| 源 | 结论 |
|----|------|
| `theporndb` | ✅ API Key 已配则可刮；`BLACKED`/`PURETABOO`/`VIXEN` 样例通；已支持 YY 输入扩成 YYYY 查询 |
| `avheat` | ✅ Flare 可刮；识别码多为 **YY.MM.DD**；`western_code_candidates` 已对齐规范 YYYY；无 Blacked 库存属站内缺货 |

探针：`data/debug/western_sources_probe.txt`。

**已修**

- `western_code_candidates` / `_western_date_fold_key` + `code_equiv` YYYY↔YY（`scrape_details/common.py`）  
- `aio_common.scrape_aio_family`：搜索/挑链/详情校验吃双形态  
- `theporndb`：`_build_search_queries` / `_score_western_date_hit` 接受 YY  
- 测试：`app/tests/test_western_code_candidates.py`

### 14. MissAV（`miss_av`）

| 项 | 内容 |
|----|------|
| 组 | 综合 |
| 适合区 | **有码 / 素人 / FC2**；无码（HEYZO + 部分 date6）；国产兜底 |
| 不适配 | 欧美点分键；盲信 mosaic 字段 |
| 查找方式 | `GET {base}/cn/{slug}` 多候选；失败 `/cn/search/{code}` |
| 番号风险 | 素人板号页码≠查询串；date6 页码为裸 `062014_830`；国产 `MDX-0001` 曾被剥零当成日系 `MDX-001` |

**已修**

- `miss_av_code_candidates` / `_path_codes`：pad、剥板号、FC2-PPV、date6 裸日期  
- `_is_detail_html`：页内番号对候选 `code_equiv` **或** fold  
- `code_equiv`：国产前缀禁止 `_code_bucket` 剥零判等  
- 测试：`app/tests/test_miss_av_code_candidates.py`  

探针：`data/debug/miss_av_region_probe.txt`。

### 15. NJAV / 123AV（`njav`）

| 项 | 内容 |
|----|------|
| 组 | 综合 |
| 适合区 | **有码**、**无码（HEYZO）**、**FC2**；素人（须板号） |
| 不适配 | 国产（`MDX-0001` 日系同号碰撞）；欧美；盲搜素人裸字母号 |
| 查找方式 | 缓存 → `/ja/v/{slug}` 多候选 → 多关键词搜索 |
| 番号风险 | FC2 须 PPV slug；素人站内为 `328HMDN-332` 非 `HMDN-332`；搜索结果嘈杂须精确挑链 |

**已修**

- `njav_code_candidates` / `_path_slugs`：pad、加板号、FC2-PPV  
- 直链优先 + `_pick_detail_href` / `_is_detail_html` 用 `code_equiv`  
- 测试：`app/tests/test_njav_code_candidates.py`  

探针：`data/debug/njav_region_probe.txt`。

---

## 共用约定（后续站点也按此记）

| 规则族 | 典型形态 | 注意 |
|--------|----------|------|
| 有码 std3 | `SSIS-001` / `SONE-015` | pad=3；文件夹短号要补零候选；分盘 `…C`/`…CH` 先剥基号 |
| 无码 date6 | `1PON-062014-830`、`CARIB-011317-002` | 站内常是下划线 / 裸日期 / 品牌前缀 |
| 素人 | `HMDN-332`、`259LUXU-001` | 数字板号可剥可留，看站点 |
| FC2 | `FC2-976194` ≡ `FC2-PPV-976194` | 用 `code_equiv` / `fc2_slug_variants` |
| 国产 / 欧美 | 各站专用 | 勿套 JavBus/DMM |

公共工具：`code_equiv`、`fold_code`、`javbus_code_candidates`、`parse_maker_code` / `std_code_key`（`scrape_details/common.py`、`search/av.py`）。

---

## 更新方式

每审完一站，在本文件：

1. 进度总表改状态与适合区  
2. 「站点记录」追加一节（适合区 / 查找方式 / 风险 / 已修或「无需改」）  
3. 相关测试路径一并写上  

下一站站点详解：**JavDay（`javday`）**（catalog 顺序）；无码专用站与 FC2 已批量复测见上。
