/** 页面栈滚动记忆：滚动过程持续记录，返回时按 key 恢复 */

const memory = new Map<string, number>();
/** 防止深逛无限累积；LRU：写入时挪到末尾 */
const MAX_ENTRIES = 200;

export function saveScrollPosition(key: string, top: number): void {
  if (!key) return;
  if (memory.has(key)) memory.delete(key);
  memory.set(key, Math.max(0, top));
  while (memory.size > MAX_ENTRIES) {
    const oldest = memory.keys().next().value;
    if (oldest == null) break;
    memory.delete(oldest);
  }
}

export function clearScrollPosition(key: string): void {
  if (!key) return;
  memory.delete(key);
}

export function peekScrollPosition(key: string): number | undefined {
  if (!key) return undefined;
  return memory.get(key);
}

export function restoreScrollPosition(
  el: HTMLElement | null | undefined,
  key: string,
): void {
  if (!el || !key) return;
  const top = memory.get(key);
  if (top == null) return;
  if (Math.abs(el.scrollTop - top) > 1) {
    el.scrollTop = top;
  }
}

export function captureScrollElement(
  el: HTMLElement | null | undefined,
  key: string,
): void {
  if (!el || !key) return;
  saveScrollPosition(key, el.scrollTop);
}

/** 监听滚动并写入记忆；返回清理函数 */
export function watchScrollMemory(
  el: HTMLElement | null | undefined,
  key: string,
): () => void {
  if (!el || !key) return () => {};
  const onScroll = () => {
    saveScrollPosition(key, el.scrollTop);
  };
  el.addEventListener('scroll', onScroll, { passive: true });
  // 挂上时若已有偏移也记一笔
  if (el.scrollTop > 0) onScroll();
  return () => {
    el.removeEventListener('scroll', onScroll);
    if (el.scrollTop > 0) saveScrollPosition(key, el.scrollTop);
  };
}

/** 在 hub 容器内找主要滚动层 */
export function findHubScroller(
  root: HTMLElement | null | undefined,
): HTMLElement | null {
  if (!root) return null;
  const hit = root.querySelector(
    '.settings-hub__scroll, .app-hub__scroll, .home-search-body, .app-push__body, .app-body',
  );
  return (hit as HTMLElement) || root;
}
