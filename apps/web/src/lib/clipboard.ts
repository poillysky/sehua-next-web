/**
 * 剪贴板封装 — 指南 §8.4
 * 失败不抛到业务层；调用方用 toast / 弹层兜底。
 */

export async function copyText(text: string): Promise<boolean> {
  const value = String(text ?? "");
  if (!value) return false;

  // 1) 现代 API（需安全上下文 + 用户手势）
  try {
    if (
      typeof navigator !== "undefined" &&
      window.isSecureContext &&
      navigator.clipboard?.writeText
    ) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* fall through */
  }

  // 2) execCommand：放在视口内、可选中（离屏/opacity:0 在部分 WebView 会失败）
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.setAttribute("aria-hidden", "true");
    ta.style.cssText = [
      "position:fixed",
      "top:0",
      "left:0",
      "width:2px",
      "height:2px",
      "padding:0",
      "margin:0",
      "border:none",
      "outline:none",
      "opacity:0.01",
      "z-index:-1",
    ].join(";");
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, value.length);
    const ok = document.execCommand("copy");
    ta.blur();
    ta.remove();
    if (ok) return true;
  } catch {
    /* fall through */
  }

  // 3) 再试一次 Clipboard（部分环境 isSecureContext 误判）
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* ignore */
  }

  return false;
}
