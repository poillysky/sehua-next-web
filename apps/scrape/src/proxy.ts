import { Agent, ProxyAgent, setGlobalDispatcher } from "undici";

let activeProxy = "";

export function getActiveProxy(): string {
  return activeProxy;
}

/** 允许 host:port / 缺省 scheme；空=直连 */
export function normalizeProxyUrl(raw: string | null | undefined): string {
  let s = String(raw || "").trim();
  if (!s) return "";
  // socks5://host:port 保留；裸 host:port → http://
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) {
    s = `http://${s}`;
  }
  // undici ProxyAgent 不吃尾斜杠
  s = s.replace(/\/+$/, "");
  try {
    // 校验可解析
    // eslint-disable-next-line no-new
    new URL(s);
  } catch {
    return "";
  }
  return s;
}

/** 立即切换全局 fetch 代理；空=直连。非法地址不抛崩进程。 */
export function applyProxy(url: string | null | undefined): {
  ok: boolean;
  proxyUrl: string;
  error?: string;
} {
  const trimmed = normalizeProxyUrl(url);
  if (!trimmed) {
    setGlobalDispatcher(new Agent());
    activeProxy = "";
    const had = String(url || "").trim();
    if (had) {
      console.warn(`[scrape] proxy ignored (invalid): ${had}`);
      return { ok: false, proxyUrl: "", error: `代理地址无效：${had}` };
    }
    console.log("[scrape] proxy cleared (direct)");
    return { ok: true, proxyUrl: "" };
  }
  try {
    setGlobalDispatcher(new ProxyAgent(trimmed));
    activeProxy = trimmed;
    console.log(`[scrape] using proxy ${trimmed}`);
    return { ok: true, proxyUrl: trimmed };
  } catch (e) {
    setGlobalDispatcher(new Agent());
    activeProxy = "";
    const msg = e instanceof Error ? e.message : String(e);
    console.warn(`[scrape] proxy apply failed: ${msg}`);
    return { ok: false, proxyUrl: "", error: msg };
  }
}

export function applyProxyFromEnv(): void {
  const proxy =
    process.env.HTTPS_PROXY ||
    process.env.HTTP_PROXY ||
    process.env.ALL_PROXY ||
    process.env.https_proxy ||
    process.env.http_proxy ||
    "";
  applyProxy(proxy);
}
