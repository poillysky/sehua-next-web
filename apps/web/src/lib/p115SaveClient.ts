import { apiFetch } from "@/lib/api";
import {
  isArchiveDownloadLink,
  linkKindOf,
} from "@/lib/detailResource";

export type P115SaveResult = {
  ok: boolean;
  message: string;
  needConfig?: boolean;
  needLogin?: boolean;
  extractScheduled?: boolean;
  shareCount?: number;
  offlineCount?: number;
};

type Envelope = {
  status?: number;
  data?: {
    ok?: boolean;
    message?: string;
    extractScheduled?: boolean;
    added?: number;
    failed?: { url?: string; message?: string }[];
  } | null;
  message?: string;
  detail?: string | { msg?: string; message?: string }[];
};

function envelopeMessage(json: Envelope, fallback: string): string {
  if (typeof json.detail === "string" && json.detail.trim()) {
    return json.detail.trim();
  }
  if (Array.isArray(json.detail) && json.detail[0]) {
    const first = json.detail[0];
    const m = first.msg || first.message;
    if (m) return String(m);
  }
  const dataMsg = json.data?.message?.trim();
  if (dataMsg) return dataMsg;
  const failedMsg = json.data?.failed?.[0]?.message?.trim();
  if (failedMsg) return failedMsg;
  if (json.message?.trim()) return json.message.trim();
  return fallback;
}

function classifyFail(msg: string): P115SaveResult {
  if (/登录|鉴权|401|未登录/i.test(msg) && !/Cookie|115/i.test(msg)) {
    return { ok: false, message: "请先登录后再转存", needLogin: true };
  }
  if (/尚未配置|缺少 UID|缺少 CID|缺少 SEID|Cookie 无效|Cookie 可能过期|重新粘贴|重新登录 115/i.test(msg)) {
    return {
      ok: false,
      message: /尚未配置/.test(msg)
        ? "尚未配置 115，请先到设置填写 Cookie"
        : msg,
      needConfig: true,
    };
  }
  if (/验证码|911/i.test(msg)) {
    return {
      ok: false,
      message: "需要验证码：请先在 115 网页打开「云下载」完成验证后再点转存",
    };
  }
  if (/配额|10009/i.test(msg)) {
    return {
      ok: false,
      message: "离线任务配额已满，请到 115 清理云下载任务后再试",
    };
  }
  if (/空间不足|10007/i.test(msg)) {
    return { ok: false, message: "115 空间不足，请清理后再转存" };
  }
  return { ok: false, message: msg || "转存 115 失败" };
}

/** 分享 → /settings/p115/share；磁力/ED2K → /settings/p115/offline（含云解压） */
export async function runP115Save(opts: {
  urls: string[];
  password?: string | null;
  titleHint?: string;
}): Promise<P115SaveResult> {
  const urls = Array.from(
    new Set((opts.urls || []).map((u) => u.trim()).filter(Boolean)),
  );
  const password = (opts.password || "").trim();
  if (!urls.length) {
    return { ok: false, message: "没有可转存的磁力 / ED2K / 115 分享链接" };
  }

  const shareUrls = urls.filter((u) => linkKindOf(u) === "115share");
  const offlineUrls = urls.filter((u) => linkKindOf(u) !== "115share");
  const isShareOnly = shareUrls.length > 0 && offlineUrls.length === 0;
  const isArchive = offlineUrls.some((u) => isArchiveDownloadLink(u));
  const wantExtract = !isShareOnly && (Boolean(password) || isArchive);

  try {
    if (shareUrls.length) {
      const res = await apiFetch("/settings/p115/share", {
        method: "POST",
        body: JSON.stringify({
          urls: shareUrls,
          password: password || undefined,
        }),
      });
      const json = (await res.json().catch(() => ({}))) as Envelope;
  if (!res.ok) {
      return classifyFail(
        envelopeMessage(
          json,
          res.status >= 500
            ? "转存服务异常，请稍后重试或检查 115 Cookie"
            : `转存失败（${res.status}）`,
        ),
      );
    }
    if (!offlineUrls.length) {
        return {
          ok: true,
          message:
            envelopeMessage(json, "") ||
            `已转存 ${shareUrls.length} 个 115 分享到网盘`,
          shareCount: shareUrls.length,
        };
      }
    }

    if (!offlineUrls.length) {
      return { ok: false, message: "没有可转存的磁力/ED2K 链接" };
    }

    const res = await apiFetch("/settings/p115/offline", {
      method: "POST",
      body: JSON.stringify({
        urls: offlineUrls,
        password: password || undefined,
        titleHint: opts.titleHint || undefined,
        autoExtract: wantExtract,
      }),
    });
    const json = (await res.json().catch(() => ({}))) as Envelope;
    if (!res.ok) {
      return classifyFail(
        envelopeMessage(
          json,
          res.status >= 500
            ? "转存服务异常，请稍后重试或检查 115 Cookie"
            : `转存失败（${res.status}）`,
        ),
      );
    }

    const extractScheduled = Boolean(json.data?.extractScheduled);
    const msg = envelopeMessage(json, "");
    return {
      ok: true,
      extractScheduled,
      offlineCount: offlineUrls.length,
      shareCount: shareUrls.length || undefined,
      message: extractScheduled
        ? `已转存 ${offlineUrls.length} 条；后台轮询（约 30 秒内）完成后自动云解压`
        : msg || `已转存 ${offlineUrls.length} 条到 115 云下载`,
    };
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err || "");
    if (/failed to fetch|network|load failed/i.test(raw)) {
      return { ok: false, message: "网络异常，请检查 API 是否可用后再试" };
    }
    return { ok: false, message: raw || "转存 115 失败" };
  }
}
