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

/** Surfaces where the whole page must stay pinned (search / login / push 表单) */
export function isPinnedFocusSurface(el: EventTarget | null): boolean {
  return (
    el instanceof Element &&
    Boolean(
      el.closest(
        '.app-search, .app-search-row, .login-screen, .auth-viewport, .home-search, .app-push, .settings-push, .p115-paste-page',
      ),
    )
  );
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

  const pushFocused = Boolean(
    document.activeElement instanceof Element &&
      document.activeElement.closest('.app-push, .settings-push, .p115-paste-page'),
  );

  document
    .querySelectorAll<HTMLElement>(
      '.app-shell, .app-body, .auth-viewport, .login-screen, .device-content, .home-landing, .app-stack-root',
    )
    .forEach((el) => {
      if (el.scrollTop !== 0) el.scrollTop = 0;
    });

  // push 聚焦：只钉 document，不跟 visualViewport.offsetTop 对打
  if (pushFocused) return;

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
    // 弹层无键盘时可滚；键盘期整壳钉死
    if (document.documentElement.dataset.keyboard === '1') return false;
    if (document.documentElement.dataset.pageLock === '1') {
      return false;
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
    if (el.dataset.appSavedScroll != null) return;
    el.dataset.appSavedScroll = String(el.scrollTop);
    el.dataset.appSavedOverflow = el.style.overflow;
    el.dataset.appSavedTouchAction = el.style.touchAction;
    el.style.overflow = 'hidden';
    el.style.touchAction = 'none';
    el.scrollTop = 0;
  });

  // push 内 scroller 一并钉死，避免键盘期滚动
  document
    .querySelectorAll<HTMLElement>('.app-push__body, .settings-push__body')
    .forEach((el) => {
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
