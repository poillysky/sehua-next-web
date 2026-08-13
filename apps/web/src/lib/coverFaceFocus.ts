import { apiFetch, API_BASE } from '@/lib/api';
import type { PosterCropMode } from '@/lib/api';
import { objectPositionForCropMode } from '@/lib/coverCropPrefs';

/** img 可能已是 /cover-proxy?url=…；focus API 需要原始 http(s) 以便服务端再走代理拉图 */
function focusFetchUrl(src: string): string {
  const s = String(src || '').trim();
  if (!s) return s;
  try {
    const base =
      typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1';
    const u = new URL(s, base);
    const path = u.pathname.replace(/\/$/, '');
    if (path.endsWith('/cover-proxy')) {
      return u.searchParams.get('url') || s;
    }
    if (path.endsWith('/scrape/export/img')) {
      return u.searchParams.get('u') || u.searchParams.get('url') || s;
    }
    // 同源相对代理路径
    if (s.startsWith(`${API_BASE}/cover-proxy?`)) {
      return new URL(s, base).searchParams.get('url') || s;
    }
  } catch {
    /* ignore */
  }
  return s;
}

const focusCache = new Map<string, string>();
const inflight = new Map<string, Promise<string>>();
const SS_KEY = 'nextweb:cover-face-focus-v1';
const MAX_SS = 200;
let queue = Promise.resolve();
let active = 0;
const MAX_PARALLEL = 3;

function loadSessionCache() {
  if (typeof sessionStorage === 'undefined') return;
  try {
    const raw = sessionStorage.getItem(SS_KEY);
    if (!raw) return;
    const obj = JSON.parse(raw) as Record<string, string>;
    for (const [k, v] of Object.entries(obj)) {
      if (k && v) focusCache.set(k, v);
    }
  } catch {
    /* ignore */
  }
}

function saveSessionCache() {
  if (typeof sessionStorage === 'undefined') return;
  try {
    const obj: Record<string, string> = {};
    let n = 0;
    for (const [k, v] of focusCache) {
      obj[k] = v;
      n += 1;
      if (n >= MAX_SS) break;
    }
    sessionStorage.setItem(SS_KEY, JSON.stringify(obj));
  } catch {
    /* ignore */
  }
}

if (typeof window !== 'undefined') {
  loadSessionCache();
}

function enqueue<T>(job: () => Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const run = async () => {
      while (active >= MAX_PARALLEL) {
        await new Promise((r) => setTimeout(r, 24));
      }
      active += 1;
      try {
        resolve(await job());
      } catch (e) {
        reject(e);
      } finally {
        active -= 1;
      }
    };
    queue = queue.then(run, run);
  });
}

async function detectWithServer(src: string): Promise<string | null> {
  try {
    const remote = focusFetchUrl(src);
    const res = await apiFetch(
      `/cover-focus?url=${encodeURIComponent(remote)}`,
    );
    if (!res.ok) return null;
    const json = (await res.json()) as {
      data?: { x?: number; y?: number };
    };
    const x = Number(json.data?.x);
    const y = Number(json.data?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return `${(x * 100).toFixed(1)}% ${(y * 100).toFixed(1)}%`;
  } catch {
    return null;
  }
}

/** 人脸取景 object-position；内存 + session 缓存，限流请求 */
export async function resolveFaceObjectPosition(src: string): Promise<string> {
  const key = String(src || '').trim();
  if (!key) return objectPositionForCropMode('face');
  const hit = focusCache.get(key);
  if (hit) return hit;
  const pending = inflight.get(key);
  if (pending) return pending;

  const job = enqueue(async () => {
    const fromServer = await detectWithServer(key);
    const next = fromServer || objectPositionForCropMode('face');
    focusCache.set(key, next);
    saveSessionCache();
    return next;
  }).finally(() => {
    inflight.delete(key);
  });

  inflight.set(key, job);
  return job;
}

export function staticObjectPositionForMode(mode: PosterCropMode | undefined): string {
  return objectPositionForCropMode(mode);
}
