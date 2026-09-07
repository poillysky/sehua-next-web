'use client';

import { useEffect } from 'react';
import {
  ensureFormFieldAboveKeyboard,
  focusWithoutScroll,
  isEditableElement,
  isPinnedFocusSurface,
  lockPinnedPage,
  PINNED_FOCUS_SEL,
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
      if (el.closest(PINNED_FOCUS_SEL)) return true;
      return shouldUseNativeShell();
    };

    const afterFocus = (el: HTMLElement) => {
      if (isPinnedFocusSurface(el)) {
        lockPinnedPage();
        pinMainLayout();
        window.setTimeout(pinMainLayout, 50);
        window.setTimeout(pinMainLayout, 160);
        window.setTimeout(pinMainLayout, 320);
        window.setTimeout(() => {
          const vv = window.visualViewport;
          if (!vv) return;
          const gap = Math.max(0, window.innerHeight - vv.height);
          if (gap > 24) ensureFormFieldAboveKeyboard(gap);
        }, 280);
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
        if (active instanceof Element && active.closest(PINNED_FOCUS_SEL)) {
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
