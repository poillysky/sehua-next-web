import {
  type MediaCastPerson,
  type MediaItem,
  type PansouLink,
} from '@/lib/api';
import { linkKindOf } from '@/lib/resourceView';

export type CloudSearchKind = 'pansou' | 'cloudsaver';

export function is115ShareLink(lk: PansouLink): boolean {
  return linkKindOf(lk.url) === '115share';
}

export function isOfflineSaveLink(lk: PansouLink): boolean {
  const kind = linkKindOf(lk.url);
  return kind === 'magnet' || kind === 'ed2k';
}

export function canSaveTo115(lk: PansouLink): boolean {
  return is115ShareLink(lk) || isOfflineSaveLink(lk);
}

export function pickAka(item: MediaItem): string[] {
  return [item.originalTitle, ...(item.aka || [])]
    .map((s) => String(s || '').trim())
    .filter(Boolean)
    .filter((s, i, arr) => arr.indexOf(s) === i && s !== item.title)
    .filter((s) => /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z0-9]/.test(s))
    .filter(
      (s) => !/^[\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u1780-\u17FF]+/.test(s),
    )
    .slice(0, 2);
}

const COUNTRY_SHORT: Record<string, string> = {
  'United States of America': '美国',
  'United States': '美国',
  USA: '美国',
  'United Kingdom': '英国',
  UK: '英国',
  Japan: '日本',
  China: '中国',
  'Hong Kong': '中国香港',
  Taiwan: '中国台湾',
  'South Korea': '韩国',
  Korea: '韩国',
  France: '法国',
  Germany: '德国',
  Italy: '意大利',
  Spain: '西班牙',
  Canada: '加拿大',
  Australia: '澳大利亚',
  India: '印度',
  Thailand: '泰国',
  Russia: '俄罗斯',
};

export function shortCountry(name: string): string {
  const s = String(name || '').trim();
  return COUNTRY_SHORT[s] || s;
}

export function normalizeCast(raw: MediaItem['cast']): MediaCastPerson[] {
  if (!Array.isArray(raw)) return [];
  const out: MediaCastPerson[] = [];
  for (const row of raw) {
    if (typeof row === 'string') {
      const name = row.trim();
      if (name) out.push({ name });
      continue;
    }
    if (row && typeof row === 'object' && 'name' in row) {
      const name = String(row.name || '').trim();
      if (!name) continue;
      const id =
        row.id != null && String(row.id).trim() ? String(row.id) : undefined;
      const avatarUrl =
        row.avatarUrl != null && String(row.avatarUrl).trim()
          ? String(row.avatarUrl)
          : undefined;
      out.push({ name, id, avatarUrl });
    }
  }
  return out.slice(0, 12);
}
