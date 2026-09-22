/**
 * HTTP 客户端基座（API_BASE / parseError / Envelope / apiFetch）
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */

/**
 * 精简 API 客户端 — 对接 apps/api（色花同协议），非整包复制 sehua 前端。
 */
import type {
  AuthUser,
  BrowseResult,
  FilterSize,
  FilterTime,
  MatchMode,
  ResourceDbConfig,
  ResourceItem,
  SearchResult,
  SortType,
} from '@/types/resource';

export const API_BASE =
  typeof window === 'undefined'
    ? (process.env.API_INTERNAL_BASE || 'http://127.0.0.1:8020').replace(/\/$/, '')
    : (process.env.NEXT_PUBLIC_API_BASE || '/api').replace(/\/$/, '');

export type Envelope<T> = { data: T; message: string; status: number };

export async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as {
      detail?: string | Array<{ msg?: string; loc?: unknown[] }>;
    };
    if (typeof j.detail === 'string') return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]) {
      const first = j.detail[0];
      const msg = String(first.msg || '').trim();
      if (/field required/i.test(msg)) {
        const loc = Array.isArray(first.loc) ? first.loc : [];
        const field = String(loc[loc.length - 1] || '').trim();
        if (field === 'apiKey' || field === 'api_key') return '请填写 API Key';
        return field ? `请填写 ${field}` : '请填写必填项';
      }
      if (msg) return msg;
    }
  } catch {
    /* ignore */
  }
  return `请求失败 ${res.status}`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const isForm =
    typeof FormData !== 'undefined' && init.body instanceof FormData;
  if (init.body && !headers.has('Content-Type') && !isForm) {
    headers.set('Content-Type', 'application/json');
  }
  if (isForm && headers.has('Content-Type')) {
    headers.delete('Content-Type');
  }
  return fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' });
}

