# 目录结构约定

## 总览（合理）

```
sehua-next-web/
├── apps/
│   ├── web/                 # Next.js PWA :3020
│   └── api/                 # FastAPI :8020
│       ├── app/             # 业务（按域分包）
│       │   ├── main.py
│       │   ├── core/ auth/ ai/ p115/ prefix/
│       │   ├── scrap_library/ scrape/ scrape_details/
│       │   ├── scrape_maps_seed/
│       │   ├── search/ makers/ media/ translate/ tests/
│       ├── scripts/         # 运维脚本（进 git）
│       └── _local_refs/     # 本机参考（不进 git）· mdcx/
├── config/
├── data/                    # 运行时缓存/映射
├── media/                   # 刮削库 / STRM
├── docs/
├── backups/
└── README.md
```

程序里的 `ROOT` = 仓库根。映射/缓存在 **`data/`**，片库在 **`media/`**。

## `apps/api/app` 分包（已整理）

| 包 | 内容 |
|----|------|
| `core/` | db · pg · bootstrap · settings · http · region … |
| `auth/` | 登录鉴权 |
| `ai/` | 助手 / 对话 / 嵌入配置 |
| `p115/` | 115 网盘 |
| `prefix/` | 前缀目录 / STRM / harvest |
| `scrap_library/` | 刮削库向量 / 补齐 / 头像 / 字幕 / 封面 |
| `scrape/` | 源站配置与元数据优化（不含 details） |
| `scrape_details/` | 各源站解析器 |
| `scrape_maps_seed/` | 演员/标签映射种子 |
| `search/` | 资源搜索 · sehua/bitmagnet · 收藏 · 论坛 |
| `makers/` · `media/` · `translate/` | 片商目录 · 影视 · 翻译 |
| `tests/` | 原 `app/test_*.py` |

入口仍为 [`apps/api/app/main.py`](../apps/api/app/main.py)，导入形如 `from app.scrap_library.embed_routes import …`。

## 进 git / 不进 git

**进 git**：`apps/**` 业务与种子、脚本、`docs/**`、`config/app.json`、根 README / Docker。

**不进 git**：`data/scrape_maps/`、`media/**`、`apps/api/_local_refs/`、`apps/api/_gap_reports/`、`apps/api/_*.py|json…`、`backups/`、`.refs/` 等。

## 禁止

- 不要在仓库外路径批量整理/删除
- 不要删 `media/`、`data/meta`、`data/prefix_catalog`、Postgres
- 不要把探针探针结果再塞回 `apps/api/app/`

## `apps/web`

```
src/app · features/ · components/ · shell/ · lib/
```

按 Tab/业务域分包，结构清晰。主要负担是超大 `app-ui.css`。

## 本机运行时

见 [local-runtime.md](./local-runtime.md)、[scrape-maps.md](./scrape-maps.md)。
