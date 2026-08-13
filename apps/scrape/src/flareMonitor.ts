/**
 * FlareSolverr 智能监控：
 * - 会话数 / 延迟 / 错误率（始终可用）
 * - CPU/内存：FLARESOLVERR_STATS_CMD 或 SSH+docker stats（可选）
 * - 过载先回收会话（降内存），仍严重且配置了重启命令则自动重启
 */
import { exec as execCb } from "node:child_process";
import { promisify } from "node:util";
import {
  getFlareSolverrUrl,
  getFlareTrafficStats,
  getSharedSessionId,
  listFlareSessions,
  recycleFlareSessions,
} from "./flaresolverr.js";

const exec = promisify(execCb);

export type FlareHostStats = {
  cpuPercent: number | null;
  memPercent: number | null;
  memUsedMb: number | null;
  source: string;
};

export type FlareMonitorSnapshot = {
  ok: boolean;
  flareSolverrUrl: string;
  reachable: boolean;
  sessions: number;
  ownedSession: string | null;
  orphanSessions: number;
  latencyAvgMs: number;
  latencyP95Ms: number;
  errorRate: number;
  trafficSample: number;
  cpuPercent: number | null;
  memPercent: number | null;
  memUsedMb: number | null;
  statsSource: string;
  level: "ok" | "warn" | "critical" | "down";
  reasons: string[];
  lastAction: string | null;
  lastActionAt: string | null;
  lastActionDetail: string | null;
  restartConfigured: boolean;
  autoEnabled: boolean;
  checkedAt: string;
};

type MonitorConfig = {
  intervalMs: number;
  maxSessionsWarn: number;
  maxSessionsCritical: number;
  cpuWarn: number;
  cpuCritical: number;
  memWarn: number;
  memCritical: number;
  latencyWarnMs: number;
  latencyCriticalMs: number;
  errorRateWarn: number;
  errorRateCritical: number;
  restartCooldownMs: number;
  autoEnabled: boolean;
  statsCmd: string;
  restartCmd: string;
  ssh: string;
  dockerName: string;
};

function envNum(name: string, fallback: number): number {
  const n = Number(process.env[name]);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function readConfig(): MonitorConfig {
  const autoRaw = String(process.env.FLARESOLVERR_AUTO_MANAGE || "1").trim();
  return {
    intervalMs: envNum("FLARESOLVERR_MONITOR_INTERVAL_MS", 30_000),
    maxSessionsWarn: envNum("FLARESOLVERR_MAX_SESSIONS_WARN", 2),
    maxSessionsCritical: envNum("FLARESOLVERR_MAX_SESSIONS_CRITICAL", 3),
    cpuWarn: envNum("FLARESOLVERR_CPU_WARN", 80),
    cpuCritical: envNum("FLARESOLVERR_CPU_CRITICAL", 92),
    memWarn: envNum("FLARESOLVERR_MEM_WARN", 75),
    memCritical: envNum("FLARESOLVERR_MEM_CRITICAL", 88),
    // CF 过盾常 25–60s；过低会误判「过载」并毁掉可复用 session
    latencyWarnMs: envNum("FLARESOLVERR_LATENCY_WARN_MS", 60_000),
    latencyCriticalMs: envNum("FLARESOLVERR_LATENCY_CRITICAL_MS", 120_000),
    errorRateWarn: envNum("FLARESOLVERR_ERROR_RATE_WARN", 0.3),
    errorRateCritical: envNum("FLARESOLVERR_ERROR_RATE_CRITICAL", 0.55),
    restartCooldownMs: envNum("FLARESOLVERR_RESTART_COOLDOWN_MS", 5 * 60_000),
    autoEnabled: !(autoRaw === "0" || /^false|off|no$/i.test(autoRaw)),
    statsCmd: String(process.env.FLARESOLVERR_STATS_CMD || "").trim(),
    restartCmd: String(process.env.FLARESOLVERR_RESTART_CMD || "").trim(),
    ssh: String(process.env.FLARESOLVERR_SSH || "").trim(),
    dockerName: String(process.env.FLARESOLVERR_DOCKER_NAME || "flaresolverr").trim(),
  };
}

let timer: ReturnType<typeof setInterval> | null = null;
let ticking = false;
let lastAction: string | null = null;
let lastActionAt: string | null = null;
let lastActionDetail: string | null = null;
let lastRestartAt = 0;
let lastSnapshot: FlareMonitorSnapshot | null = null;

function flareHostIsLocal(flareUrl: string): boolean {
  try {
    const host = new URL(flareUrl).hostname.toLowerCase();
    return (
      host === "127.0.0.1" ||
      host === "localhost" ||
      host === "::1" ||
      host === "0.0.0.0"
    );
  } catch {
    return false;
  }
}

async function runShell(
  cmd: string,
  timeoutMs = 25_000,
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  try {
    const { stdout, stderr } = await exec(cmd, {
      timeout: timeoutMs,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
    });
    return {
      ok: true,
      stdout: String(stdout || ""),
      stderr: String(stderr || ""),
    };
  } catch (e) {
    const err = e as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      stdout: String(err.stdout || ""),
      stderr: String(err.stderr || err.message || e),
    };
  }
}

