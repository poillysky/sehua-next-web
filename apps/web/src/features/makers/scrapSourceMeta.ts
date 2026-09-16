/** 从刮削库 sourceText 解析详情字段（ingest 时写入的 NFO 行） */

export type ScrapSourceMeta = {
  region: string;
  prefix: string;
  code: string;
  title: string;
  originalTitle: string;
  originalPlot: string;
  outlineShow: string;
  badges: string[];
  cnsub: boolean;
  definition: string;
  mosaic: string;
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
  originalPlot: /^原剧情：([\s\S]+?)(?=\n[^\s][^：\n]*：|$)/m,
  outlineShow: /^双语：(.+)$/m,
  badges: /^角标：(.+)$/m,
  definition: /^清晰度：(.+)$/m,
  mosaic: /^马赛克：(.+)$/m,
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

/** 站点标签 / UI 文案误入女优行时的防御过滤 */
const JUNK_ACTRESS = new Set(
  [
    '显示更多',
    '顯示更多',
    '查看更多',
    '更多',
    '巨乳',
    '美乳',
    '淫乱',
    '淫亂',
    '角色扮演',
    '原创',
    '原創',
    '高清',
    '高畫質',
    '高画质',
    '独家',
    '獨家',
    '中出',
    '中出し',
    '痴女',
    '漫改',
    '剧情',
    '劇情',
    '苗条',
    '苗條',
    '美少女',
    '单体作品',
    '單體作品',
    '出道',
    '出道作品',
    'AV出道',
    'デビュー',
    '新人',
    '收藏',
    '字幕',
    '翻译',
    '翻譯',
    '绝顶高潮',
    '絕頂高潮',
    '其他恋物癖',
    '其他戀物癖',
    '羞耻',
    '羞恥',
    '羞辱',
    '打手枪',
    '打手槍',
    '强制口交',
    '強制口交',
    '打屁股',
    '玩具',
    '多P',
    '3P',
    '4P',
    '合集',
    'VR',
    '4K',
    'HD',
    'UHD',
    'FC2',
    'SOD',
    'M女',
    '素人',
    '人妻',
    '熟女',
    '制服',
    '口交',
    '颜射',
    '顏射',
    '内射',
    '潮吹',
    '露出',
    '偷拍',
    '调教',
    '調教',
    '丝袜',
    '絲襪',
    '黑丝',
    '黑絲',
    '足交',
    '肛交',
    '群交',
    '无套',
    '無套',
    '有码',
    '有碼',
    '无码',
    '無碼',
    '中文',
    '中文字幕',
    '免费',
    '免費',
    '未知',
    '暂无',
    '暫無',
    'N/A',
    '女优',
    '女優',
  ].map((s) => s.toLowerCase()),
);

function cleanActresses(raw: string): string[] {
  const out: string[] = [];
  for (const token of splitTokens(raw)) {
    const name = token.replace(/\s*[（(][^）)]*[）)]\s*$/, '').trim();
    if (!name || name.length > 40) continue;
    if (JUNK_ACTRESS.has(name.toLowerCase())) continue;
    if (/排行|登入|登录|密码|註冊|注册/i.test(name)) continue;
    if (/^[A-Z]{2,10}\d{2,}$/i.test(name)) continue;
    if (/^\d+$/.test(name) || /https?:\/\//i.test(name)) continue;
    if (!out.includes(name)) out.push(name);
  }
  return out;
}

export function parseScrapSourceText(sourceText?: string | null): ScrapSourceMeta {
  const text = String(sourceText || '');
  const actresses = cleanActresses(line(text, 'actress'));
  const prefix = line(text, 'prefix');
  const genreRaw = line(text, 'genre');
  let plot = line(text, 'plot');
  if (!plot) {
    const m = /^剧情：(.+)$/m.exec(text);
    plot = m?.[1]?.trim() || '';
  }
  let originalPlot = line(text, 'originalPlot');
  if (!originalPlot) {
    const m = /^原剧情：(.+)$/m.exec(text);
    originalPlot = m?.[1]?.trim() || '';
  }
  const badgeRaw = line(text, 'badges');
  const badges = badgeRaw ? splitTokens(badgeRaw) : [];
  const cnsub =
    /^字幕：中字$/m.test(text) ||
    badges.some((b) => /中字|字幕|cnsub/i.test(b));
  return {
    region: line(text, 'region'),
    prefix,
    code: line(text, 'code'),
    title: line(text, 'title'),
    originalTitle: line(text, 'originalTitle'),
    originalPlot,
    outlineShow: line(text, 'outlineShow') || 'zh',
    badges,
    cnsub,
    definition: line(text, 'definition'),
    mosaic: line(text, 'mosaic'),
    actresses,
    studio: line(text, 'studio'),
    label: line(text, 'label'),
    year: line(text, 'year'),
    genres: cleanGenres(genreRaw, actresses, prefix),
    plot,
  };
}
