import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fetchText } from "./download.js";
import {
  applyFlareSolverr,
  abortAllFlareRequests,
  clearCachedClearance,
  getFlareSolverrUrl,
  hostNeedsFlare,
  looksBlockedHtml,
  normalizeFlareUrl,
  probeFlareSolverr,
  setClearanceStorePath,
} from "./flaresolverr.js";
import {
  collectFlareMonitorSnapshot,
  getLastFlareMonitorSnapshot,
  recycleFlareNow,
  restartFlareNow,
  startFlareMonitor,
} from "./flareMonitor.js";
import { applyProxy, applyProxyFromEnv, getActiveProxy } from "./proxy.js";
import {
  loadPersistedNetwork,
  persistActiveNetwork,
  setNetworkStorePath,
} from "./networkStore.js";
import { setAiravMirrorStorePath } from "./airavMirror.js";
import { createQueue, getMeta, scrapeOne, type Dirs } from "./scrape.js";
import { defaultCookieFor } from "./sourceCookies.js";
import { DEFAULT_KIND_SOURCES, SOURCE_CATALOG } from "./sources.js";
import type { ScrapeRequest } from "./types.js";
import { APP_ROOT, codeFileStem, loadEnv, stdCode } from "./util.js";

loadEnv();
applyProxyFromEnv();
applyFlareSolverr(process.env.FLARESOLVERR_URL || "");

const PORT = Number(process.env.PORT || 9210);
const HOST = process.env.HOST || "0.0.0.0";
const coversDir = path.resolve(APP_ROOT, process.env.COVERS_DIR || "./data/covers");
const metaDir = path.resolve(APP_ROOT, process.env.META_DIR || "./data/meta");
const libraryDir = process.env.LIBRARY_DIR
  ? path.resolve(process.env.LIBRARY_DIR)
  : "";

fs.mkdirSync(coversDir, { recursive: true });
fs.mkdirSync(metaDir, { recursive: true });
setClearanceStorePath(path.join(metaDir, "cf-clearance.json"));
setNetworkStorePath(path.join(metaDir, "network.json"));
setAiravMirrorStorePath(path.join(metaDir, "airav-mirror.json"));
loadPersistedNetwork();

const dirs: Dirs = { coversDir, metaDir };
/** 双通道各自并发；默认 8，可用环境变量覆盖。旧 SCRAPE_CONCURRENCY 作两者上限参考。 */
const _legacyConc = Math.max(
  1,
  Math.min(16, Number(process.env.SCRAPE_CONCURRENCY || 8) || 8),
);
const SCRAPE_FAST_CONCURRENCY = Math.max(
  1,
  Math.min(
    16,
    Number(process.env.SCRAPE_FAST_CONCURRENCY || _legacyConc) || _legacyConc,
  ),
);
const SCRAPE_SLOW_CONCURRENCY = Math.max(
  1,
  Math.min(
    16,
    Number(process.env.SCRAPE_SLOW_CONCURRENCY || _legacyConc) || _legacyConc,
  ),
);
const runFast = createQueue(SCRAPE_FAST_CONCURRENCY);
const runSlow = createQueue(SCRAPE_SLOW_CONCURRENCY);

function queueForChannel(channel: unknown) {
  return String(channel || "")
    .trim()
    .toLowerCase() === "slow"
    ? runSlow
    : runFast;
}

const app = express();
app.use(express.json({ limit: "1mb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    service: "sehua-next-search-scrape",
    coversDir,
    metaDir,
    libraryDir: libraryDir || null,
    flareSolverrUrl: getFlareSolverrUrl() || null,
    proxyUrl: getActiveProxy() || null,
    scrapeFastConcurrency: SCRAPE_FAST_CONCURRENCY,
    scrapeSlowConcurrency: SCRAPE_SLOW_CONCURRENCY,
  });
});

app.get("/api/config/network", (_req, res) => {
  res.json({
    ok: true,
    data: {
      flareSolverrUrl: getFlareSolverrUrl() || "",
      proxyUrl: getActiveProxy() || "",
    },
  });
});

app.put("/api/config/network", (req, res) => {
  const body = (req.body || {}) as {
    flareSolverrUrl?: string;
    proxyUrl?: string;
  };
  const prevFlare = getFlareSolverrUrl();
  const prevProxy = getActiveProxy();
  if (body.flareSolverrUrl !== undefined) {
    applyFlareSolverr(normalizeFlareUrl(body.flareSolverrUrl));
  }
  let proxyErr: string | undefined;
  if (body.proxyUrl !== undefined) {
    const r = applyProxy(body.proxyUrl);
    if (!r.ok && r.error) proxyErr = r.error;
  }
  // 代理变了 → 出口 IP 变，旧 cf_clearance 失效
  if (getActiveProxy() !== prevProxy && getFlareSolverrUrl() === prevFlare) {
    clearCachedClearance();
  }
  persistActiveNetwork();
  res.json({
    ok: !proxyErr,
    data: {
      flareSolverrUrl: getFlareSolverrUrl() || "",
      proxyUrl: getActiveProxy() || "",
    },
    message: proxyErr || "network updated",
  });
});

