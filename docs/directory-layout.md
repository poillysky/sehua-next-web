# 目录结构约定

## 总览（合理）

```
sehua-next-web/
├── apps/
│   ├── maps/                # 映射种子（唯一进 git 的 JSON 表）
│   ├── web/                 # Next.js PWA :3020
│   └── api/                 # FastAPI :8020
│       ├── app/             # 业务（按域分包）
│       │   ├── main.py
│       │   ├── core/ auth/ ai/ p115/ prefix/
│       │   ├── scrap_library/ scrape/ scrape_details/
│       │   ├── search/ makers/ media/ translate/ tests/
│       ├── scripts/         # 运维脚本（进 git）
│       └── _local_refs/     # 本机参考（不进 git）· mdcx/
├── config/                  # app.json · app.local* · sql/ 参考 DDL
├── data/                    # 运行时缓存 / 映射覆盖（见 data/README）
├── media/                   # scrap-library / strm-library
├── docker/                  # 镜像内脚本；Dockerfile/compose 在仓库根
├── docs/
├── backups/                 # 本机备份：db/ + workspace/（勿提交）
├── Dockerfile · docker-compose.yml · start-dev.* · stop-dev.*
└── README.md
```

程序里的 `ROOT` = 仓库根。  
**映射种子** → `apps/maps/{makers,prefixes,scrape,regions,sites}/`；**运行时覆盖** → `data/`；片库 → `media/`。

| 根目录 | 说明 |
|--------|------|
| `config/` | 默认 settings + 本机覆盖；`sql/` 仅参考，见 [`config/README.md`](../config/README.md) |
| `docker/` | supervisord / entrypoint；构建入口仍在根，见 [`docker/README.md`](../docker/README.md) |
| `media/` | 片库，见 [`media/README.md`](../media/README.md) |
| `backups/` | `db/` 库导出 · `workspace/` 整理归档，见 [`backups/README.md`](../backups/README.md) |
| `.agents` / `.refs` / `.workbuddy` | 本机工具（gitignore，不整理） |
## `apps/maps`（映射种子）

见 [`apps/maps/README.md`](../apps/maps/README.md)、[scrape-maps.md](./scrape-maps.md)。

## `apps/api/app` 分包

| 包 | 内容 |
|----|------|
| `core/` | db · maps_paths · pg · bootstrap · settings · http · region … |
| `auth/` | 登录鉴权 |
| `ai/` | 助手 / 对话 / 嵌入配置 |
| `p115/` | 115 网盘 |
| `prefix/` | 前缀目录 / STRM / harvest |
| `scrap_library/` | 刮削库向量 / 补齐 / 头像 / 字幕 / 封面 |
| `scrape/` | 源站配置与元数据优化（不含 details） |
| `scrape_details/` | 各源站解析器 |
| `search/` | 资源搜索 · sehua/bitmagnet · 收藏 · 论坛 |
| `makers/` · `media/` · `translate/` | 片商目录 · 影视 · 翻译 |
| `tests/` | 原 `app/test_*.py` |

入口仍为 [`apps/api/app/main.py`](../apps/api/app/main.py)。

## 进 git / 不进 git

**进 git**：`apps/**`（含 `apps/maps/` 完整演员/标签/标题表）、脚本、`docs/**`、`config/app.json`、根 README / Docker。

**不进 git**：`data/prefix/`、`data/cache/`、`data/mirrors/`、`data/meta/`、`data/debug/`、`media/**`、`apps/api/_local_refs/`、`apps/api/_gap_reports/`、`apps/data/`（禁止再出现）、`backups/` 等。  
（已废弃：`data/scrape_maps/` 演员·标签·标题双份；旧扁平名 `prefix_catalog` / `cover-cache` / `scrap_facets_snap` / `_debug`。）

## 禁止

- 不要在仓库外路径批量整理/删除
- 不要删 `media/`、`data/meta`、`data/prefix/catalog`、Postgres
- 不要把探针结果再塞回 `apps/api/app/`
- 不要在多处复制同名映射 JSON

## `apps/web`

```
src/app · features/ · components/ · shell/ · lib/
```

按 Tab/业务域分包。主要负担是超大 `app-ui.css`。

**包管理器：只用 npm**（与根 `start-dev.ps1`、CI `npm ci` 一致）。  
保留 `package-lock.json`，不要再生成 `pnpm-lock.yaml`。若本地 `node_modules` 里仍有 `.pnpm/`，在 `apps/web` 下删掉 `node_modules` 后执行 `npm ci` 重装。

共享映射 JSON 由 `npm run sync-maps`（`predev`/`prebuild`）从 `apps/maps` 复制到 `apps/web/maps/`（gitignore，Turbopack 可读）。

## `apps/api` 临时文件

- 运维/一次性脚本进 `apps/api/scripts/`
- 探针与临时烟测（`_tmp_*.py`、`_gap_reports/`）勿放在 `apps/api/` 包根；本机用完即删，或放 gitignore 的 `_local_refs/`
