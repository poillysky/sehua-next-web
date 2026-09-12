# 演员 / 标签映射

## 加载顺序

`apps/api/app/scrape_metadata_optimize.py`：

1. **`data/scrape_maps/actors.{lang}.json`**（或 `actors.json`）— 有则**只用这份**
2. 否则回退 **`apps/api/app/scrape_maps_seed/actors.{lang}.json`**

标签同理：`tags.{lang}.json` / `tags.json`。  
语言来自设置 `mappingLanguage`（默认 `zh-CN`）。

> 注意：`data/` 与 seed **不会自动合并**。本机有 data 文件时，seed 整份不生效。

## 各类文件职责

| 文件 | 位置 | 职责 |
|------|------|------|
| 运行时演员表 | `data/scrape_maps/actors.zh-CN.json` | 正式用；可含 MDCX 导入的大表 + 人工修正 |
| 运行时标签表 | `data/scrape_maps/tags.zh-CN.json` | 正式用；无则用 seed |
| 种子演员 | `apps/api/app/scrape_maps_seed/actors.zh-CN.json` | 仓库默认（drop/男优噪音等，体量小） |
| 种子标签 | `apps/api/app/scrape_maps_seed/tags.zh-CN.json` | 仓库默认（繁简/同义，约数百条） |
| MDCX XML/DB | `apps/api/_local_refs/mdcx/` | 生成大表的源，不进 git |

## 从 MDCX 生成演员表

```bash
cd apps/api
.venv/Scripts/python.exe scripts/build_actor_map_from_mdcx.py
```

默认读 `_local_refs/mdcx/mapping_actor.xml`（及可选 Actress.db），写出到 `data/scrape_maps/actors.zh-CN.json`。  
旧路径 `_gap_reports/_mdcx_*` 仍作兼容回退。

## 条目形态（简述）

- 演员：别名键 → `{ name, zh, jp?, drop?, role?, sex?, … }`
- 标签：异写键 → 标准简中字符串，或带 `drop` 的对象

设置里的「优化女优元数据」会走上述映射表清洗向量/NFO 中的女优名。
