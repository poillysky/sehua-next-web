# NextWeb

模版壳 iOS PWA + FastAPI。业务参考 sehua，**前端不在根目录**。内置刮削 / 片商 / 板块浏览已下线；仓库搜索、影视、设置保留。

## 目录分类

```
NextWeb/
├── apps/
│   ├── web/          # 前端 — Next.js PWA（模版壳）      :3020
│   └── api/          # 后端 — FastAPI（认证/资源/设置）  :8020
├── config/
│   └── app.json      # 管理员种子等
├── package.json      # 根脚本（转发到各 app）
└── README.md
```

| 分类 | 路径 | 端口 | 说明 |
|------|------|------|------|
| 前端 | `apps/web` | **3020** `0.0.0.0` | 模版 shell + features |
| 后端 | `apps/api` | **8020** | `/api` 由 Web rewrite 代理 |
| 数据 | Postgres | **5439** | 元库 + 资源库 DSN（默认 `nextweb`）；`data/` 仅本地缓存 |

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

环境变量见根目录 `.env.example`。元库 DSN：`SNS_META_DSN`（默认 `postgresql://postgres:postgres@192.168.2.38:5439/nextweb`）。

业务默认值写在 `config/app.json` 的 `settings`，首次启动写入 Postgres；已有配置不覆盖。局域网资源库/代理、115、TMDB 等放 `config/app.local.json`（已 gitignore，勿提交）。

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
docker build -t sehua-next-web:1.2.1 .
docker run -d --name sehua \
  -p 3020:3020 \
  -v "$PWD/data:/app/data" \
  sehua-next-web:1.2.1
```

GitHub Actions（`.github/workflows/docker-publish.yml`）在推送 `v*` 标签或手动触发时，构建并推送到 Docker Hub：

`poillysky/sehua-next-web:1.2.1`

与 sehua / Anzai 对齐：用户名默认 `poillysky`；Token 读取 `DOCKERHUB_TOKEN`（或 `DOCKERHUB_PASSWORD` / Variables / 手动 Run workflow 粘贴）。
