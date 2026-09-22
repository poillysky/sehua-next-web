/** 盖住层设置 aria-hidden 前：若焦点在 root 内则 blur，消除控制台警告 */
export function blurFocusedDescendant(root: Element | null | undefined) {
  if (!root || typeof document === 'undefined') return;
  const active = document.activeElement;
  if (!(active instanceof HTMLElement)) return;
  if (!root.contains(active)) return;
  try {
    active.blur();
  } catch {
    /* ignore */
  }
}
