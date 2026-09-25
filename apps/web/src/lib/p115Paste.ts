/** 从粘贴文本中抽出可转存链接与密码 */

const LINK_RE =
  /(?:magnet:\?[^\s"'<>]+|ed2k:\/\/[^\s"'<>]+|https?:\/\/(?:www\.)?(?:115\.com|115cdn\.com)\/s\/[^\s"'<>]+)/gi;

const PASSWORD_RE =
  /(?:解压密码|访问码|分享码|提取码|密码|pwd|password)\s*[:：=\s]\s*([^\s，,;；]+)/i;

/**
 * 色花资源库 `resource_sources.extract_password` 频次前列（已去掉「無/没有密码」等无效项）。
 * 供粘贴转存页一键填入。
 */
export const COMMON_EXTRACT_PASSWORDS: readonly string[] = [
  '1998@www.98T.la',
  'www.98T.la@',
  '暴龙整理',
  '1314',
  '98tang',
  'www.98T.la',
  'sehuatang',
] as const;

function trimTrailingJunk(link: string) {
  return link.replace(/[)\]}>.,;，。；]+$/g, '').trim();
}

export function extractPasteLinks(text: string): string[] {
  const raw = text || '';
  const found: string[] = [];
  const push = (u: string) => {
    const link = trimTrailingJunk(u);
    if (!link || found.includes(link)) return;
    found.push(link);
  };

  for (const m of raw.matchAll(LINK_RE)) {
    push(m[0]);
  }

  for (const line of raw.split(/\r?\n/)) {
    const t = trimTrailingJunk(line);
    if (/^(magnet:|ed2k:\/\/|https?:\/\/)/i.test(t)) push(t);
  }

  return found;
}

export function extractPastePassword(text: string): string | null {
  const m = (text || '').match(PASSWORD_RE);
  return m?.[1]?.trim() || null;
}
