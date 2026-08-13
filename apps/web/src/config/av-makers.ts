import japanJson from './av-makers.japan.json';
import chinaJson from './av-makers.china.json';
import westernJson from './av-makers.western.json';

export type AvMakerKind = '有码' | '无码' | '写真' | '国产' | '欧美';

export type AvMakerEntry = {
  maker: string;
  kind: AvMakerKind;
  description?: string;
  prefixes: string[];
  prefix_notes?: Record<string, string>;
  cover_aspect?: string;
  prefix_aspects?: Record<string, string>;
};

export type MakerRegionId = 'japan' | 'china' | 'western';

export const MAKER_REGIONS: { id: MakerRegionId; label: string }[] = [
  { id: 'japan', label: '日本' },
  { id: 'china', label: '国产' },
  { id: 'western', label: '欧美' },
];

export const AV_MAKERS_JAPAN = japanJson as unknown as AvMakerEntry[];
export const AV_MAKERS_CHINA = chinaJson as unknown as AvMakerEntry[];
export const AV_MAKERS_WESTERN = westernJson as unknown as AvMakerEntry[];

export const AV_MAKERS_BY_REGION: Record<MakerRegionId, AvMakerEntry[]> = {
  japan: AV_MAKERS_JAPAN,
  china: AV_MAKERS_CHINA,
  western: AV_MAKERS_WESTERN,
};

export const AV_MAKERS_ALL = [
  ...AV_MAKERS_JAPAN,
  ...AV_MAKERS_CHINA,
  ...AV_MAKERS_WESTERN,
];

const byMaker = new Map(
  AV_MAKERS_ALL.map((m) => [m.maker.trim().toLowerCase(), m]),
);

const byPrefix = new Map<string, AvMakerEntry>();
for (const m of AV_MAKERS_ALL) {
  for (const p of m.prefixes || []) {
    const key = String(p || '')
      .trim()
      .toUpperCase()
      .replace(/_/g, '-');
    if (key && !byPrefix.has(key)) byPrefix.set(key, m);
  }
}

export function findMakerMeta(maker: string): AvMakerEntry | undefined {
  const key = (maker || '').trim().toLowerCase();
  if (!key) return undefined;
  return byMaker.get(key);
}

export function findMakerByPrefix(prefix: string): AvMakerEntry | undefined {
  const key = String(prefix || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');
  if (!key) return undefined;
  return byPrefix.get(key);
}

export function makerDescription(maker: string): string {
  return findMakerMeta(maker)?.description?.trim() || '';
}

export function makerKind(maker: string): AvMakerKind | '' {
  return findMakerMeta(maker)?.kind || '';
}

export function prefixNote(maker: string, prefix: string): string {
  const meta = findMakerMeta(maker);
  if (!meta?.prefix_notes) return '';
  const code = (prefix || '').trim();
  if (!code) return '';
  return (
    meta.prefix_notes[code]?.trim() ||
    meta.prefix_notes[code.toUpperCase()]?.trim() ||
    ''
  );
}

export type CoverAspect = string;

export type CoverDisplay = {
  aspectRatio: string;
  aspect: CoverAspect;
  preferLandscape: boolean;
  objectPosition: 'right top' | 'center';
};

function normalizeAspect(raw: string | undefined, fallback: CoverAspect): CoverAspect {
  const s = String(raw || '')
    .trim()
    .replace(/\s+/g, '')
    .replace(':', '/');
  if (!/^\d+(\.\d+)?\/\d+(\.\d+)?$/.test(s)) return fallback;
  return s;
}

function aspectToCss(aspect: CoverAspect): string {
  const [w, h] = aspect.split('/');
  return `${w} / ${h}`;
}

function isLandscapeAspect(aspect: CoverAspect): boolean {
  const [w, h] = aspect.split('/').map(Number);
  return Number.isFinite(w) && Number.isFinite(h) && w > h;
}

export function coverDisplayFromAspect(
  raw: CoverAspect,
  fallback: CoverAspect = '2/3',
  opts?: { cropRight?: boolean },
): CoverDisplay {
  const aspect = normalizeAspect(raw, fallback);
  const preferLandscape = isLandscapeAspect(aspect);
  const cropRight = Boolean(opts?.cropRight) && !preferLandscape;
  return {
    aspect,
    aspectRatio: aspectToCss(aspect),
    preferLandscape,
    objectPosition: cropRight ? 'right top' : 'center',
  };
}

/** 按前缀解析封面展示比例 */
export function resolveCoverDisplay(prefix: string): CoverDisplay {
  const meta = findMakerByPrefix(prefix);
  const code = String(prefix || '')
    .trim()
    .toUpperCase()
    .replace(/_/g, '-');
  const kindFallback: CoverAspect =
    meta?.kind === '无码' || meta?.kind === '国产' || meta?.kind === '欧美'
      ? '16/9'
      : meta?.kind === '写真'
        ? '3/2'
        : '2/3';
  let fromPrefix: string | undefined;
  if (meta?.prefix_aspects) {
    for (const [k, v] of Object.entries(meta.prefix_aspects)) {
      if (k.toUpperCase().replace(/_/g, '-') === code) {
        fromPrefix = v;
        break;
      }
    }
  }
  const cropRight = !meta || meta.kind === '有码';
  return coverDisplayFromAspect(
    fromPrefix || meta?.cover_aspect || kindFallback,
    kindFallback,
    { cropRight },
  );
}