app.get("/api/config/flaresolverr", (_req, res) => {
  res.json({
    ok: true,
    data: {
      flareSolverrUrl: getFlareSolverrUrl() || "",
      proxyUrl: getActiveProxy() || "",
    },
  });
});

app.put("/api/config/flaresolverr", (req, res) => {
  const url = normalizeFlareUrl(
    String((req.body as { flareSolverrUrl?: string })?.flareSolverrUrl ?? ""),
  );
  applyFlareSolverr(url);
  persistActiveNetwork();
  res.json({
    ok: true,
    data: { flareSolverrUrl: getFlareSolverrUrl() || "" },
    message: url ? "flaresolverr updated" : "flaresolverr cleared",
  });
});

app.post("/api/config/flaresolverr/test", async (req, res) => {
  const body = (req.body || {}) as {
    flareSolverrUrl?: string;
    proxyUrl?: string;
    sampleUrl?: string;
  };
  if (body.flareSolverrUrl !== undefined) {
    applyFlareSolverr(normalizeFlareUrl(body.flareSolverrUrl));
  }
  if (body.proxyUrl !== undefined) {
    const pr = applyProxy(body.proxyUrl);
    if (!pr.ok && String(body.proxyUrl || "").trim()) {
      res.status(400).json({
        ok: false,
        data: {
          ok: false,
          flareSolverrUrl: getFlareSolverrUrl() || "",
          message: pr.error || "代理地址无效",
        },
        message: pr.error || "代理地址无效",
      });
      return;
    }
  }
  persistActiveNetwork();
  const result = await probeFlareSolverr(body.sampleUrl);
  res.json({
    ok: result.ok,
    data: { ...result, proxyUrl: getActiveProxy() || "" },
    message: result.message,
  });
});

app.get("/api/config/flaresolverr/monitor", async (_req, res) => {
  try {
    const data =
      getLastFlareMonitorSnapshot() || (await collectFlareMonitorSnapshot());
    res.json({ ok: true, data });
  } catch (e) {
    res.status(500).json({
      ok: false,
      message: e instanceof Error ? e.message : String(e),
    });
  }
});

app.post("/api/config/flaresolverr/recycle", async (_req, res) => {
  const r = await recycleFlareNow("manual");
  const data = await collectFlareMonitorSnapshot();
  res.json({
    ok: r.ok,
    data: { ...data, destroyed: r.destroyed },
    message: r.message,
  });
});

app.post("/api/config/flaresolverr/restart", async (_req, res) => {
  const r = await restartFlareNow("manual");
  const data = await collectFlareMonitorSnapshot();
  res.json({
    ok: r.ok,
    data: { ...data, restartCmd: r.cmd },
    message: r.message,
  });
});

