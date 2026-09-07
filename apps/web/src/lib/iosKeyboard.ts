/** iOS keyboard / focus helpers — pin shell, never shrink --app-height */

const SHELL_LOCK = 'data-app-scroll-lock';
const SCROLLER_SEL =
  '.app-shell .app-body, .app-shell .settings-screen-root, .app-shell .home-landing, .app-shell .home-search-screen, .app-shell .app-stack-root, .auth-viewport, .login-screen';

let lockCount = 0;
let pageLock = false;
let touchMoveBlock: ((e: TouchEvent) => void) | null = null;
let wheelBlock: ((e: WheelEvent) => void) | null = null;
let vvPinTimer: number | null = null;

export function isEditableElement(el: EventTarget | null): el is HTMLElement {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    const input = el as HTMLInputElement;
    if (tag === 'INPUT') {
      if (
        input.type === 'button' ||
        input.type === 'submit' ||
        input.type === 'checkbox' ||
        input.type === 'radio' ||
        input.readOnly ||
        input.disabled
      ) {
        return false;
      }
    }
    return true;
  }
  return el.isContentEditable;
}

export function isAiChatFocused(): boolean {
  if (typeof document === 'undefined') return false;
  const a = document.activeElement;
  return a instanceof Element && Boolean(a.closest('.ai-chat-push'));
}

let lastChatInsetPx = -1;
let lastChatKeyboardOn = false;

/** 对话搜输入条：贴到键盘上沿（对话页已收起底栏，不再扣 tab 高度） */
export function measureChatKeyboardInset(gap: number): number {
  if (gap <= 0 || typeof document === 'undefined') return 0;
  if (document.documentElement.dataset.aiChat === '1') {
    return Math.max(0, Math.round(gap));
  }
  const tabBar = document.querySelector('.app-tabbar') as HTMLElement | null;
  const tabH = tabBar?.getBoundingClientRect().height ?? 58;
  return Math.max(0, Math.round(gap - tabH));
}

export function applyChatKeyboardInset(gap: number) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const onPage = root.dataset.aiChat === '1';
  const focused = isAiChatFocused();

  let inset = 0;
  if (onPage && focused && gap > 24) {
    inset = measureChatKeyboardInset(gap);
    const vv = window.visualViewport;
    const composer = document.querySelector('.ai-chat__composer');
    if (vv && composer instanceof HTMLElement) {
      const keyboardTop = vv.offsetTop + vv.height;
      const margin = 10;
      const current = lastChatKeyboardOn ? Math.max(0, lastChatInsetPx) : 0;
      // 去掉已有抬起，按自然位置算底部被挡多少
      const naturalBottom = composer.getBoundingClientRect().bottom + current;
      const covered = Math.max(0, Math.round(naturalBottom + margin - keyboardTop));
      if (covered > inset) inset = covered;
    }
  }

  const on = inset > 0;
  if (on === lastChatKeyboardOn && Math.abs(inset - lastChatInsetPx) < 4) return;
  lastChatInsetPx = inset;
  lastChatKeyboardOn = on;
  if (on) root.dataset.chatKeyboard = '1';
  else delete root.dataset.chatKeyboard;
  root.style.setProperty('--chat-keyboard-inset', `${inset}px`);
}

export function clearChatKeyboardInset() {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  lastChatInsetPx = 0;
  lastChatKeyboardOn = false;
  delete root.dataset.chatKeyboard;
  root.style.setProperty('--chat-keyboard-inset', '0px');
}

let lastFormInsetPx = -1;
let lastFormLiftPx = -1;
let lastFormKeyboardOn = false;

