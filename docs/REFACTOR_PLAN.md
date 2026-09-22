# SehuaNext 重构方案（模块化 / 去冗余 / 提效）

> 生成时间：2026-09-22
> 体检基线：`main` @ `884338c`（v1.2.21）
> 方法：`pc-code-refactor` 可逆拆分法（按职责拆、每步可回退、对外兼容、先验证后删除）

---

## 执行进度

| 阶段 | 状态 | 结果 |
|---|---|---|
| Phase 0 安全网 | ✅ 完成 | 分支 `refactor-modular`（本地）；基线 `1 failed / 284 passed`（见下）；前端 `tsc --noEmit` = **0 错误** |
| Phase 1A 死 shim | ✅ 完成 | **发现并修复误判**：85 处旧路径引用已迁移到真实模块；16 个 shim 已归档至 `_archive/dead_shims/` |
| Phase 1B 仓库整理 | ✅ 完成 | 归档 **173 个文件 / 34.8 MB**（根目录临时产物 82、maps 快照 32、其他 24 + 迁移备份 35） |
| Phase 1C `main.py` PG 错误映射合一 | ✅ 完成 | 与 Phase 3 合并处理；`test_postgres_dsn()` 成为唯一实现 |
| Phase 2 后端去重 | 🟡 部分 | **已完成 6 组**：连接池（`pg`↔`bitmagnet_pg`）、`_cache_get`、`_abs`、`_build_fanza_trailer`、`_madou_std`=`std_code`、`_normalize_proxy_url`、p115 的 `_is_clear_ok`=`_is_del_ok`。**剩余孪生家族**见 §八 |
| Phase 3 `main.py` 瘦身 | ✅ 完成 | **738 → 160 行**；14 个重复端点收敛为参数化 router 工厂 |
| Phase 4 拆 `enrich.py` / `embed.py` | ⬜ 待做 | 见 §八「未完成项与原因」 |
| Phase 5 前端 | 🟡 部分 | **5A ✅**：`lib/api.ts` 4,805 行 → `lib/api/` 19 个域模块（最大 727 行）；5B/5C 待做 |
| Phase 6 性能专项 | ⬜ 待做 | 需先测量再动手（沿用 `_diag_*`） |

### ⚠️ 基线不是全绿（改动前就如此，非本次引入）

- `test_enrich_local_status_scan.py::test_status_totals_overlay` —— **确定性失败**。
  `_apply_local_status_totals`（`enrich.py:1750`）现行语义是「队列表**有任何行**（含 `pending`）就以库为准，tip 只在库全空时兜底」，
  而测试断言的是旧语义（guard 不含 `pending`）→ **测试未跟上 v1.2.21 的改动**。
- `test_enrich_round18_fixes.py::test_paused_status_does_not_raise` —— **偶发失败**，依赖库内 `running` 残留与 `_enrich_job["currentRegion"]` 的前序污染；
  单独跑该文件必过，全量跑时有时不过。

> 结论：回归验收标准定为「**失败集合不许变多**」，而非「全绿」。上述两条建议另开一轮单独修，不与重构混做。


## 一、体检数据（实测，非估计）

| 端 | 文件数 | 总行数 | 最大文件 | 最大函数 |
|---|---|---|---|---|
| API (Python) | 214 | 83,994 | `scrap_library/enrich.py` **16,844** | `run_enrich` **1,185 行** |
| Web (TS/TSX) | 135 | 39,115 | `lib/api.ts` **4,474** | `MakersManagePanel.tsx` **3,736** |

规模分布（后端）：

```
enrich.py            16,844  ████████████████████████████████████
embed.py              5,850  █████████████
conn_settings_routes  2,133  █████
media/routes.py       1,834  ████
actress_avatar.py     1,729  ████
outbound_http.py      1,495  ███
catalog_routes.py     1,270  ███
```

超长函数统计：`>600 行` **4 个**，`>300 行` **14 个**。

前端头部文件：

```
lib/api.ts                    4,474
features/settings/MakersManagePanel  3,736
features/settings/EnrichLivePanel    3,236
features/settings/EnrichStrategyPanel 2,154
features/makers/MakersScreen         1,965
features/settings/P115Panel          1,519
features/settings/AiModelsPanel      1,316
```

---

## 二、六个真问题（每条都有证据）

### 问题 1：巨型单文件（最高优先级）

