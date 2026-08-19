'use client';

import { useEffect, useLayoutEffect, useState } from 'react';
import {
  applyChatKeyboardInset,
  clearChatKeyboardInset,
  isPinnedFormTyping,
  lockPinnedPage,
  pinDocumentScroll,
  pinMainLayout,
  pinUnderlyingScrollers,
  shouldSkipViewportFight,
  unlockPinnedPage,
} from '@/lib/iosKeyboard';
import { isStandalone, shouldUseNativeShell } from '@/lib/standalone';
import { useIOSFocusGuard } from '@/hooks/useIOSFocusGuard';

const KEYBOARD_THRESHOLD = 80;
const STABILITY_MS = 120;

/**
 * 壳高固定：键盘只用 --keyboard-inset，不收缩 --app-height。
 * Push 表单不消费 inset（避免垫底上顶）；主页钉住，禁止跟键盘一起被顶走。
 */
export function useAppViewport() {
  const [nativeShell, setNativeShell] = useState(true);
  const [standalone, setStandalone] = useState(false);

  useIOSFocusGuard(true);

  useLayoutEffect(() => {
    const applyMode = () => {
      const native = shouldUseNativeShell();
      const alone = isStandalone();
      setNativeShell(native);
      setStandalone(alone);
      document.documentElement.dataset.shell = native ? 'native' : 'preview';
      document.documentElement.dataset.standalone = alone ? '1' : '0';
      document.body.classList.toggle('is-native-shell', native);
      document.body.classList.toggle('is-standalone', alone);
    };
    applyMode();
    window.addEventListener('resize', applyMode);
    const mq = window.matchMedia('(display-mode: standalone)');
    mq.addEventListener?.('change', applyMode);
    return () => {
      window.removeEventListener('resize', applyMode);
      mq.removeEventListener?.('change', applyMode);
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    let layoutH = window.innerHeight;
    let stabilityTimer: number | null = null;
    let pendingInset = 0;

    const measureGap = () => {
      const vv = window.visualViewport;
      if (!vv) return 0;
      const ref = Math.max(layoutH, window.innerHeight);
      return Math.max(0, ref - vv.height);
    };

    const commitKeyboard = (open: boolean, inset: number) => {
      root.dataset.keyboard = open ? '1' : '0';
      root.style.setProperty('--keyboard-inset', `${open ? inset : 0}px`);
      if (!open) clearChatKeyboardInset();
    };

    const applyLayoutHeight = () => {
      // 键盘打开时禁止改矮壳高
      if (root.dataset.keyboard === '1') return;

      const alone = isStandalone();
      const native = shouldUseNativeShell();
      layoutH = window.innerHeight || layoutH;

      if (alone) {
        root.style.setProperty('--app-height', '100vh');
        return;
      }
      if (!native) {
        root.style.removeProperty('--app-height');
        return;
      }
      root.style.setProperty('--app-height', `${Math.round(layoutH)}px`);
    };

    const applyVisualHeight = () => {
      const vv = window.visualViewport;
      const vh = vv?.height || window.innerHeight;
      root.style.setProperty('--vv-height', `${Math.round(vh)}px`);
      if (vv) {
        root.style.setProperty(
          '--vv-offset-top',
          `${Math.round(vv.offsetTop)}px`,
        );
      }
    };

    const onViewportSignal = () => {
      applyVisualHeight();
      const gap = measureGap();
      const pinnedFormTyping = isPinnedFormTyping();

      // 钉页表单输入：vv 随联想栏微抖，勿反复开关键盘 / 锁页
      if (pinnedFormTyping && gap > 24) {
        if (root.dataset.keyboard !== '1') {
          root.dataset.keyboard = '1';
          root.style.setProperty('--keyboard-inset', '0px');
          lockPinnedPage();
        }
        applyChatKeyboardInset(gap);
        pinDocumentScroll();
        return;
      }

      const skipViewportFight = shouldSkipViewportFight();

      if (gap <= KEYBOARD_THRESHOLD) {
        if (pinnedFormTyping) {
          applyChatKeyboardInset(gap);
          return;
        }
        if (stabilityTimer) {
          window.clearTimeout(stabilityTimer);
          stabilityTimer = null;
        }
        commitKeyboard(false, 0);
        clearChatKeyboardInset();
        const stillPinned = Boolean(
          document.activeElement &&
            (document.activeElement as HTMLElement).closest?.(
              '.app-search, .app-search-row, .login-screen, .auth-viewport, .home-search, .app-push, .settings-push, .p115-paste-page',
            ),
        );
        if (!stillPinned) unlockPinnedPage();
        if (!isStandalone()) applyLayoutHeight();
        return;
      }

      const bezel = document.querySelector('.device-bezel') as HTMLElement | null;
      const capH =
        root.dataset.shell === 'preview' && bezel?.clientHeight
          ? bezel.clientHeight
          : layoutH;
      pendingInset = Math.min(gap, capH * 0.55);
      applyChatKeyboardInset(gap);

      // 首次判定键盘打开：只写 flag；inset 等稳定后再提交（钉页表单不消费 inset）
      if (root.dataset.keyboard !== '1') {
        root.dataset.keyboard = '1';
        root.style.setProperty(
          '--keyboard-inset',
          skipViewportFight ? '0px' : `${pendingInset}px`,
        );
      }
      lockPinnedPage();
      if (skipViewportFight) {
        pinDocumentScroll();
      } else {
        pinMainLayout();
      }
      if (stabilityTimer) window.clearTimeout(stabilityTimer);
      stabilityTimer = window.setTimeout(() => {
        stabilityTimer = null;
        const stillSkipInset = shouldSkipViewportFight();
        commitKeyboard(true, stillSkipInset ? 0 : pendingInset);
        applyChatKeyboardInset(measureGap());
        pinDocumentScroll();
        pinUnderlyingScrollers();
        if (!stillSkipInset) pinMainLayout();
      }, STABILITY_MS);
    };

    const healViewport = () => {
      if (!isStandalone()) return;
      const el = document.querySelector('.app-shell') as HTMLElement | null;
      if (!el) return;
      root.style.setProperty('--app-height', '100vh');
      const prev = el.style.display;
      el.style.display = 'none';
      void el.offsetHeight;
      el.style.display = prev || '';
      layoutH = window.innerHeight || layoutH;
      applyVisualHeight();
    };

    const isEditableFocused = () => {
      const a = document.activeElement;
      if (!(a instanceof HTMLElement)) return false;
      const tag = a.tagName;
      return (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        a.isContentEditable
      );
    };

    applyLayoutHeight();
    applyVisualHeight();
    commitKeyboard(false, 0);

    const boot = [100, 500, 1000].map((ms) =>
      window.setTimeout(() => {
        applyLayoutHeight();
        applyVisualHeight();
      }, ms),
    );

    const onWinResize = () => {
      applyLayoutHeight();
      onViewportSignal();
    };

    window.addEventListener('resize', onWinResize);
    window.visualViewport?.addEventListener('resize', onViewportSignal);
    window.visualViewport?.addEventListener('scroll', () => {
      applyVisualHeight();
      if (root.dataset.keyboard !== '1') return;
      const gap = measureGap();
      if (isPinnedFormTyping()) {
        applyChatKeyboardInset(gap);
        pinDocumentScroll();
        return;
      }
      applyChatKeyboardInset(gap);
      if (shouldSkipViewportFight()) {
        pinDocumentScroll();
        return;
      }
      pinDocumentScroll();
      pinUnderlyingScrollers();
      pinMainLayout();
    });
    window.addEventListener('orientationchange', () => {
      if (stabilityTimer) window.clearTimeout(stabilityTimer);
      commitKeyboard(false, 0);
      window.setTimeout(() => {
        layoutH = window.innerHeight;
        applyLayoutHeight();
        applyVisualHeight();
        healViewport();
      }, 200);
    });
    document.addEventListener('focusout', () => {
      window.setTimeout(() => {
        if (isEditableFocused()) return;
        commitKeyboard(false, 0);
        pinDocumentScroll();
        applyLayoutHeight();
        applyVisualHeight();
        healViewport();
      }, 120);
      window.setTimeout(healViewport, 400);
    });

    return () => {
      boot.forEach((id) => window.clearTimeout(id));
      if (stabilityTimer) window.clearTimeout(stabilityTimer);
      window.removeEventListener('resize', onWinResize);
      window.visualViewport?.removeEventListener('resize', onViewportSignal);
    };
  }, []);

  return { nativeShell, standalone };
}
