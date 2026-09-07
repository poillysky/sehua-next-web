/** 从刮削库 sourceText 解析详情字段（ingest 时写入的 NFO 行） */

export type ScrapSourceMeta = {
  region: string;
  prefix: string;
  code: string;
  title: string;
  originalTitle: string;
  actresses: string[];
  studio: string;
  label: string;
  year: string;
  genres: string[];
  plot: string;
};

const LINE_RE: Record<string, RegExp> = {
  region: /^分区：(.+)$/m,
  prefix: /^前缀：(.+)$/m,
  code: /^番号：(.+)$/m,
  title: /^标题：(.+)$/m,
  originalTitle: /^原标题：(.+)$/m,
  actress: /^女优：(.+)$/m,
  studio: /^片商：(.+)$/m,
  label: /^发行：(.+)$/m,
  year: /^年份：(.+)$/m,
  genre: /^类型：(.+)$/m,
  plot: /^剧情：([\s\S]+?)(?=\n[^\s][^：\n]*：|$)/m,
};

function line(text: string, key: keyof typeof LINE_RE): string {
  const m = LINE_RE[key].exec(text);
  return m?.[1]?.trim() || '';
}

function splitTokens(raw: string): string[] {
  return raw
    .split(/[\s,，、/|]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 清洗类型行里混入的「片商: xxx」尾注 */
function cleanGenres(raw: string, actresses: string[], prefix: string): string[] {
  let body = raw;
  body = body.split(/\s*(?:片商|发行|系列)\s*[:：]/)[0] || body;
  const skip = new Set(actresses.map((a) => a.toUpperCase()));
  if (prefix) skip.add(prefix.toUpperCase());
  const out: string[] = [];
  for (const token of splitTokens(body)) {
    if (skip.has(token.toUpperCase())) continue;
    if (/^[A-Z0-9]+-\d+$/i.test(token)) continue;
    if (token.length > 24) continue;
    if (!out.includes(token)) out.push(token);
  }
  return out;
}

export function parseScrapSourceText(sourceText?: string | null): ScrapSourceMeta {
  const text = String(sourceText || '');
  const actresses = splitTokens(line(text, 'actress'));
  const prefix = line(text, 'prefix');
  const genreRaw = line(text, 'genre');
  let plot = line(text, 'plot');
  if (!plot) {
    const m = /^剧情：(.+)$/m.exec(text);
    plot = m?.[1]?.trim() || '';
  }
  return {
    region: line(text, 'region'),
    prefix,
    code: line(text, 'code'),
    title: line(text, 'title'),
    originalTitle: line(text, 'originalTitle'),
    actresses,
    studio: line(text, 'studio'),
    label: line(text, 'label'),
    year: line(text, 'year'),
    genres: cleanGenres(genreRaw, actresses, prefix),
    plot,
  };
}
