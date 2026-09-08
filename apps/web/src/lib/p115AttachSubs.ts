'use client';

/** 片商详情 → 仓库转存时，附带上传该番号本地字幕 */
export const P115_ATTACH_SUBS_KEY = 'nextweb:p115-attach-subs';

export type P115AttachSubs = {
  code?: string;
  itemId?: string;
  /** 片商分区 id 或中文标签，用于 115 区分子目录 */
  region?: string;
};

export function writeP115AttachSubs(payload: P115AttachSubs | null): void {
  try {
    if (typeof sessionStorage === 'undefined') return;
    if (!payload || (!payload.code && !payload.itemId && !payload.region)) {
      sessionStorage.removeItem(P115_ATTACH_SUBS_KEY);
      return;
    }
    sessionStorage.setItem(
      P115_ATTACH_SUBS_KEY,
      JSON.stringify({
        code: String(payload.code || '').trim(),
        itemId: String(payload.itemId || '').trim(),
        region: String(payload.region || '').trim(),
      }),
    );
  } catch {
    /* ignore */
  }
}

export function readP115AttachSubs(): P115AttachSubs | null {
  try {
    if (typeof sessionStorage === 'undefined') return null;
    const raw = sessionStorage.getItem(P115_ATTACH_SUBS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as P115AttachSubs;
    const code = String(parsed?.code || '').trim();
    const itemId = String(parsed?.itemId || '').trim();
    const region = String(parsed?.region || '').trim();
    if (!code && !itemId && !region) return null;
    return { code, itemId, region };
  } catch {
    return null;
  }
}

export function clearP115AttachSubs(): void {
  writeP115AttachSubs(null);
}