function parseStatsJson(raw: string): FlareHostStats | null {
  const text = String(raw || "").trim();
  if (!text) return null;
  // 允许前后夹杂日志：取第一段 {…}
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try {
    const j = JSON.parse(m[0]) as Record<string, unknown>;
    const cpu = Number(j.cpu ?? j.cpuPercent ?? j.CPUPerc);
    const mem = Number(j.mem ?? j.memPercent ?? j.MemPerc);
    const used = Number(j.memUsedMb ?? j.mem_used_mb ?? j.usedMb);
    return {
      cpuPercent: Number.isFinite(cpu) ? cpu : null,
      memPercent: Number.isFinite(mem) ? mem : null,
      memUsedMb: Number.isFinite(used) ? used : null,
      source: "json",
    };
  } catch {
    return null;
  }
}

function parseDockerStatsLine(line: string): FlareHostStats | null {
  // NAME CPU% MEM% MEM USAGE
  // flaresolverr 12.34% 45.67% 1.2GiB / 7.7GiB
  const s = line.trim();
  if (!s) return null;
  const cpuM = s.match(/([\d.]+)\s*%/);
  const memMs = [...s.matchAll(/([\d.]+)\s*%/g)];
  const memM = memMs.length >= 2 ? memMs[1] : null;
  const usageM = s.match(/([\d.]+)\s*(GiB|MiB|GB|MB)/i);
  let memUsedMb: number | null = null;
  if (usageM) {
    const n = Number(usageM[1]);
    const unit = usageM[2].toLowerCase();
    if (Number.isFinite(n)) {
      memUsedMb =
        unit.startsWith("g") ? Math.round(n * 1024) : Math.round(n);
    }
  }
  return {
    cpuPercent: cpuM ? Number(cpuM[1]) : null,
    memPercent: memM ? Number(memM[1]) : null,
    memUsedMb,
    source: "docker-stats",
  };
}

async function probeHostStats(cfg: MonitorConfig): Promise<FlareHostStats> {
  const empty: FlareHostStats = {
    cpuPercent: null,
    memPercent: null,
    memUsedMb: null,
    source: "none",
  };
  if (cfg.statsCmd) {
    const r = await runShell(cfg.statsCmd);
    const parsed = parseStatsJson(r.stdout) || parseDockerStatsLine(r.stdout);
    if (parsed) return { ...parsed, source: `cmd:${cfg.statsCmd.slice(0, 40)}` };
  }

  const flare = getFlareSolverrUrl();
  const docker = cfg.dockerName || "flaresolverr";

  if (flare && flareHostIsLocal(flare)) {
    const r = await runShell(
      `docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemPerc}} {{.MemUsage}}" ${docker}`,
    );
    if (r.ok) {
      const parsed = parseDockerStatsLine(r.stdout);
      if (parsed) return { ...parsed, source: "local-docker" };
    }
  }

  if (cfg.ssh) {
    // BatchMode：无交互密钥；失败则静默无指标
    const remote = `docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemPerc}} {{.MemUsage}}' ${docker}`;
    const r = await runShell(
      `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 ${cfg.ssh} ${JSON.stringify(remote)}`,
      30_000,
    );
    if (r.ok) {
      const parsed = parseDockerStatsLine(r.stdout);
      if (parsed) return { ...parsed, source: `ssh:${cfg.ssh}` };
    }
  }

  return empty;
}

