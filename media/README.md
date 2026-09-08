# media/

片库类目录（与 `data/` 运行时缓存分开）：

| 路径 | 说明 |
|------|------|
| `strm-library/` | 七区番号 STRM 输出（供刮削取元数据） |
| `scrap-library/` | 刮削完成后的 NFO/海报库（向量灌库） |

相对路径设置项（如 `strm-library`）解析到本目录下。Docker 请单独挂载 `media` 卷到 `/app/media`。