/** 设置 / Push 表单：随键盘同步上抬（--form-lift），并垫底可滚 */
export function applyFormKeyboardInset(gap: number) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const a = document.activeElement;
  const inForm =
    isEditableElement(a) &&
    Boolean(
      a.closest(
        '.app-push:not(:has(.ai-chat-push)), .settings-push, .settings-screen-root .app-push, .home-search-screen, .login-screen, .auth-viewport',
      ),
    );
  // 对话搜走 --chat-keyboard-inset，不走表单上抬
  if (isAiChatFocused() || !inForm || gap <= 24) {
    if (lastFormKeyboardOn || lastFormInsetPx !== 0 || lastFormLiftPx !== 0) {
      lastFormInsetPx = 0;
      lastFormLiftPx = 0;
      lastFormKeyboardOn = false;
      delete root.dataset.formKeyboard;
      root.style.setProperty('--form-keyboard-inset', '0px');
      root.style.setProperty('--form-lift', '0px');
    }
    return;
  }
  const inset = Math.max(0, Math.round(gap));
  // 只抬到「输入底边刚过键盘顶」；绝不跟整段键盘高度走
  let lift = 0;
  const vv = window.visualViewport;
  if (vv && isEditableElement(a)) {
    const margin = 12;
    const keyboardTop = vv.offsetTop + vv.height;
    const rect = a.getBoundingClientRect();
    const currentLift = lastFormKeyboardOn ? Math.max(0, lastFormLiftPx) : 0;
    // 去掉已有 transform，按自然位置算最小上抬
    const naturalBottom = rect.bottom + currentLift;
    lift = Math.min(
      inset,
      Math.max(0, Math.round(naturalBottom + margin - keyboardTop)),
    );
  }
  if (
    lastFormKeyboardOn &&
    Math.abs(inset - lastFormInsetPx) < 6 &&
    Math.abs(lift - lastFormLiftPx) < 4
  ) {
    return;
  }
  lastFormInsetPx = inset;
  lastFormLiftPx = lift;
  lastFormKeyboardOn = true;
  root.dataset.formKeyboard = '1';
  // 垫底只留一点，主要靠最小上抬 + 内滚
  root.style.setProperty(
    '--form-keyboard-inset',
    `${Math.min(inset, Math.max(lift + 48, 72))}px`,
  );
  root.style.setProperty('--form-lift', `${lift}px`);
}

export function clearFormKeyboardInset() {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  lastFormInsetPx = -1;
  lastFormLiftPx = -1;
  lastFormKeyboardOn = false;
  delete root.dataset.formKeyboard;
  root.style.setProperty('--form-keyboard-inset', '0px');
  root.style.setProperty('--form-lift', '0px');
}

/**
 * 微调滚动：上抬后若输入仍略偏，平滑滚进可见区。
 */
export function scrollFocusedFieldAboveKeyboard() {
  if (typeof window === 'undefined') return;
  const a = document.activeElement;
  if (!isEditableElement(a)) return;
  if (isAiChatFocused()) return;
  const body = a.closest(
    '.app-push__body, .settings-push__body, .home-search-body, .home-search-screen, .login-screen, .auth-viewport',
  ) as HTMLElement | null;
  if (!body) return;
  const vv = window.visualViewport;
  const viewTop = vv?.offsetTop ?? 0;
  const viewBottom = viewTop + (vv?.height ?? window.innerHeight);
  const margin = 18;
  const rect = a.getBoundingClientRect();
  if (rect.bottom <= viewBottom - margin && rect.top >= viewTop + margin) {
    return;
  }
  let delta = 0;
  if (rect.bottom > viewBottom - margin) {
    delta = rect.bottom - (viewBottom - margin);
  } else if (rect.top < viewTop + margin) {
    delta = rect.top - (viewTop + margin);
  }
  if (Math.abs(delta) < 2) return;
  const next = body.scrollTop + delta;
  try {
    body.scrollTo({ top: next, behavior: 'smooth' });
  } catch {
    body.scrollTop = next;
  }
}

export function ensureFormFieldAboveKeyboard(gap: number) {
  applyFormKeyboardInset(gap);
  if (gap <= 24) return;
  // 等 transform 过渡一帧后再微调滚动
  window.setTimeout(() => {
    requestAnimationFrame(scrollFocusedFieldAboveKeyboard);
  }, 40);
  window.setTimeout(scrollFocusedFieldAboveKeyboard, 200);
}

export function isAiChatTyping(): boolean {
  if (!isAiChatFocused()) return false;
  const a = document.activeElement;
  if (!(a instanceof HTMLElement)) return false;
  return a.classList.contains('ai-chat__input');
}

/** 钉页表单输入中（搜索 / 登录 / Push 设置等）：vv 微抖勿反复开关键盘 / 锁页 */
export function isPinnedFormTyping(): boolean {
  if (typeof document === 'undefined') return false;
  const a = document.activeElement;
  return isEditableElement(a) && isPinnedFocusSurface(a);
}

/** @deprecated 用 isPinnedFormTyping */
export function isPushFormTyping(): boolean {
  return isPinnedFormTyping();
}

/** PWA 键盘期勿跟 visualViewport 对打（Push / 主页搜索 / 登录等） */
export function shouldSkipViewportFight(): boolean {
  if (typeof document === 'undefined') return false;
  const a = document.activeElement;
  if (!(a instanceof Element)) return false;
  if (
    a.closest('.app-push, .settings-push, .p115-paste-page')
  ) {
    return true;
  }
  return isPinnedFormTyping();
}