`enrich.py` 一个文件 16,844 行、281 个顶层定义，里面塞了：队列扫描、本地 NFO 分类、详情抓取、合并策略、封面、状态接口、任务调度、落库。

超长函数：`run_enrich` 1,185 行、`_fetch_detail` 850 行、`_merge_got` 746 行、`enrich_one_row` 582 行、`get_enrich_status` 546 行。

**危害**：改一处要翻半天、无法并行开发、无法单测、人（和 AI）都容易改错。

### 问题 2：复制粘贴孪生文件（后端冗余主体）

**9 组函数体逐字节相同**：

| 重复函数 | 位置 |
|---|---|
| `std_code` / `_madou_std` ×3 | `scrape_details/common.py`、`madou.py`、`madouqu.py` |
| `_normalize_proxy_url` / `normalize_proxy_url` ×2 | `core/conn_settings_routes.py`、`core/outbound_http.py` |
| `close_pool` ×2 | `core/pg.py`、`search/bitmagnet_pg.py` |
| `_cache_get` ×2 | `makers/catalog_routes.py`、`media/routes.py` |
| `_abs` ×2 | `makers/catalog_routes.py`、`makers/providers_extra.py` |
| `_is_clear_ok` / `_is_del_ok` ×2 | `p115/offline.py`（同文件内） |
| `_build_fanza_trailer` ×2 | `scrape_details/dmm.py`、`freejavbt.py` |
| `get_job_status` ×2 | `search/bitmagnet_embed_svc.py`、`sehua_resource_embed_svc.py` |
| `request_stop` ×2 | 同上 |

**223 组跨文件重复代码块（≥12 行连续）**，主要孪生家族：

| 孪生家族 | 证据 |
|---|---|
| `core/pg.py` ↔ `search/bitmagnet_pg.py` | 多组逐块相同 → 同一套连接池逻辑写了两遍 |
| `search/bitmagnet_embed_svc.py` ↔ `sehua_resource_embed_svc.py` | 同构向量化服务写了两遍 |
| `scrape_details/onespondo.py` ↔ `pacopacomama.py` | **30+ 组相同块** → 基本是复制品 |
| `scrape_details/madou.py` ↔ `madouqu.py` | 多组相同块 |
| `scrape_details/dmm.py` ↔ `freejavbt.py` | 多组相同块 |
| `heydouga` / `heyzo` / `kin8` / `nyoshin` / `tokyohot` | 5 个文件共享同一段逻辑 |
| `p115/extract.py` ↔ `p115/relocate.py` | 多组相同块 |
| `media/bangumi_anilist.py` ↔ `media/routes.py` | 多组相同块 |

**危害**：改一处漏一处，行为漂移（同一个 bug 修了一个没修另一个）。

### 问题 3：`main.py` 自身在重复自己

`main.py` 737 行里：

- `/settings/resource-db/*` 7 个端点 与 `/settings/bitmagnet-db/*` 7 个端点 **近乎逐行相同** → 可参数化为一个 router 工厂。
- `test_resource_db`（L301-366）与 `_test_postgres_dsn`（L665-690）**是同一段 PG 错误映射写了两遍**。
- 大量路由处理逻辑（备份导入导出、向量任务控制）本该在 feature 模块里，`main.py` 应只做装配。

### 问题 4：16 个死代码 shim 文件

`apps/api/app/` 根目录下 16 个 8 行文件，靠 `import_module` 把 `app.core.pg` 的符号灌进 `app.pg`：

```
pg.py  outbound_http.py  bitmagnet_pg.py  search_av.py  prefix_ranges.py
prefix_catalog_dmm.py  prefix_catalog_harvest.py  prefix_catalog_store.py
prefix_code_read.py  prefix_maker_names.py  scrap_enrich_strategy.py
scrap_library_embed.py  scrape_sources_settings.py  makers_settings.py
makers_catalog_routes.py  makers_providers_extra.py
```

**⚠️ 2026-09-22 更正**：初版检索结论「全仓零引用」**是错的**。当时正则写成 `app\.(pg|...)`，漏掉了 `from app import pg` 这种写法。
实情：`apps/api/scripts/` 下 **85 处**（35 个脚本）依赖这些 shim，连 `app/tests/test_prefix_code_read.py` 都被间接牵连。

