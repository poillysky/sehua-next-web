# 映射表约定

- **唯一位置**：[`apps/maps/`](../apps/maps/README.md)（演员 / 标签 / 番号标题都在 `scrape/`）
- **禁止**再搞 `data/scrape_maps/` 演员·标签·标题兜底副本
- 逻辑名：`app.core.maps_paths.maps_seed(...)` / `load_json_map(...)`
- 前缀目录等其它运行时：仓库根 `data/prefix/`（`catalog/`、`code-ranges.json`）

## MDCX 大表

```bash
cd apps/api
.venv/Scripts/python.exe scripts/import_mdcx_maps.py
```

| 产物 | 路径 |
|------|------|
| 演员 | `apps/maps/scrape/actors.zh-CN.json` |
| 标签 | `apps/maps/scrape/tags.zh-CN.json` |
| 番号标题 | `apps/maps/scrape/code-titles.json` |

人工修正直接改 `apps/maps/scrape/actors.zh-CN.json` / `tags.zh-CN.json`（只维护主表）。

## code-titles 质量审查

完整要求与进度见：
[`apps/api/_gap_reports/title_batches/review_non_mdcx/REVIEW_LOG.md`](../apps/api/_gap_reports/title_batches/review_non_mdcx/REVIEW_LOG.md)

摘要：

- 只审 **非 MDCX** 条目；MDCX `c_number` 重叠项不碰。
- **必须逐条通读标题**，禁止用正则/脚本代替审查。
- 每批 2000；按 chunk 读；改完写回本日志。
