# NextWeb

模版壳 iOS PWA + FastAPI + 刮削 Worker。业务参考 sehua，**前端不在根目录**。

## 目录分类

```
NextWeb/
├── apps/
│   ├── web/          # 前端 — Next.js PWA（模版壳）      :3020
│   ├── api/          # 后端 — FastAPI（认证/资源/设置）  :8020
│   └── scrape/       # 刮削 Worker — Express 封面/元数据  :9210
├── data/             # 数据 — SQLite 元库 + 本地缓存
│   ├── app.sqlite    # 用户/会话/配置（非资源正文）
│   ├── library/      # 刮削导出库（可选）
│   ├── maker-fs/     # 厂牌前缀索引（可选）
│   └── scrape_maps/  # 刮削映射缓存（可选）
├── config/
│   └── app.json      # 管理员种子等
├── package.json      # 根脚本（转发到各 app）
└── README.md
```

| 分类 | 路径 | 端口 | 说明 |
|------|------|------|------|
| 前端 | `apps/web` | **3020** `0.0.0.0` | 模版 shell + features |
| 后端 | `apps/api` | **8020** | `/api` 由 Web rewrite 代理 |
| 刮削 | `apps/scrape` | **9210** | 仅本机；API 经 `SCRAPE_ORIGIN` 调用 |
| 数据 | `data/` | — | SQLite 元库；资源在 Postgres |

## 启动

```bash
# 1) 后端
npm run dev:api

# 2) 刮削（可选；设置里刮封面才需要）
cd apps/scrape && npm install && cd ../..
npm run dev:scrape

# 3) 前端
npm run dev
```

- Web：`http://localhost:3020`
- API health：`http://localhost:8020/health`
- Scrape health：`http://127.0.0.1:9210/health`

默认管理员：`admin` / `admin123456`（见 `config/app.json`）。

环境变量见根目录 `.env.example`。

业务默认值写在 `config/app.json` 的 `settings`（资源库 / 论坛地区 / 刮削等），首次启动写入 SQLite；已有配置不覆盖。`config/app.local.json` 可覆盖敏感项（115 / TMDB，勿提交）。强制重种：在 config 加 `"seed_settings_on_boot": true` 后重启 API。

## Docker（单镜像）

一个镜像同时跑 **web + api + scrape**（supervisord），对外只暴露 **3020**。

### NAS（`/vol1/1000/Docker/sehua-next-web`）

```bash
mkdir -p /vol1/1000/Docker/sehua-next-web/{data,scrape-data,config}
# 放入 docker-compose.yml，并把仓库 config/app.json 拷到 config/
cd /vol1/1000/Docker/sehua-next-web
docker compose pull
docker compose up -d
```

`restart: always`；数据卷为绝对路径。资源库是**独立 Postgres**，用局域网 DSN（默认 `192.168.2.38:5435/ed2k`，见 `config/app.json`），不依赖主栈 Docker 网络。

### 本地

```bash
docker build -t sehua-next-web:1.0.0 .
docker run -d --name sehua \
  -p 3020:3020 \
  -v "$PWD/data:/app/data" \
  -v sehua-scrape:/app/apps/scrape/data \
  sehua-next-web:1.0.0
```

GitHub Actions（`.github/workflows/docker-publish.yml`）在推送 `v*` 标签或手动触发时，构建并推送到 Docker Hub：

`poillysky/sehua-next-web:1.0.0`

与 sehua / Anzai 对齐：用户名默认 `poillysky`；Token 读取 `DOCKERHUB_TOKEN`（或 `DOCKERHUB_PASSWORD` / Variables / 手动 Run workflow 粘贴）。
