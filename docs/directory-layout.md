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
| `apps/api/_gap_reports/` | ❌ 已清理 | 探针输出；备份在 `backups/workspace-*` |

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
- 不要把探针探针结果再提交进 `apps/api/app/`