function buildRestartCommand(cfg: MonitorConfig): string {
  if (cfg.restartCmd) return cfg.restartCmd;
  if (cfg.ssh) {
    const docker = cfg.dockerName || "flaresolverr";
    return `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 ${cfg.ssh} ${JSON.stringify(`docker restart ${docker}`)}`;
  }
  const flare = getFlareSolverrUrl();
  if (flare && flareHostIsLocal(flare)) {
    return `docker restart ${cfg.dockerName || "flaresolverr"}`;
  }
  return "";
}

function evaluateLevel(
  snap: Omit<
    FlareMonitorSnapshot,
    "level" | "reasons" | "lastAction" | "lastActionAt" | "lastActionDetail" | "checkedAt"
  >,
  cfg: MonitorConfig,
): { level: FlareMonitorSnapshot["level"]; reasons: string[] } {
  if (!snap.reachable) {
    return { level: "down", reasons: ["FlareSolverr 不可达"] };
  }
  const reasons: string[] = [];
  let critical = false;
  let warn = false;

  if (snap.sessions >= cfg.maxSessionsCritical) {
    critical = true;
    reasons.push(`会话过多 ${snap.sessions}`);
  } else if (snap.sessions >= cfg.maxSessionsWarn) {
    warn = true;
    reasons.push(`会话偏多 ${snap.sessions}`);
  }

  if (snap.cpuPercent != null) {
    if (snap.cpuPercent >= cfg.cpuCritical) {
      critical = true;
      reasons.push(`CPU ${snap.cpuPercent.toFixed(0)}%`);
    } else if (snap.cpuPercent >= cfg.cpuWarn) {
      warn = true;
      reasons.push(`CPU ${snap.cpuPercent.toFixed(0)}%`);
    }
  }
  if (snap.memPercent != null) {
    if (snap.memPercent >= cfg.memCritical) {
      critical = true;
      reasons.push(`内存 ${snap.memPercent.toFixed(0)}%`);
    } else if (snap.memPercent >= cfg.memWarn) {
      warn = true;
      reasons.push(`内存 ${snap.memPercent.toFixed(0)}%`);
    }
  }
  if (snap.trafficSample >= 3) {
    if (snap.latencyAvgMs >= cfg.latencyCriticalMs) {
      critical = true;
      reasons.push(`延迟 ${Math.round(snap.latencyAvgMs / 1000)}s`);
    } else if (snap.latencyAvgMs >= cfg.latencyWarnMs) {
      warn = true;
      reasons.push(`延迟 ${Math.round(snap.latencyAvgMs / 1000)}s`);
    }
    if (snap.errorRate >= cfg.errorRateCritical) {
      critical = true;
      reasons.push(`错误率 ${(snap.errorRate * 100).toFixed(0)}%`);
    } else if (snap.errorRate >= cfg.errorRateWarn) {
      warn = true;
      reasons.push(`错误率 ${(snap.errorRate * 100).toFixed(0)}%`);
    }
  }

  if (critical) return { level: "critical", reasons };
  if (warn) return { level: "warn", reasons };
  return { level: "ok", reasons: reasons.length ? reasons : ["正常"] };
}

async function probeReachable(): Promise<boolean> {
  const flare = getFlareSolverrUrl();
  if (!flare) return false;
  try {
    const sessions = await listFlareSessions();
    void sessions;
    return true;
  } catch {
    return false;
  }
}