**已处理**：把这 85 处全部迁移到真实模块路径（`from app.search import bitmagnet_pg` 等），迁移后残留复查 = 0，shim 才真正成为死代码并归档。
教训：**死代码判定必须同时覆盖 `from X import Y` 与 `import X.Y` 两种形式**，且必须跑回归验证。

### 问题 5：前端 8 个设置面板各写一遍同样的活

- `onSave` 重复定义 **8 处**（BitmagnetDbPanel / CloudSaverPanel / EnrichStrategyPanel / NetworkPanel / P115Panel / PansouPanel / ResourceDbPanel / TmdbPanel）
- `onTest` 重复定义 **7 处**
- `hubStatus` 重复 **4 处**
- `lib/api.ts` 4,474 行单文件承载 auth/resource/settings/makers/media/p115/ai 全部接口

### 问题 6：仓库根目录垃圾堆积

根目录 ~171 个未跟踪文件（`_p_*.txt`、`.tmp_*`、`_check*.txt`、`_mem*.txt` …），是历代排查的临时输出，全在 git 里躺着。

---

## 三、目标结构

### 后端 `apps/api/app/`

```
app/
├── main.py                    # 只做装配：建 app、挂中间件、include 路由
├── core/                      # 横切能力
│   ├── pg_pool.py             # ★新：连接池基类（pg / bitmagnet_pg 共用）
│   ├── pg.py                  #    薄封装，复用 pg_pool
│   ├── outbound_http.py
│   ├── atomic_io.py
│   └── ...
├── features/                  # ★新：按业务领域分包
│   ├── settings/              #   resource-db / bitmagnet-db / conn 设置
│   │   ├── routes.py          #   ★参数化 router 工厂，消掉 7×2 重复
│   │   ├── schemas.py
│   │   └── backup_routes.py
│   ├── enrich/                #   ★由 enrich.py 16,844 行拆出
│   │   ├── __init__.py        #   重导出全部旧名称 → 调用方零改动
│   │   ├── queue.py           #   队列扫描 / 批量出入队
│   │   ├── local_scan.py      #   本地 NFO 全盘分类
│   │   ├── fetch.py           #   详情抓取
│   │   ├── merge.py           #   合并策略
│   │   ├── cover.py           #   封面
│   │   ├── status.py          #   状态 / 角标
│   │   ├── job.py             #   任务调度 / 线程池
│   │   └── persist.py         #   落库
│   └── embed/                 #   ★由 embed.py + 两个 embed_svc 合并
│       ├── __init__.py
│       ├── base.py            #   ★公共向量化基类（消 twins）
│       ├── sehua.py
│       └── bitmagnet.py
├── scrape_details/            # 保留 + 抽 _base.py
│   └── _base.py               #   ★共同的 inits/helper/循环
└── (删除 16 个根级 shim)
```

### 前端 `apps/web/src/`

```
src/
├── lib/
│   └── api/                   # ★api.ts 4,474 行按域拆
│       ├── index.ts           #   重导出 → 现有 import 路径不变
│       ├── client.ts          #   fetch 封装 / 拦截器 / 错误
│       ├── auth.ts  resource.ts  settings.ts
│       ├── makers.ts  media.ts   p115.ts  ai.ts
├── hooks/
│   ├── useConnTest.ts         # ★消掉 onTest ×7
│   ├── usePanelSave.ts        # ★消掉 onSave ×8
│   └── useHubStatus.ts        # ★消掉 hubStatus ×4
└── features/settings/
    ├── MakersManagePanel/     # 3,736 → 拆成分片
    ├── EnrichLivePanel/       # 3,236 → 拆成分片
    └── EnrichStrategyPanel/   # 2,154 → 拆成分片
```

---

## 四、分阶段执行

原则：**先零风险清理 → 再去重 → 再拆大文件 → 最后碰前端**。每阶段独立可回退。

### Phase 0 · 安全网（必做前置）

- 建分支 `refactor/modular`（当前 `main` 干净）
- 跑测试基线：`cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe -m pytest app/tests -q` → 期望 **285 passed / 19 subtests**
- 前端类型基线：`& <node.exe> node_modules\typescript\bin\tsc --noEmit -p tsconfig.json`
- 列出每个待拆模块的外部导入点（拆分后逐项验证）

### Phase 1 · 零风险清理

