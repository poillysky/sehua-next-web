import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const APP_ROOT = path.resolve(__dirname, "..");

export function loadEnv(): void {
  const envPath = path.join(APP_ROOT, ".env");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!m || process.env[m[1]!]) continue;
    process.env[m[1]!] = m[2];
  }
}

export function stdCode(raw: string): string {
  // 统一大小写/分隔符；数字补满至少 3 位（OFES-001 / SONE-001）
  // 宽度取 digits.length：保留已有前导零（MD-0362 勿收成 MD-362）
  const s = String(raw || "")
    .trim()
    .toUpperCase()
    .replace(/_/g, "-");
  const m = s.match(/^([A-Z0-9]+)-(\d+)$/);
  if (!m) return s;
  const prefix = m[1]!;
  const digits = m[2]!;
  const n = String(parseInt(digits, 10));
  const width = Math.max(
    3,
    digits.length,
    /^\d+$/.test(prefix) ? digits.length : 0,
  );
  return `${prefix}-${n.padStart(width, "0")}`;
}

export function codeFileStem(code: string): string {
  return stdCode(code).replace(/[^\w.-]+/g, "_");
}

export const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

export async function sleep(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

/** airav.io 等站点常把 SEO 导航文案当成 og:title，不能当真标题 */
export function isJunkTitle(raw: string | null | undefined): boolean {
  const t = String(raw || "").trim();
  if (!t) return true;
  if (/airav\.io|airav\.wiki|免費a片|免费a片|瘋av|疯av|女優av查詢|女优av查询|線上看|在线看/i.test(t)) {
    return true;
  }
  // 仅拦明确的去码/破解「壳标题」，避免误伤正片里偶发的「流出/无码」等词
  // 例：马赛克破坏版 SONE-019 明日叶三叶
  if (/[马馬][赛賽]克\s*破[坏壞]|[马馬][赛賽]克\s*破解/.test(t)) {
    return true;
  }
  // 「去码/解码/AI去码」版 + 番号，多为壳标题而非正片名
  if (
    /(?:AI\s*)?(?:去[码碼]|解[码碼])版/.test(t) &&
    /[A-Z0-9]{2,12}\s*[-_]?\s*\d{2,}/i.test(t)
  ) {
    return true;
  }
  // 整段以「(无码)破解版 + 番号」开头
  if (/^(?:无码|無碼)?破解版\s*[A-Z0-9]/i.test(t)) {
    return true;
  }
  // 「免費,線上看,直播,番號」一类短 SEO 串；含足够汉字的片名即使有逗号也保留
  const commas = (t.match(/,/g) || []).length;
  if (commas >= 2 && t.length <= 80) {
    const han = (t.match(/[\u4e00-\u9fff]/g) || []).length;
    if (han < 6) return true;
  }
  return false;
}

/** 简体/繁体中文片名（无假名）— 对齐 sehuatang splitTitleLang */
export function isLikelyChinese(title: string | null | undefined): boolean {
  const t = String(title || "").trim();
  if (!t || !/[\u4e00-\u9fff]/.test(t)) return false;
  // 忽略中点・等标点，勿把「初・体・験」判成日文
  const body = t.replace(/[\s・･·\-–—:：|/／]/g, "");
  if (/[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff]/g.test(body)) return false;
  return true;
}

/** 本地 preferTitle / 索引 titleZh 复用门：壳题/截断壳不合格 → 仍走网络 */
export function isQualityChineseTitle(title: string | null | undefined): boolean {
  const t = String(title || "").trim();
  if (!t || isJunkTitle(t) || !isLikelyChinese(t)) return false;
  if (/[、，,…]+$/.test(t)) return false;
  if (/^.{1,4}[、，,]/.test(t) && t.length < 16) return false;
  if (/^(?:AV)?(?:隐退作|引退作|出道作|解禁作|引退|隐退)$|^AV初[体體][験驗].{0,6}$/i.test(t)) {
    return false;
  }
  if (
    /^[\u4e00-\u9fff]{2,8}[-·・‧][\u4e00-\u9fff]{2,12}$/.test(t) &&
    t.length <= 14
  ) {
    return false;
  }
  return true;
}

/** 含假名的日文片名（非纯中文） */
export function isLikelyJapanese(title: string | null | undefined): boolean {
  const t = String(title || "").trim();
  if (!t || isJunkTitle(t) || isLikelyChinese(t)) return false;
  return /[\u3040-\u30ff\u31f0-\u31ff]/.test(t);
}

export function isJunkCoverUrl(raw: string | null | undefined): boolean {
  const u = String(raw || "").trim().toLowerCase();
  if (!u) return true;
  // DMM 无图占位、站点 logo、矢量标等不当封面
  return /logo|favicon|sprite|\.svg(\?|$)|airio-logo|placeholder|now[\s._-]*printing|nowprinting/i.test(
    u,
  );
}