const FORM_SCROLL_SEL =
  '.app-push__body, .settings-push__body, .home-search-body, .home-search-screen, .login-screen, .auth-viewport, .modal-card, .sheet-panel, .ai-chat__msgs, .ai-chat__composer, .ai-chat__field';

/** 搜索 / 登录 / Push：钉页时仍允许这些区域触摸滚动 */
export const PINNED_FOCUS_SEL =
  '.app-search, .app-search-row, .login-screen, .auth-viewport, .home-search-screen, .home-search-body, .home-search__field, .home-search__input, .app-push, .settings-push, .p115-paste-page';

function pushBodyKeepsScroll(el: HTMLElement): boolean {
  if (el.classList.contains('ai-chat-push')) return true;
  return Boolean(
    el.querySelector(
      'input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]), textarea, select',
    ),
  );
}

function scrollerKeepsInnerScroll(el: HTMLElement): boolean {
  if (
    el.matches(
      '.home-search-screen, .home-search-body, .login-screen, .auth-viewport',
    )
  ) {
    return true;
  }
  return false;
}

/** Surfaces where the whole page must stay pinned (search / login / push 表单) */
export function isPinnedFocusSurface(el: EventTarget | null): boolean {
  return el instanceof Element && Boolean(el.closest(PINNED_FOCUS_SEL));
}

export function focusWithoutScroll(el: HTMLElement) {
  try {
    el.focus({ preventScroll: true });
  } catch {
    el.focus();
  }
  pinDocumentScroll();
}

export function pinDocumentScroll() {
  if (typeof window === 'undefined') return;
  if (window.scrollY !== 0 || window.scrollX !== 0) {
    window.scrollTo(0, 0);
  }
  if (document.documentElement.scrollTop) document.documentElement.scrollTop = 0;
  if (document.body.scrollTop) document.body.scrollTop = 0;
}

/**
 * 钉住主壳滚动。注意：聚焦在 push 表单时不要用 vv.offsetTop 去 scrollTo 对打，
 * 那是 iOS PWA 键盘抖动的主因之一。
 */
export function pinUnderlyingScrollers() {
  if (typeof document === 'undefined') return;
  document
    .querySelectorAll<HTMLElement>('.app-shell [data-app-saved-scroll]')
    .forEach((el) => {
      const y = Number(el.dataset.appSavedScroll || 0);
      if (el.scrollTop !== y) el.scrollTop = y;
    });
}

export function pinMainLayout() {
  if (typeof document === 'undefined') return;
  pinDocumentScroll();

  document
    .querySelectorAll<HTMLElement>(
      '.app-shell, .app-body, .auth-viewport, .login-screen, .device-content, .home-landing, .app-stack-root',
    )
    .forEach((el) => {
      // 搜索结果 / 登录等依赖内滚，绝不能被钉回顶部
      if (scrollerKeepsInnerScroll(el)) return;
      if (el.classList.contains('home-search-body')) return;
      if (el.scrollTop !== 0) el.scrollTop = 0;
    });

  if (shouldSkipViewportFight()) return;

  try {
    const vv = window.visualViewport;
    if (vv && (vv.offsetTop > 0 || window.scrollY !== 0)) {
      window.scrollTo(0, 0);
    }
  } catch {
    /* ignore */
  }
}

function attachTouchLock() {
  if (touchMoveBlock) return;

  const allowScroll = (t: EventTarget | null) => {
    if (!(t instanceof Element)) return false;
    if (t.closest('.toast-stack, .toast')) return true;
    if (document.documentElement.dataset.chatKeyboard === '1') {
      return Boolean(
        t.closest('.ai-chat__msgs, .ai-chat__composer, .ai-chat__field, .ai-chat__input'),
      );
    }
    const root = document.documentElement.dataset;
    // 键盘 / 钉页 / scroll-lock：允许搜索结果、登录、Push 表单内滚（与 CSS 例外一致）
    if (root.keyboard === '1' || root.pageLock === '1' || root.scrollLock === '1') {
      return Boolean(t.closest(FORM_SCROLL_SEL));
    }
    return Boolean(t.closest('.modal-card, .sheet-panel'));
  };

  touchMoveBlock = (e: TouchEvent) => {
    if (allowScroll(e.target)) return;
    e.preventDefault();
  };
  document.addEventListener('touchmove', touchMoveBlock, {
    passive: false,
    capture: true,
  });

  wheelBlock = (e: WheelEvent) => {
    if (allowScroll(e.target)) return;
    e.preventDefault();
  };
  document.addEventListener('wheel', wheelBlock, {
    passive: false,
    capture: true,
  });
}