| 动作 | 收益 | 风险 |
|---|---|---|
| 删 16 个死 shim | 去 16 个文件 / 128 行 + 消除 `import_module` 魔法 | 零（已全仓验证无引用） |
| 根目录临时文件归档/忽略 | 仓库整洁，`git status` 可用 | 零 |
| `main.py` 两处 PG 错误映射合一 | 去重 ~65 行 | 极低 |

### Phase 2 · 后端去重（收益最大 / 风险低）

按 `pc-code-refactor` 策略 D（共享代码抽离）：

1. `core/pg_pool.py` 连接池基类 → `core/pg.py`、`search/bitmagnet_pg.py` 复用
2. `scrape_details/_base.py` → 收敛 onespondo/pacopacomama、madou/madouqu、dmm/freejavbt、heydouga/heyzo/kin8/nyoshin/tokyohot
3. `features/embed/base.py` → 收敛两个 `*_embed_svc`
4. 小工具归位：`normalize_proxy_url` → `core/`，`_cache_get`/`_abs` → `core/`，`std_code` 单一实现
5. `p115/extract.py` ↔ `relocate.py` 公共块抽离

每步做完立刻跑 285 项回归。

### Phase 3 · `main.py` 瘦身

- `/settings/{resource,bitmagnet}-db` 用**参数化 router 工厂**替换 14 个近乎重复的端点
- 备份/向量任务端点下沉到 `features/settings/`
- `main.py` 目标 < 120 行，只剩装配

### Phase 4 · 拆分巨型文件（最需小心，用 6 步可逆拆分法）

`enrich.py` 16,844 行 → `features/enrich/` 包：

- Step 1 建目录不搬代码 → Step 2 逐职责**复制** → Step 3 `__init__.py` 重导出全部旧名称 → Step 4 验证（导入 / 测试 / 起服务 / 无循环依赖）→ Step 5 内部改相对导入 → Step 6 删旧文件
- **重构只搬代码、不改逻辑**（坑 5）——发现问题另开一轮
- `embed.py` 5,850 行同理

### Phase 5 · 前端

1. `lib/api.ts` → `lib/api/*` + `index.ts` 重导出（现有 import 路径不变）
2. 抽 `useConnTest` / `usePanelSave` / `useHubStatus`，消掉 8+7+4 处重复
3. 拆三个超大 Panel（>2,000 行），按「容器管数据 / 展示组件管渲染」

### Phase 6 · 性能专项（先测量，后动手）

- 用现有 `_diag_*` 工具先测基线再改，禁止凭感觉优化
- 已知待办：扫描期间状态接口断连（305s 内 7 次 `Server disconnected`，多线程扫盘打满 GIL）
- 已知结论勿推翻：封面阶段占墙钟 ≈70%、慢源 `iqqtv+avbase+airav_io = 80.9%`（**不是 dmm**）

---

## 五、纪律与安全网（本项目硬约束）

⚠️ **管线在跑时只读取证** —— 改 `app/*.py` 会触发 dev_server 硬重启，且**只重启服务、不恢复 enrich**。

⚠️ **Bash 在本机不可用** → 一律用 PowerShell。

⚠️ **stdout 常被吞** → 结果写文件再读。

⚠️ **同文件多处编辑必须串行**（并行会被后写覆盖，工具仍报成功）。

⚠️ **本环境删除文件可能静默失败**（`Remove-Item` 曾无效）→ Phase 1/4 的删除步骤需先用一次性文件验证删除方案可行，再批量执行。

⚠️ **反证必做**：回退 → 期望 FAILED → 还原 → 期望 PASS，才算验证过。

⚠️ **热路径禁令**（重构时不得引入）：状态热路径禁磁盘校验/DB 写；读路径不许写库；`GLOBAL_SUPPLEMENT_N` 封面回退池修过两次勿再动。

---

## 六、验收标准

- [ ] 285 passed / 19 subtests 全绿
- [ ] 前端 `tsc --noEmit` 零错误
- [ ] 无 >1,000 行的源文件（`enrich.py` / `api.ts` 已拆）
- [ ] 无逐字节重复的函数体（9 组 → 0）
- [ ] 跨文件重复块 223 组 → 显著下降（孪生家族收敛）
- [ ] 对外导入路径零变更（调用方一行不改）
- [ ] 服务能正常启动、主要功能手工点通
- [ ] 性能无退化（Phase 6 用同一基线对比）

