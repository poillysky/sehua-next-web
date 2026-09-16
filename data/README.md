# `data/` — 本机运行时（默认不进 git）

按用途分层；真相源映射在 `apps/maps/`，片库在 `media/`。

```
data/
  meta/                 # cf-clearance 等会话态
  mirrors/              # site-mirrors.json · iqqtv-mirror.json
  prefix/
    catalog/            # 七区前缀→番号目录（catalog.json）
    code-ranges.json    # 前缀流水号上限缓存
  cache/
    cover/              # 封面缩略缓存
    facets/             # 刮削库分面快照
  presets/              # 本机预设（如 openai）
  debug/                # 脚本报告 / 探针输出
```

从 MDCX 导入演员/标签/标题（写入 `apps/maps/scrape/`，不是这里）：

```bash
cd apps/api && .venv/Scripts/python.exe scripts/import_mdcx_maps.py
```

片库见 [`media/README.md`](../media/README.md)；约定见 [`docs/local-runtime.md`](../docs/local-runtime.md)。