/** 仅测代理：应用地址后尝试出网 */
app.post("/api/config/proxy/test", async (req, res) => {
  const body = (req.body || {}) as { proxyUrl?: string };
  const pr = applyProxy(body.proxyUrl);
  if (!pr.ok) {
    res.status(200).json({
      ok: false,
      data: { ok: false, proxyUrl: pr.proxyUrl || "" },
      message: pr.error || "代理地址无效",
    });
    return;
  }
  persistActiveNetwork();
  if (!pr.proxyUrl) {
    res.json({
      ok: true,
      data: { ok: true, proxyUrl: "" },
      message: "直连模式（未填代理）",
    });
    return;
  }
  try {
    const r = await fetch("https://www.google.com/generate_204", {
      method: "GET",
      redirect: "manual",
      signal: AbortSignal.timeout(12000),
    });
    const ok = r.status === 204 || (r.status >= 200 && r.status < 500);
    res.json({
      ok,
      data: { ok, proxyUrl: pr.proxyUrl, status: r.status },
      message: ok
        ? `代理可达（HTTP ${r.status}）`
        : `代理响应异常（HTTP ${r.status}）`,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    res.json({
      ok: false,
      data: { ok: false, proxyUrl: pr.proxyUrl },
      message: `代理连通失败：${msg}`,
    });
  }
});

app.get("/api/scrape/health", (_req, res) => {
  res.json({ ok: true, coversDir, metaDir });
});

app.get("/api/sources", (_req, res) => {
  res.json({
    ok: true,
    data: {
      sourceCatalog: SOURCE_CATALOG,
      defaultKindSources: DEFAULT_KIND_SOURCES,
      kinds: [
        "japan_censored",
        "japan_uncensored",
        "fc2",
        "china",
        "western",
      ],
    },
  });
});

app.post("/api/sources/probe", async (req, res) => {
  const body = (req.body || {}) as { id?: string; baseUrl?: string };
  const id = String(body.id || "")
    .trim()
    .toLowerCase();
  const def = SOURCE_CATALOG.find((s) => s.id === id);
  if (!def) {
    res.status(404).json({ ok: false, message: "unknown source" });
    return;
  }
  if (id === "forum") {
    res.json({
      ok: true,
      data: { id, status: "ok", lastError: null, cooldownSec: 0 },
    });
    return;
  }
  const base = String(body.baseUrl || def.defaultUrl || "")
    .trim()
    .replace(/\/$/, "");
  if (!base) {
    res.json({
      ok: true,
      data: {
        id,
        status: "error",
        lastError: "未配置 URL",
        cooldownSec: 10,
      },
    });
    return;
  }
  const probePath = def.probePath || "/";
  const url = `${base}${probePath.startsWith("/") ? probePath : `/${probePath}`}`;
  try {
    // theporndb：根路径无业务；有 Key 才算配置就绪，否则标 unknown
    if (id === "theporndb") {
      const key = String(process.env.THEPORNDB_API_KEY || "").trim();
      if (!key) {
        res.json({
          ok: true,
          data: {
            id,
            status: "unknown",
            lastError: "未配置 THEPORNDB_API_KEY",
            cooldownSec: 0,
          },
        });
        return;
      }
      // 有 Key：打一枪轻量搜索验证鉴权（勿依赖根路径 HTML）
      try {
        const auth = key.toLowerCase().startsWith("bearer ")
          ? key
          : `Bearer ${key}`;
        const apiBase = base.replace(/\/$/, "") || "https://api.theporndb.net";
        const probe = await fetch(`${apiBase}/jav?q=SONE-001&per_page=1`, {
          signal: AbortSignal.timeout(15000),
          headers: {
            Accept: "application/json",
            Authorization: auth,
          },
        });
        if (probe.status === 401 || probe.status === 403) {
          res.json({
            ok: true,
            data: {
              id,
              status: "error",
              lastError: `API 鉴权失败 HTTP ${probe.status}`,
              cooldownSec: 30,
            },
          });
          return;
        }
        if (!probe.ok) {
          res.json({
            ok: true,
            data: {
              id,
              status: "error",
              lastError: `API HTTP ${probe.status}`,
              cooldownSec: 15,
            },
          });
          return;
        }
        res.json({
          ok: true,
          data: { id, status: "ok", lastError: "", cooldownSec: 0 },
        });
        return;
      } catch (e) {
        res.json({
          ok: true,
          data: {
            id,
            status: "error",
            lastError: e instanceof Error ? e.message : "API 探测失败",
            cooldownSec: 15,
          },
        });
        return;
      }
    }
    // CF 站：javlibrary 等 fresh 过盾常 25–40s；28s 易误报「探测超时」
    // 强制 viaFlare，避免先烧 12s 代理直连再过盾
    const needsFlare =
      Boolean(getFlareSolverrUrl()) && hostNeedsFlare(url);
    const html = await fetchText(url, {
      timeoutMs: needsFlare ? 65000 : 10000,
      strictTimeout: true,
      viaFlare: needsFlare ? true : undefined,
      sourceId: id,
      cookie: defaultCookieFor(id),
      referer: `${base}/`,
    });
    if (!html) {
      res.json({
        ok: true,
        data: {
          id,
          status: "error",
          lastError: needsFlare ? "过盾超时 / 无响应" : "超时 / 无响应",
          cooldownSec: 15,
        },
      });
      return;
    }
    if (looksBlockedHtml(html)) {
      const challenge =
        /Just a moment|cf-browser-verification|Attention Required|Cloudflare/i.test(
          html.slice(0, 4000),
        );
      const hint =
        id === "fc2_hub" || id === "mgstage" || id === "javdb"
          ? "出口 IP 被站方封锁（换代理或暂时依赖其它源）"
          : challenge
            ? "仍是挑战页（过盾未完成）"
            : "空响应 / 封锁页";
      res.json({
        ok: true,
        data: {
          id,
          status: "error",
          lastError: hint,
          cooldownSec: 15,
        },
      });
      return;
    }
    res.json({
      ok: true,
      data: { id, status: "ok", lastError: null, cooldownSec: 0 },
    });
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e);
    const msg = /timed?\s*out|aborted|TimeoutError/i.test(raw)
      ? "探测超时"
      : raw;
    res.json({
      ok: true,
      data: {
        id,
        status: "error",
        lastError: msg.slice(0, 120),
        cooldownSec: 10,
      },
    });
  }
});

app.use(
  "/covers",
  express.static(coversDir, { fallthrough: true, maxAge: "7d" }),
);

app.get("/api/meta/:code", (req, res) => {
  const code = stdCode(String(req.params.code || ""));
  const meta = getMeta(dirs, code);
  if (!meta) {
    res.status(404).json({ ok: false, message: "not found" });
    return;
  }
  res.json({ ok: true, data: meta });
});

app.get("/covers/:code.jpg", (req, res, next) => {
  const stem = codeFileStem(String(req.params.code || ""));
  const file = path.join(coversDir, `${stem}.jpg`);
  if (!fs.existsSync(file)) {
    next();
    return;
  }
  res.sendFile(file);
});

app.post("/api/scrape", async (req, res) => {
  const body = (req.body || {}) as ScrapeRequest;
  const code = stdCode(String(body.code || ""));
  if (!code) {
    res.status(400).json({ ok: false, message: "code required" });
    return;
  }
  const deadlineMs = Math.max(
    10000,
    Math.min(
      120000,
      Number(
        (body as { deadlineMs?: number }).deadlineMs
          || process.env.SCRAPE_ITEM_DEADLINE_MS
          || 35000,
      ) || 35000,
    ),
  );
  try {
    const run = queueForChannel(body.channel);
    const meta = await run(async () => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const result = await Promise.race([
          scrapeOne(dirs, code, {
            preferCoverUrl: body.preferCoverUrl,
            preferTitle: body.preferTitle,
            preferActors: body.preferActors,
            preferLocal: body.preferLocal,
            force: Boolean(body.force),
            kind: body.kind,
            region: body.region,
            metaSources: body.metaSources,
            coverSources: body.coverSources,
            fieldPriority: body.fieldPriority,
            coverDownloadStrategy: body.coverDownloadStrategy,
            posterCrop: body.posterCrop,
            channel: body.channel,
          }),
          new Promise<never>((_, reject) => {
            timer = setTimeout(
              () => reject(new Error("scrape_deadline")),
              deadlineMs,
            );
          }),
        ]);
        return result;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (/scrape_deadline/i.test(msg)) {
          return {
            code,
            title: "",
            source: "none",
            ok: false,
            message: "scrape_deadline",
            sourcesTried: [],
            sourceRuns: [],
            scrapedAt: new Date().toISOString(),
          };
        }
        throw e;
      } finally {
        if (timer) clearTimeout(timer);
      }
    });
    res.json({ ok: meta.ok, data: meta, message: meta.message });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/flare aborted|aborted|AbortError/i.test(msg)) {
      res.status(499).json({ ok: false, message: "aborted" });
      return;
    }
    res.status(500).json({
      ok: false,
      message: msg,
    });
  }
});

