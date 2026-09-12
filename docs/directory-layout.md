# 目录结构约定

## 总览（合理）

```
sehua-next-web/
├── apps/
│   ├── web/                 # Next.js PWA :3020
│   └── api/                 # FastAPI :8020
│       ├── app/             # 业务代码
│       │   └── scrape_maps_seed/   # 映射种子（进 git）
│       ├── scripts/         # 运维脚本（进 git）
│       └── _local_refs/     # 本机参考数据（不进 git）
│           └── mdcx/        # mapping_actor.xml · Actress.db
├── config/                  # app.json 等
├── data/                    # 运行时缓存/映射（不进 git 大文件）
├── media/                   # 刮削库 / STRM（不进 git）
├── docs/                    # 本目录：仓库文档（进 git）
├── backups/                 # 本机备份（不进 git）
├── docker/ · Dockerfile · docker-compose.yml
├── scripts/                 # 根级辅助脚本
└── README.md
```

程序里的 `ROOT` = 仓库根。因此：

- 映射/缓存必须在 **`data/`**，不要放 `apps/data/`
- 片库必须在 **`media/`**，不要塞进 `data/`

## 评估结论

| 路径 | 判定 | 说明 |
|------|------|------|
| `apps/web` · `apps/api` | ✅ | 前后端分离清晰 |
| `apps/api/app/scrape_maps_seed/` | ✅ | 默认可交付；体积小 |
| `data/scrape_maps/` | ✅ | 本机大表/人工修正；优先于 seed |
| `media/` | ✅ | 与 `data/` 职责分离 |
| `apps/api/_local_refs/mdcx/` | ✅ | MDCX 源材料；脚本默认识别 |
| `docs/` | ✅ | 长文档集中，避免散落 |
| `backups/` | ✅ | 整理/迁移快照；gitignore |
| `apps/data/` | ❌ 已清理 | 曾误放，程序从不读取 |
| `apps/api/_gap_reports/` | ❌ 应保持清理 | 探针输出；备份在 `backups/workspace-*` |

## 进 git / 不进 git

**进 git**

- `apps/**` 业务与种子映射、脚本
- `docs/**`
- `config/app.json`（及示例）
- 根 `README`、compose、Dockerfile

**不进 git**（见 `.gitignore`）

- `data/scrape_maps/`、`data/scrap_facets_snap/`、`data/meta/`、`data/prefix_catalog/` …
- `media/**`
- `apps/api/_local_refs/`、`apps/api/_gap_reports/`、`apps/api/_*.py|json|…`
- `backups/`、`.refs/`、`.agents/`、`.workbuddy/`、`.env*.local`

## 禁止

- 不要在**仓库外**路径批量整理/删除
- 不要删 `media/`、`data/meta`、`data/prefix_catalog`、Postgres
- 不要把大批探针结果再提交进 `apps/api/app/`

## `apps/` 内部清晰度

### `apps/web` — 清晰

```
src/
├── app/          # Next 路由壳
├── features/     # 按业务：home / makers / media / settings / …
├── components/   # 通用 UI
├── shell/        # Tab / AppShell
├── lib/ · hooks/ · config/ · types/
```

按功能域分包，和 Tab 一致。主要负担是超大 `app-ui.css`（样式未按 feature 拆）。

### `apps/api` — 顶层合理，`app/` 偏平

```
api/
├── app/                 # ~100 个 .py 几乎全摊在根上
│   ├── scrape_details/  # 按站点拆源（清晰）
│   └── scrape_maps_seed/
├── scripts/             # 运维脚本
└── _local_refs/         # 本机参考
```

合理处：`scrape_details/`、大致的 `*_routes` / `*_store` / `*_client` 命名。

不清处：

1. `app/` 根平铺过多 — prefix / scrap_library / p115 / ai / search 靠文件名前缀分区，文件夹边界弱
2. `scrap_*` 与 `scrape_*` 双轨命名易混
3. `test_*.py` 与业务同目录，未独立 `tests/`
4. 探针文件易回流 `api/` 根（`_tmp_*`、`_gap_reports`）

日后若重构，可按域建子包（不必一次拆完），例如 `core/`、`scrap_library/`、`prefix/`、`p115/`、`ai/`、`search/`。
