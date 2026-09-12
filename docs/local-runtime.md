# 本机运行时目录

以下目录默认**不提交**到 GitHub（体积大或含隐私/本机状态）。

## `data/`

相对仓库根。短说明见 [`data/README.md`](../data/README.md)。

| 子路径 | 用途 |
|--------|------|
| `scrape_maps/` | 演员/标签映射（正式） |
| `scrap_facets_snap/` | 片商页分面磁盘快照 |
| `prefix_catalog/` | 七区前缀→番号目录 |
| `meta/` · `cover-cache/` · `presets/` | 其它本机缓存 |
| `*.json` 镜像类 | 如 site-mirrors（本机） |

用户/会话/设置主体在 **Postgres**（`SNS_META_DSN`），不在这些文件里。

## `media/`

见 [`media/README.md`](../media/README.md)。

| 子路径 | 用途 |
|--------|------|
| `scrap-library/` | 刮削 NFO/海报（含 `_actress/` 女优头像） |
| `strm-library/` | 七区 STRM |

## `apps/api/_local_refs/`

本机参考数据（gitignore）：

- `mdcx/mapping_actor.xml`
- `mdcx/Actress-20250220.db`

## `backups/`

本机备份。例如：

- `backups/workspace-2026-09-12/` — 目录整理前快照（含旧 `_gap_reports`、误放的 `apps/data`）
- `backups/bitmagnet-db` · `backups/resource-db` — DB 转储类

整理脚本**只应写入本仓库内的 `backups/`**，不要写到桌面/其它盘除非你显式指定。
