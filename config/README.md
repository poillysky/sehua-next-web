# config/

应用默认配置与参考 DDL（相对仓库根）。

| 路径 | 用途 | 进 git |
|------|------|--------|
| `app.json` | 管理员种子 / 默认 `settings`（首次启动写入 Postgres） | 是 |
| `app.local.example.json` | 本机覆盖示例（DSN、代理、115…） | 是 |
| `app.local.json` | 本机覆盖（勿提交） | 否 |
| `sql/` | 参考 DDL（embed / 索引）；**运行时不加载** | 是 |

业务默认值在 `app.json` 的 `settings`；局域网资源库、代理等放 `app.local.json`。  
Docker 可将本目录挂到 `/app/config`。
