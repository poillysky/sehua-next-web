# 本机运行时目录

以下目录默认**不提交**到 GitHub（体积大或含隐私/本机状态）。

## `data/`

相对仓库根。短说明见 [`data/README.md`](../data/README.md)。

| 子路径 | 用途 |
|--------|------|
| `meta/` | cf-clearance 等 |
| `mirrors/` | site-mirrors / iqqtv-mirror |
| `prefix/catalog/` | 七区前缀→番号目录 |
| `prefix/code-ranges.json` | 前缀流水号上限缓存 |
| `cache/cover/` | 封面缩略缓存 |
| `cache/facets/` | 刮削库分面磁盘快照 |
| `presets/` | 本机预设 |
| `debug/` | 脚本报告 / 探针输出 |

用户/会话/设置主体在 **Postgres**（`SNS_META_DSN`），不在这些文件里。  
演员/标签/番号标题映射只在 **`apps/maps/scrape/`**（勿再写 `data/scrape_maps/`）。

## `media/`

见 [`media/README.md`](../media/README.md)。

| 子路径 | 用途 |
|--------|------|
| `scrap-library/` | 刮削 NFO/海报（含 `_actress/` 女优头像） |
| `strm-library/` | 七区 STRM |

## `apps/api/_local_refs/mdcx/`

MDCX 原始映射（gitignore），导入写入 `apps/maps/scrape/` 唯一完整表：

| 文件 | 导入产物 |
|------|----------|
| `mapping_actor.xml` | `apps/maps/scrape/actors.zh-CN.json` |
| `Actress-*.db` | 同上（别名 enrichment） |
| `mapping_info.xml` | `apps/maps/scrape/tags.zh-CN.json` |
| `c_number.json` | `apps/maps/scrape/code-titles.json` |

```bash
cd apps/api
.venv/Scripts/python.exe scripts/import_mdcx_maps.py
```

## `backups/`

本机备份（勿提交）。整理脚本**只应写入本仓库内的 `backups/`**。短说明见 [`backups/README.md`](../backups/README.md)。

| 子路径 | 用途 |
|--------|------|
| `db/bitmagnet-db/` · `db/resource-db/` | 数据库导出 |
| `workspace/YYYY-MM-DD/` | 目录整理前的工作区快照 |