'use client';

import { useEffect } from 'react';
import {
  focusWithoutScroll,
  isEditableElement,
  isPinnedFocusSurface,
  lockPinnedPage,
  pinDocumentScroll,
  pinMainLayout,
  unlockPinnedPage,
} from '@/lib/iosKeyboard';
import { shouldUseNativeShell } from '@/lib/standalone';

/**
 * 拦截 iOS 聚焦前预滚动；搜索/登录/push 表单聚焦时锁主页。
 * 禁止 scrollIntoView / 手动滚 push（会跟 visualViewport 对打，PWA 全屏必抖）。
 */
export function useIOSFocusGuard(enabled = true) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;

    const shouldGuard = (el: HTMLElement) => {
      if (
        el.closest(
          '.app-push, .settings-push, .app-search, .login-screen, .auth-viewport, .p115-paste-page',
        )
      ) {
        return true;
      }
      return shouldUseNativeShell();
    };

    const afterFocus = (el: HTMLElement) => {
      if (isPinnedFocusSurface(el)) {
        lockPinnedPage();
        pinMainLayout();
        window.setTimeout(pinMainLayout, 50);
        window.setTimeout(pinMainLayout, 160);
        window.setTimeout(pinMainLayout, 320);
        return;
      }
      pinDocumentScroll();
    };

    const takeOver = (el: HTMLElement, e: Event) => {
      if (document.activeElement === el) return;
      e.preventDefault();
      focusWithoutScroll(el);
      afterFocus(el);
    };

    const onMouseDown = (e: MouseEvent) => {
      const t = e.target;
      if (!isEditableElement(t) || e.button !== 0) return;
      if (!shouldGuard(t)) return;
      takeOver(t, e);
    };

    const onTouchEnd = (e: TouchEvent) => {
      const t = e.target;
      if (!isEditableElement(t) || !shouldGuard(t)) return;
      if (document.activeElement === t) {
        afterFocus(t);
        return;
      }
      takeOver(t, e);
    };

    const onFocusIn = (e: FocusEvent) => {
      const t = e.target;
      if (!isEditableElement(t) || !shouldGuard(t)) return;
      afterFocus(t);
    };

    const onFocusOut = (e: FocusEvent) => {
      const from = e.target;
      if (!isPinnedFocusSurface(from)) return;
      window.setTimeout(() => {
        const active = document.activeElement;
        if (isPinnedFocusSurface(active)) return;
        if (
          active instanceof Element &&
          active.closest(
            '.app-search, .login-screen, .auth-viewport, .app-push, .settings-push',
          )
        ) {
          return;
        }
        if (document.documentElement.dataset.keyboard === '1') {
          lockPinnedPage();
          return;
        }
        unlockPinnedPage();
      }, 80);
    };

    document.addEventListener('mousedown', onMouseDown, true);
    document.addEventListener('touchend', onTouchEnd, {
      capture: true,
      passive: false,
    });
    document.addEventListener('focusin', onFocusIn, true);
    document.addEventListener('focusout', onFocusOut, true);

    return () => {
      document.removeEventListener('mousedown', onMouseDown, true);
      document.removeEventListener('touchend', onTouchEnd, true);
      document.removeEventListener('focusin', onFocusIn, true);
      document.removeEventListener('focusout', onFocusOut, true);
      unlockPinnedPage();
    };
  }, [enabled]);
}
