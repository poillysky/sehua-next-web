# scrape-meta — 本机 ↔ NAS 共用的「可移植」镜像缓存

启动时 scrape / entrypoint 会把本目录文件灌进 `scrape-data/meta/`（缺文件或 FORCE 时）。

## 同步什么

| 文件 | 同步？ | 作用 |
|------|--------|------|
| `airav-mirror.json` | ✅ | Airav 非官方镜像，NAS curl 直链靠它 |
| `iqqtv-mirror.json` | ✅ | iqqtv 镜像 |
| `site-mirrors.json` | ✅ | 各站当前基址 |
| `cf-clearance.json` | ❌ | Cloudflare 通行证绑出口 IP，本机拷 NAS 常无效 |

## 怎么用

1. **本机**重测 Airav_io 等到「curl直连」，且 `apps/scrape/data/meta/` 里已有上述 json  
2. 调用导出（任选）：
   - `POST http://127.0.0.1:9210/api/meta/export-seed`  
   - 或手动复制三个 json 到本目录  
3. 把整个 `config/scrape-meta/` 拷到 NAS 的  
   `/vol1/1000/Docker/sehua-next-web/config/scrape-meta/`  
4. NAS 重启容器（或 `SCRAPE_META_SEED_FORCE=1` 后 `POST .../api/meta/import-seed`）  
5. 再重测 Airav_io，应优先打镜像 → curl 直链  

说明：本机 Windows curl 有时能直接打 `airav.io`，NAS Linux curl 不行——所以一定要有一份**非官方** `airav-mirror.json`，光同步「代码一样」不够。
