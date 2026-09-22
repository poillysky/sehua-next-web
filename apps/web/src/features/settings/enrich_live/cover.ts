import { scrapLibraryCoverUrl, type ScrapLibraryEnrichFieldRow } from '@/lib/api';

/** 详情竖框约 240px，2x 用 480 即可；过大 w 会逼后端现场压图变慢 */
export const ENRICH_POSTER_W = 480;
export const ENRICH_SHOT_W = 320;

export function localCoverSrc(api?: string, mtime?: number, w = ENRICH_POSTER_W) {
  const raw = String(api || '').trim();
  if (!raw) return '';
  const url = scrapLibraryCoverUrl(
    { posterApi: raw, thumbApi: '', coverUrl: '' },
    { w, prefer: 'poster', rp: false },
  );
  if (!url) return '';
  if (!mtime) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_t=${mtime}`;
}

export function fieldsFromSourceText(src: string): ScrapLibraryEnrichFieldRow[] {
  const text = String(src || '');
  const pick = (id: string, label: string, re: RegExp) => {
    const m = text.match(re);
    const val = (m?.[1] || '').trim();
    return { id, label, ok: Boolean(val), value: val || undefined };
  };
  return [
    pick('title', '标题', /^标题：(.+)$/m),
    pick('actors', '女优', /^女优：(.+)$/m),
    pick('studio', '片商', /^片商：(.+)$/m),
    pick('overview', '剧情', /^剧情：(.+)$/m),
  ];
}

function displayHitSource(source?: string): string {
  const s = String(source || '').trim();
  if (
    !s ||
    s === 'log_recover' ||
    s === 'recover' ||
    s === 'local_scan' ||
    s === 'scan'
  ) {
    return '';
  }
  return s;
}

export function ensurePosterField(
  fields: ScrapLibraryEnrichFieldRow[],
  opts?: { posterDownloaded?: boolean },
): ScrapLibraryEnrichFieldRow[] {
  const posterDownloaded = opts?.posterDownloaded;
  const list = [...(fields || [])];
  const idx = list.findIndex(
    (f) => f.id === 'poster' || f.label === '封面',
  );
  const fallback: ScrapLibraryEnrichFieldRow = {
    id: 'poster',
    label: '封面',
    ok: Boolean(posterDownloaded),
    value: posterDownloaded ? '已落盘' : '无',
  };
  if (idx >= 0) {
    const cur = list[idx];
    const ok =
      typeof posterDownloaded === 'boolean'
        ? posterDownloaded || Boolean(cur.ok)
        : Boolean(cur.ok);
    list[idx] = {
      ...cur,
      id: 'poster',
      label: cur.label || '封面',
      ok,
      value:
        cur.value ||
        (ok ? (posterDownloaded ? '已落盘' : '有') : '无'),
      source: cur.source,
    };
    return list;
  }
  const titleIdx = list.findIndex(
    (f) => f.id === 'title' || f.label === '标题',
  );
  if (titleIdx >= 0) {
    list.splice(titleIdx + 1, 0, fallback);
    return list;
  }
  return [fallback, ...list];
}
