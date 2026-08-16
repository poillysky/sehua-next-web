/**
 * 把可移植的镜像缓存从 config/scrape-meta 灌进 scrape data/meta。
 * 本机与 NAS 共用同一份 seed → 行为对齐（curl 直链依赖镜像地址，不依赖 cf_clearance）。
 *
 * 不复制 cf-clearance.json：通行证绑出口 IP / TLS，拷了也常无效甚至误导。
 */

import fs from "node:fs";
import path from "node:path";

const PORTABLE = [
  "airav-mirror.json",
  "iqqtv-mirror.json",
  "site-mirrors.json",
] as const;

function seedDirs(metaDir: string, appRoot: string): string[] {
  const out: string[] = [];
  const env = String(process.env.SCRAPE_META_SEED_DIR || "").trim();
  if (env) out.push(env);
  const cfg = String(process.env.CONFIG_DIR || "").trim();
  if (cfg) out.push(path.join(cfg, "scrape-meta"));
  out.push("/app/config/scrape-meta");
  // 本机 monorepo：apps/scrape → ../../config/scrape-meta
  out.push(path.resolve(appRoot, "../../config/scrape-meta"));
  out.push(path.resolve(metaDir, "../../../config/scrape-meta"));
  return [...new Set(out.map((p) => path.resolve(p)))];
}

function readJson(file: string): unknown | null {
  try {
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
  } catch {
    return null;
  }
}

function shouldReplaceAirav(destPath: string, seedPath: string): boolean {
  const force = /^(1|true|yes)$/i.test(
    String(process.env.SCRAPE_META_SEED_FORCE || "").trim(),
  );
  if (force) return true;
  if (!fs.existsSync(destPath)) return true;
  const dest = readJson(destPath) as { baseUrl?: string } | null;
  const seed = readJson(seedPath) as { baseUrl?: string } | null;
  const d = String(dest?.baseUrl || "");
  const s = String(seed?.baseUrl || "");
  if (!s) return false;
  // 目标是官方或空，种子是非空 → 用种子
  if (!d) return true;
  try {
    const dh = new URL(d).hostname.replace(/^www\./i, "").toLowerCase();
    if (dh === "airav.io") return true;
  } catch {
    return true;
  }
  return false;
}

function mergeSiteMirrors(destPath: string, seedPath: string): boolean {
  const force = /^(1|true|yes)$/i.test(
    String(process.env.SCRAPE_META_SEED_FORCE || "").trim(),
  );
  const seed = readJson(seedPath) as {
    version?: number;
    mirrors?: Record<string, { baseUrl?: string; updatedAt?: string; expiresAt?: number }>;
  } | null;
  if (!seed?.mirrors || typeof seed.mirrors !== "object") return false;

  if (!fs.existsSync(destPath) || force) {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    fs.copyFileSync(seedPath, destPath);
    return true;
  }

  const dest = (readJson(destPath) as {
    version?: number;
    mirrors?: Record<string, { baseUrl?: string; updatedAt?: string; expiresAt?: number }>;
  } | null) || { version: 1, mirrors: {} };
  dest.mirrors = dest.mirrors || {};
  let changed = false;
  for (const [id, hit] of Object.entries(seed.mirrors)) {
    const url = String(hit?.baseUrl || "").trim();
    if (!url) continue;
    const cur = dest.mirrors[id];
    if (!cur?.baseUrl) {
      dest.mirrors[id] = hit;
      changed = true;
    }
  }
  if (changed) {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    fs.writeFileSync(destPath, JSON.stringify(dest, null, 2), "utf8");
  }
  return changed;
}

/** 启动时调用：用 config/scrape-meta 对齐本机/NAS 镜像缓存 */
export function seedPortableMetaFromConfig(metaDir: string, appRoot: string): void {
  const dirs = seedDirs(metaDir, appRoot).filter((d) => fs.existsSync(d));
  if (!dirs.length) return;

  fs.mkdirSync(metaDir, { recursive: true });
  let applied = 0;

  for (const dir of dirs) {
    for (const name of PORTABLE) {
      const seedPath = path.join(dir, name);
      if (!fs.existsSync(seedPath)) continue;
      const destPath = path.join(metaDir, name);

      if (name === "site-mirrors.json") {
        if (mergeSiteMirrors(destPath, seedPath)) {
          console.log(`[scrape] meta-seed merge ${name} ← ${dir}`);
          applied += 1;
        }
        continue;
      }

      if (name === "airav-mirror.json") {
        if (!shouldReplaceAirav(destPath, seedPath)) continue;
        fs.copyFileSync(seedPath, destPath);
        console.log(`[scrape] meta-seed ${name} ← ${dir}`);
        applied += 1;
        continue;
      }

      // iqqtv 等：缺文件才拷；FORCE 时覆盖
      const force = /^(1|true|yes)$/i.test(
        String(process.env.SCRAPE_META_SEED_FORCE || "").trim(),
      );
      if (!force && fs.existsSync(destPath)) continue;
      fs.copyFileSync(seedPath, destPath);
      console.log(`[scrape] meta-seed ${name} ← ${dir}`);
      applied += 1;
    }
    // 多 seed 目录时：用第一个有内容的即可
    if (applied > 0) break;
  }

  if (applied > 0) {
    console.log(`[scrape] meta-seed applied ${applied} file(s) (cf-clearance 不共享)`);
  }
}

export function exportPortableMeta(metaDir: string, outDir: string): string[] {
  fs.mkdirSync(outDir, { recursive: true });
  const copied: string[] = [];
  for (const name of PORTABLE) {
    const src = path.join(metaDir, name);
    if (!fs.existsSync(src)) continue;
    fs.copyFileSync(src, path.join(outDir, name));
    copied.push(name);
  }
  return copied;
}