export async function collectFlareMonitorSnapshot(): Promise<FlareMonitorSnapshot> {
  const cfg = readConfig();
  const flare = getFlareSolverrUrl();
  const traffic = getFlareTrafficStats();
  const owned = getSharedSessionId();
  let sessions: string[] = [];
  let reachable = false;
  if (flare) {
    try {
      sessions = await listFlareSessions();
      reachable = true;
    } catch {
      reachable = false;
    }
  }
  const host = await probeHostStats(cfg);
  const base = {
    ok: Boolean(flare) && reachable,
    flareSolverrUrl: flare || "",
    reachable,
    sessions: sessions.length,
    ownedSession: owned,
    orphanSessions: sessions.filter((id) => id !== owned).length,
    latencyAvgMs: traffic.avgMs,
    latencyP95Ms: traffic.p95Ms,
    errorRate: traffic.errorRate,
    trafficSample: traffic.sample,
    cpuPercent: host.cpuPercent,
    memPercent: host.memPercent,
    memUsedMb: host.memUsedMb,
    statsSource: host.source,
    restartConfigured: Boolean(buildRestartCommand(cfg)),
    autoEnabled: cfg.autoEnabled,
  };
  const { level, reasons } = evaluateLevel(base, cfg);
  const snap: FlareMonitorSnapshot = {
    ...base,
    level,
    reasons,
    lastAction,
    lastActionAt,
    lastActionDetail,
    checkedAt: new Date().toISOString(),
  };
  lastSnapshot = snap;
  return snap;
}

function rememberAction(action: string, detail: string): void {
  lastAction = action;
  lastActionAt = new Date().toISOString();
  lastActionDetail = detail;
  console.log(`[scrape] flare-monitor ${action}: ${detail}`);
}