/** 暂停/取消刮削：立刻打断排队与进行中的 FlareSolverr 请求 */
app.post("/api/scrape/abort", (_req, res) => {
  const n = abortAllFlareRequests("scrape-abort");
  res.json({
    ok: true,
    data: { aborted: n },
    message: n ? `已中断 ${n} 个过盾请求` : "无进行中过盾请求",
  });
});

app.post("/api/scrape/batch", async (req, res) => {
  const body = (req.body || {}) as {
    codes?: string[];
    preferCoverUrls?: Record<string, string>;
    force?: boolean;
    kind?: string;
    region?: string;
    metaSources?: string[];
    coverSources?: string[];
    fieldPriority?: import("./types.js").FieldPriority;
    coverDownloadStrategy?: import("./types.js").CoverDownloadStrategy;
    posterCrop?: import("./types.js").PosterCropConfig;
  };
  const codes = (body.codes || []).map(stdCode).filter(Boolean).slice(0, 20);
  if (!codes.length) {
    res.status(400).json({ ok: false, message: "codes required (max 20)" });
    return;
  }
  const items = [];
  for (const code of codes) {
    const run = queueForChannel((body as { channel?: string }).channel);
    const meta = await run(() =>
      scrapeOne(dirs, code, {
        preferCoverUrl: body.preferCoverUrls?.[code],
        force: Boolean(body.force),
        kind: body.kind,
        region: body.region,
        metaSources: body.metaSources,
        coverSources: body.coverSources,
        fieldPriority: body.fieldPriority,
        coverDownloadStrategy: body.coverDownloadStrategy,
        posterCrop: body.posterCrop,
        channel: (body as { channel?: string }).channel,
      }),
    );
    items.push(meta);
  }
  res.json({ ok: true, data: { items }, message: `done ${items.length}` });
});

app.listen(PORT, HOST, () => {
  console.log(
    `[scrape] listening ${HOST}:${PORT} covers=${coversDir} meta=${metaDir}`,
  );
  console.log(
    `[scrape] channel queues fast≤${SCRAPE_FAST_CONCURRENCY} slow≤${SCRAPE_SLOW_CONCURRENCY}`,
  );
  startFlareMonitor();
});
