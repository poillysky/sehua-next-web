# NextWeb

模版壳 iOS PWA + FastAPI。业务参考 sehua，**前端不在根目录**。刮削改由外部 **MDC-ng** 写入 `library/`，本仓库不再内置 scrape Worker。

## 目录分类

```
NextWeb/
├── apps/
│   ├── web/          # 前端 — Next.js PWA（模版壳）      :3020
│   └── api/          # 后端 — FastAPI（认证/资源/设置）  :8020
├── data/             # 数据 — SQLite 元库 + 本地缓存
│   ├── app.sqlite    # 用户/会话/配置（非资源正文）
│   ├── library/      # MDC-ng 刮削导出库（可选）
│   └── maker-fs/     # 厂牌前缀索引（可选）
├── config/
│   └── app.json      # 管理员种子等
├── package.json      # 根脚本（转发到各 app）
└── README.md
```

| 分类 | 路径 | 端口 | 说明 |
|------|------|------|------|
| 前端 | `apps/web` | **3020** `0.0.0.0` | 模版 shell + features |
| 后端 | `apps/api` | **8020** | `/api` 由 Web rewrite 代理 |
| 数据 | `data/` | — | SQLite 元库；资源在 Postgres |

## 启动

### 一键（Windows）

双击根目录 `start-dev.cmd`（或 `npm run dev:all`）。会释放端口、开 2 个控制台窗口，并在健康后打开浏览器。

```bat
start-dev.cmd
start-dev.cmd -NoBrowser
stop-dev.cmd
```

### 分步

```bash
npm run dev:api   # 8020
npm run dev       # 3020
```

- Web：`http://localhost:3020`
- API health：`http://localhost:8020/health`

默认管理员：`admin` / `admin123456`（见 `config/app.json`）。

环境变量见根目录 `.env.example`。

业务默认值写在 `config/app.json` 的 `settings`，首次启动写入 SQLite；已有配置不覆盖。局域网 DSN、代理、115、TMDB 等放 `config/app.local.json`（已 gitignore，勿提交）。

## Docker（单镜像）

一个镜像同时跑 **web + api**（supervisord），对外只暴露 **3020**。健康检查探测 web / api 两端。

### NAS（`/vol1/1000/Docker/sehua-next-web`）

```bash
mkdir -p /vol1/1000/Docker/sehua-next-web/{data,config}
cd /vol1/1000/Docker/sehua-next-web
docker compose pull
docker compose up -d
```

`restart: always`；数据卷为绝对路径。资源库是**独立 Postgres**，在设置页或 `app.local.json` 填局域网 DSN。

### 本地

```bash
docker build -t sehua-next-web:1.0.18 .
docker run -d --name sehua \
  -p 3020:3020 \
  -v "$PWD/data:/app/data" \
  sehua-next-web:1.0.18
```

GitHub Actions（`.github/workflows/docker-publish.yml`）在推送 `v*` 标签或手动触发时，构建并推送到 Docker Hub：

`poillysky/sehua-next-web:1.0.18`

与 sehua / Anzai 对齐：用户名默认 `poillysky`；Token 读取 `DOCKERHUB_TOKEN`（或 `DOCKERHUB_PASSWORD` / Variables / 手动 Run workflow 粘贴）。
