# docker/

单镜像运行时脚本（由根目录 `Dockerfile` 复制进镜像）。

| 文件 | 用途 |
|------|------|
| `entrypoint.sh` | 容器入口；按 `APP_ROLE=ui\|worker` 选 supervisord 配置 |
| `healthcheck.sh` | 健康检查（UI：web+api；Worker：仅 api） |
| `supervisord.conf` | UI：同时拉起 web + api |
| `supervisord-worker.conf` | Worker：仅 api（刮削/扫描重活） |

**构建 / 编排入口在仓库根**（勿挪进本目录，以免破坏 NAS 与 CI 路径）：

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

本地或 NAS 用法见根 [`README.md`](../README.md) 的 Docker 一节。