function detachTouchLock() {
  if (touchMoveBlock) {
    document.removeEventListener('touchmove', touchMoveBlock, true);
    touchMoveBlock = null;
  }
  if (wheelBlock) {
    document.removeEventListener('wheel', wheelBlock, true);
    wheelBlock = null;
  }
}

export function lockUnderlyingScroll() {
  if (typeof document === 'undefined') return;
  const shell =
    document.querySelector('.app-shell') ||
    document.querySelector('.auth-viewport') ||
    document.querySelector('.device-content');
  if (!shell) return;

  lockCount += 1;
  if (lockCount > 1) {
    pinDocumentScroll();
    pinUnderlyingScrollers();
    pinMainLayout();
    return;
  }

  pinDocumentScroll();
  pinMainLayout();
  shell.setAttribute(SHELL_LOCK, '1');
  document.documentElement.dataset.scrollLock = '1';

  document.querySelectorAll<HTMLElement>(SCROLLER_SEL).forEach((el) => {
    if (scrollerKeepsInnerScroll(el)) return;
    if (el.dataset.appSavedScroll != null) return;
    el.dataset.appSavedScroll = String(el.scrollTop);
    el.dataset.appSavedOverflow = el.style.overflow;
    el.dataset.appSavedTouchAction = el.style.touchAction;
    el.style.overflow = 'hidden';
    el.style.touchAction = 'none';
    el.scrollTop = 0;
  });

  // push 内 scroller 一并钉死，避免键盘期滚动（对话搜 msgs 除外）
  document
    .querySelectorAll<HTMLElement>('.app-push__body, .settings-push__body')
    .forEach((el) => {
      if (pushBodyKeepsScroll(el)) return;
      if (el.dataset.appSavedScroll != null) return;
      el.dataset.appSavedScroll = String(el.scrollTop);
      el.dataset.appSavedOverflow = el.style.overflow;
      el.dataset.appSavedTouchAction = el.style.touchAction;
      el.style.overflow = 'hidden';
      el.style.touchAction = 'none';
    });

  attachTouchLock();

  if (vvPinTimer) window.clearInterval(vvPinTimer);
  let ticks = 0;
  vvPinTimer = window.setInterval(() => {
    pinDocumentScroll();
    pinUnderlyingScrollers();
    pinMainLayout();
    ticks += 1;
    if (lockCount === 0) {
      if (vvPinTimer) window.clearInterval(vvPinTimer);
      vvPinTimer = null;
      return;
    }
    if (!pageLock && ticks >= 24) {
      if (vvPinTimer) window.clearInterval(vvPinTimer);
      vvPinTimer = null;
    }
  }, 32);
}

export function unlockUnderlyingScroll() {
  if (typeof document === 'undefined') return;
  lockCount = Math.max(0, lockCount - 1);
  if (lockCount > 0) return;
  clearScrollLockDom();
}

/** 键盘升起 / 搜索聚焦：钉住主页面 */
export function lockPinnedPage() {
  if (typeof document === 'undefined') return;
  if (pageLock) {
    pinMainLayout();
    return;
  }
  pageLock = true;
  document.documentElement.dataset.pageLock = '1';
  lockUnderlyingScroll();
  pinMainLayout();
}

export function unlockPinnedPage() {
  if (typeof document === 'undefined') return;
  if (!pageLock) return;
  pageLock = false;
  delete document.documentElement.dataset.pageLock;
  unlockUnderlyingScroll();
}

function clearScrollLockDom() {
  if (vvPinTimer) {
    window.clearInterval(vvPinTimer);
    vvPinTimer = null;
  }
  detachTouchLock();
  document
    .querySelectorAll(`[${SHELL_LOCK}]`)
    .forEach((el) => el.removeAttribute(SHELL_LOCK));
  delete document.documentElement.dataset.scrollLock;

  document
    .querySelectorAll<HTMLElement>('[data-app-saved-scroll]')
    .forEach((el) => {
      el.style.overflow = el.dataset.appSavedOverflow || '';
      el.style.touchAction = el.dataset.appSavedTouchAction || '';
      const y = Number(el.dataset.appSavedScroll || 0);
      el.scrollTop = y;
      delete el.dataset.appSavedScroll;
      delete el.dataset.appSavedOverflow;
      delete el.dataset.appSavedTouchAction;
    });
}