---

## 七、需要你确认

1. **从哪开始**：建议 Phase 0+1（安全网 + 零风险清理），当天可见收益。
2. **是否建独立分支**：建议 `refactor/modular`，逐步提交、随时回退。
3. **Phase 4 的拆分粒度**：`enrich.py` 拆成 8 个模块（如上）是否符合你心里的结构？
4. **根目录垃圾**：归档到 `_archive/` 还是直接删？（本环境删文件不可靠，建议先归档）

---

## 八、本轮完成明细与未完成项

### 已完成（均已验证）

| 项 | 结果 | 验证方式 |
|---|---|---|
| 分支与归档 | `refactor-modular`（本地）；`_archive/` 归档 **173 个文件 / 34.8 MB**（清单见 `_archive/MANIFEST.md`） | `git status` 干净；删除能力实测可用 |
| 旧路径迁移 | `apps/api/scripts/` 下 **85 处** `from app import <shim>` → 真实模块 | AST 静态解析（360 文件/1256 导入），残留 = 0 |
| `main.py` 瘦身 | **738 → 160 行**；DB 设置端点 → `app/core/db_settings_routes.py` 参数化工厂 | OpenAPI 路由 **25/25 逐条一致**，请求体 model 名与 operationId 全等 |
| 连接池合并 | `core/pg_pool.py::DbPool`；`core/pg.py` / `search/bitmagnet_pg.py` 变薄封装 | 25 项行为断言（超时、游标名、池参数、重建、异常类型）全过 |
| 重复实现消除 | `_cache_get`×2、`_abs`×2、`_build_fanza_trailer`×2、`_madou_std`×2=`std_code`、`_normalize_proxy_url`×2、`_is_clear_ok`=`_is_del_ok` | 参考实现差分测试 **103 例**全一致 |
| 前端 api.ts | **4,805 行 → `lib/api/` 19 模块 + barrel**；`lib/api.ts` 保留为重导出壳（调用方零改动） | `tsc --noEmit` **0 错误** |
| 回归基线 | `1 failed / 284 passed`（失败集合自始至终未变多） | 每次改动后全量 pytest |

### 未完成项与原因

**1. `enrich.py`(16,844 行) / `embed.py`(5,850 行) 拆分 —— 本轮未做。**

原因：这两个文件内部高度耦合（281 个顶层定义共用 `_enrich_job` 等模块级可变状态），
盲目按职责切分会立刻产生**循环导入**与 `NameError`。安全做法需要先做一轮
**顶层定义的依赖分析**（每个定义引用了哪些模块级名字），据此找出可分离的簇，
再按「共享状态模块 → 叶子模块 → 上层模块」自底向上搬迁。这属于独立一轮的工作量，
且必须在**刮削管线空闲**时进行（改 `app/*.py` 会触发 dev_server 硬重启）。

**2. 剩余孪生家族 —— 本轮未做。**

| 孪生家族 | 备注 |
|---|---|
| `scrape_details/onespondo.py` ↔ `pacopacomama.py` | 30+ 组相同块，基本是复制品 |
| `heydouga` / `heyzo` / `kin8` / `nyoshin` / `tokyohot` | 5 文件共享同一段逻辑 |
| `search/bitmagnet_embed_svc.py` ↔ `sehua_resource_embed_svc.py` | 同构向量化服务（`get_job_status` / `request_stop` 等） |
| `p115/extract.py` ↔ `relocate.py` | 公共块 |
| `media/bangumi_anilist.py` ↔ `media/routes.py` | 公共块 |
| `scrap_library/enrich.py::_cache_get` | 2 行转发壳（**有意保留**：需绑定各自模块的缓存 dict） |

**3. 前端 5B/5C —— 本轮未做**：8 个面板的 `onSave`×8 / `onTest`×7 / `hubStatus`×4 抽 hook；
3 个超大 Panel（3,736 / 3,236 / 2,154 行）按「容器管数据 / 组件管渲染」拆分。

**4. Phase 6 性能专项 —— 未做**：需先跑 `_diag_*` 取基线，不凭感觉优化。

### 纪律提醒

- 刮削管线在跑时**只读取证**；改 `app/*.py` 会硬重启 dev_server 且不恢复 enrich。
- 剩余项建议**每项单独一轮**，每轮结束跑全量回归 + `tsc`，失败集合不得变多。