export async function recycleFlareNow(
  reason = "manual",
  opts?: { keepOwned?: boolean },
): Promise<{
  ok: boolean;
  destroyed: number;
  message: string;
}> {
  try {
    const keepOwned = opts?.keepOwned === true;
    const r = await recycleFlareSessions({ keepOwned });
    rememberAction(
      "recycle",
      `${reason} · destroyed=${r.destroyed} before=${r.sessionsBefore} keepOwned=${keepOwned}`,
    );
    return {
      ok: true,
      destroyed: r.destroyed,
      message: keepOwned
        ? `已清理 ${r.destroyed} 个孤儿会话`
        : `已回收 ${r.destroyed} 个会话`,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    rememberAction("recycle-failed", msg);
    return { ok: false, destroyed: 0, message: msg };
  }
}

export async function restartFlareNow(reason = "manual"): Promise<{
  ok: boolean;
  message: string;
  cmd: string;
}> {
  const cfg = readConfig();
  const cmd = buildRestartCommand(cfg);
  if (!cmd) {
    return {
      ok: false,
      message:
        "未配置重启命令。请设置 FLARESOLVERR_RESTART_CMD 或 FLARESOLVERR_SSH（docker restart）",
      cmd: "",
    };
  }
  const now = Date.now();
  if (reason !== "manual" && now - lastRestartAt < cfg.restartCooldownMs) {
    return {
      ok: false,
      message: `重启冷却中（${Math.ceil((cfg.restartCooldownMs - (now - lastRestartAt)) / 1000)}s）`,
      cmd,
    };
  }
  // 先清会话，减少重启时残留 Chrome
  try {
    await recycleFlareSessions({ keepOwned: false });
  } catch {
    /* ignore */
  }
  const r = await runShell(cmd, 60_000);
  if (!r.ok) {
    rememberAction("restart-failed", r.stderr || "restart failed");
    return { ok: false, message: r.stderr || "重启失败", cmd };
  }
  lastRestartAt = now;
  rememberAction("restart", `${reason} · ${cmd.slice(0, 80)}`);
  // 等 FS 起来
  for (let i = 0; i < 20; i++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (await probeReachable()) break;
  }
  return { ok: true, message: "已触发重启并等待恢复", cmd };
}

async function autoRemediate(snap: FlareMonitorSnapshot): Promise<void> {
  const cfg = readConfig();
  if (!cfg.autoEnabled || !snap.flareSolverrUrl) return;

  // 孤儿会话：只清别人的 Chrome，保留本进程正在用的 shared session
  if (snap.orphanSessions > 0) {
    await recycleFlareNow("orphan-prune", { keepOwned: true });
    // 清完再评估是否还要全量回收
    const again = await collectFlareMonitorSnapshot();
    if (again.level === "ok" || again.level === "warn") {
      snap = again;
      // 预警若只剩延迟/错误率：不要毁掉 owned session（否则每次都 fresh 过盾）
      if (again.level === "warn") {
        const sessionHeavy = again.sessions >= cfg.maxSessionsWarn;
        const memHeavy =
          again.memPercent != null && again.memPercent >= cfg.memWarn;
        if (sessionHeavy || memHeavy) {
          await recycleFlareNow("auto-warn", {
            keepOwned: !memHeavy && sessionHeavy,
          });
        }
      }
      return;
    }
    snap = again;
  }

  if (snap.level === "warn") {
    const sessionHeavy = snap.sessions >= cfg.maxSessionsWarn;
    const memHeavy =
      snap.memPercent != null && snap.memPercent >= cfg.memWarn;
    // 高延迟是 Cloudflare 常态，禁止仅因延迟回收可复用会话
    if (!sessionHeavy && !memHeavy) return;
    await recycleFlareNow("auto-warn", {
      keepOwned: sessionHeavy && !memHeavy,
    });
    return;
  }

  if (snap.level === "critical" || snap.level === "down") {
    const sessionHeavy = snap.sessions >= cfg.maxSessionsCritical;
    const memHeavy =
      snap.memPercent != null && snap.memPercent >= cfg.memCritical;
    const cpuHeavy =
      snap.cpuPercent != null && snap.cpuPercent >= cfg.cpuCritical;
    const errHeavy =
      snap.trafficSample >= 3 && snap.errorRate >= cfg.errorRateCritical;
    // critical 延迟单独出现时：只清孤儿，保留 owned
    if (
      snap.level === "critical" &&
      !sessionHeavy &&
      !memHeavy &&
      !cpuHeavy &&
      !errHeavy
    ) {
      return;
    }
    const soft = await recycleFlareNow("auto-critical", {
      keepOwned: !memHeavy && !cpuHeavy && sessionHeavy,
    });
    const needRestart =
      snap.level === "down" ||
      (!soft.ok && (memHeavy || cpuHeavy)) ||
      (memHeavy && snap.memPercent != null && snap.memPercent >= 95) ||
      (cpuHeavy && snap.cpuPercent != null && snap.cpuPercent >= cfg.cpuCritical) ||
      snap.sessions >= cfg.maxSessionsCritical + 1;
    if (needRestart && buildRestartCommand(cfg)) {
      await new Promise((resolve) => setTimeout(resolve, 2500));
      await restartFlareNow("auto-critical");
    } else if (!soft.ok && buildRestartCommand(cfg)) {
      await restartFlareNow("auto-after-recycle-fail");
    }
  }
}

async function tick(): Promise<void> {
  if (ticking) return;
  ticking = true;
  try {
    const snap = await collectFlareMonitorSnapshot();
    if (snap.level !== "ok") {
      console.log(
        `[scrape] flare-monitor level=${snap.level} sessions=${snap.sessions} cpu=${snap.cpuPercent ?? "-"} mem=${snap.memPercent ?? "-"} :: ${snap.reasons.join(", ")}`,
      );
    }
    await autoRemediate(snap);
    // 动作后刷新快照
    await collectFlareMonitorSnapshot();
  } catch (e) {
    console.warn(
      "[scrape] flare-monitor tick failed:",
      e instanceof Error ? e.message : e,
    );
  } finally {
    ticking = false;
  }
}

export function getLastFlareMonitorSnapshot(): FlareMonitorSnapshot | null {
  return lastSnapshot;
}

export function startFlareMonitor(): void {
  if (timer) return;
  const cfg = readConfig();
  console.log(
    `[scrape] flare-monitor started interval=${cfg.intervalMs}ms auto=${cfg.autoEnabled ? "on" : "off"} restart=${buildRestartCommand(cfg) ? "configured" : "no"}`,
  );
  // 启动稍后跑一轮，避开冷启动探测风暴
  setTimeout(() => void tick(), 8_000);
  timer = setInterval(() => void tick(), cfg.intervalMs);
}

export function stopFlareMonitor(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
