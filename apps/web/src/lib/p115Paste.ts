/** 从粘贴文本中抽出可转存链接与密码 */

const LINK_RE =
  /(?:magnet:\?[^\s"'<>]+|ed2k:\/\/[^\s"'<>]+|https?:\/\/(?:www\.)?(?:115\.com|115cdn\.com)\/s\/[^\s"'<>]+)/gi;

const PASSWORD_RE =
  /(?:解压密码|访问码|分享码|提取码|密码|pwd|password)\s*[:：=\s]\s*([^\s，,;；]+)/i;

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
