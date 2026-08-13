import fs from "node:fs";
import path from "node:path";
import {
  applyFlareSolverr,
  getFlareSolverrUrl,
  normalizeFlareUrl,
} from "./flaresolverr.js";
import { applyProxy, getActiveProxy, normalizeProxyUrl } from "./proxy.js";

export type NetworkConfig = {
  flareSolverrUrl: string;
  proxyUrl: string;
};

let storePath = "";

export function setNetworkStorePath(filePath: string): void {
  storePath = filePath;
}

export function readNetworkFile(): NetworkConfig | null {
  if (!storePath || !fs.existsSync(storePath)) return null;
  try {
    const raw = JSON.parse(fs.readFileSync(storePath, "utf8")) as Partial<NetworkConfig>;
    return {
      flareSolverrUrl: normalizeFlareUrl(raw.flareSolverrUrl),
      proxyUrl: normalizeProxyUrl(raw.proxyUrl),
    };
  } catch {
    return null;
  }
}

export function writeNetworkFile(cfg: NetworkConfig): void {
  if (!storePath) return;
  try {
    fs.mkdirSync(path.dirname(storePath), { recursive: true });
    const tmp = `${storePath}.tmp`;
    fs.writeFileSync(
      tmp,
      JSON.stringify(
        {
          flareSolverrUrl: cfg.flareSolverrUrl || "",
          proxyUrl: cfg.proxyUrl || "",
          updatedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
      "utf8",
    );
    fs.renameSync(tmp, storePath);
  } catch (e) {
    console.warn(
      "[scrape] network.json write failed:",
      e instanceof Error ? e.message : e,
    );
  }
}

/** 启动：磁盘配置覆盖 env（与设置→网络管理对齐） */
export function loadPersistedNetwork(): NetworkConfig {
  const file = readNetworkFile();
  if (!file) {
    return {
      flareSolverrUrl: getFlareSolverrUrl() || "",
      proxyUrl: getActiveProxy() || "",
    };
  }
  applyFlareSolverr(file.flareSolverrUrl);
  applyProxy(file.proxyUrl);
  console.log(
    `[scrape] network restored flare=${file.flareSolverrUrl || "(none)"} proxy=${file.proxyUrl || "(direct)"}`,
  );
  return file;
}

export function persistActiveNetwork(): NetworkConfig {
  const cfg = {
    flareSolverrUrl: getFlareSolverrUrl() || "",
    proxyUrl: getActiveProxy() || "",
  };
  writeNetworkFile(cfg);
  return cfg;
}
