# apps/maps — 映射表（按目录分类，各表唯一一份）

```
apps/maps/
  makers/     厂牌展示 + av-makers 注册表
  prefixes/   前缀展示 / 目录种子 / 形状 / 流水号 / code-read
  scrape/     演员 · 标签 · 番号标题 · 繁简折叠
  regions/    七区元数据
  sites/      站源专用（DMM / R18 / ThePornDB / 色花堂）
```

逻辑名仍可由 `app.core.maps_paths.maps_seed("makers.json")` 解析到子目录。

## 目录说明

| 目录 | 文件 | 用途 |
|------|------|------|
| `makers/` | `makers.json` | 厂牌 i18n / intro / card / aliases |
| | `av-makers.{japan,china,western}.json` | 厂牌前缀注册 |
| `prefixes/` | `prefixes.json` | 前缀 i18n / intro / studioOverrides |
| | `catalog.seed.json` | 七区前缀目录种子 |
| | `code-ranges.json` | 流水号上限种子 |
| | `code-shapes.json` | 番号形状 / 欧美前缀 / skip |
| | `code-read.json` | 扫描 code_read 预设 |
| `scrape/` | `actors.zh-CN.json` | 演员完整表（MDCX 导入；人工也改这张；条目可带 `avatar` 直链） |
| | `tags.zh-CN.json` | 标签完整表 |
| | `code-titles.json` | 番号→中文标题（c_number） |
| | `code-actors.json` | 番号→女优名单（av_metadata 导出；存原始日文名，消费时走演员映射链） |
| | `tags.variant-fold.zh-CN.json` | 繁简折叠 |
| `regions/` | `regions.json` | 七区 order / meta / aliases |
| `sites/` | `dmm-series-digit.json` 等 | 站源专用 |

**不要**再维护 `data/scrape_maps/` 演员/标签/标题副本；运行时只读 `apps/maps/`。

## 从 MDCX 导入

源在 `apps/api/_local_refs/mdcx/`（不进 git）：

```bash
cd apps/api
.venv/Scripts/python.exe scripts/import_mdcx_maps.py
```

直接写回 `apps/maps/scrape/`。详见 [`docs/scrape-maps.md`](../../docs/scrape-maps.md)。

人工字段（当前为 `avatar` 头像直链）在重导时按**标准名**自动保留，不会被覆盖。
头像种子已并入 `actors.zh-CN.json`，不再单独维护
（旧 `scrape/actress-avatar-urls.json` 已删除）。

运行时其它覆盖：`data/prefix/code-ranges.json`、`data/prefix/catalog/`。
