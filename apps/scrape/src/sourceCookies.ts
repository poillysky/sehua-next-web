/** 对齐 MDCx / sehuatang 常见站 Cookie */
const DEFAULT_COOKIES: Record<string, string> = {
  javbus: "existmag=all; age=verified; dv=1",
  /** javdb 年龄门 + 中文界面（标签偏中文；标题仍常日文） */
  javdb: "over18=1; locale=zh",
  mgstage: "adc=1",
  /** FANZA/DMM 年龄门；详情仍可能受日本 IP 限制 */
  dmm: "age_check_done=1; ckcy=1; cklg=ja; is_overseas=0",
  /** FC2 内容站年龄确认 */
  fc2: "adult_check=1",
};

export function defaultCookieFor(sourceId: string): string {
  return DEFAULT_COOKIES[String(sourceId || "").toLowerCase()] || "";
}

export function cookieForUrl(url: string, sourceId?: string): string {
  if (sourceId) {
    const c = defaultCookieFor(sourceId);
    if (c) return c;
  }
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("javbus") || host.includes("seejav")) {
      return DEFAULT_COOKIES.javbus!;
    }
    if (host.includes("javdb")) return DEFAULT_COOKIES.javdb!;
    if (host.includes("mgstage")) return DEFAULT_COOKIES.mgstage!;
    if (host.includes("dmm.co.jp") || host.includes("fanza")) {
      return DEFAULT_COOKIES.dmm!;
    }
    if (host.includes("fc2.com")) return DEFAULT_COOKIES.fc2!;
  } catch {
    /* ignore */
  }
  return "";
}
