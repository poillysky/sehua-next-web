'use client';

import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useUiPreferences } from '@/hooks/useUiPreferences';
import { useEdgeSwipeBack } from '@/hooks/useEdgeSwipeBack';
import {
  clearScrollPosition,
  restoreScrollPosition,
  saveScrollPosition,
  watchScrollMemory,
} from '@/lib/scrollMemory';

/** 原生 push 子页：顶栏返回 + 正文，非弹窗 */
export function AppPush({
  title,
  onBack,
  children,
  right,
  bodyClassName,
  skipEnterAnimation = false,
  scrollKey,
  scrollMode = 'restore',
}: {
  title: string;
  onBack: () => void;
  children: ReactNode;
  right?: ReactNode;
  bodyClassName?: string;
  /** 同层内容切换时跳过进场动画，避免卡顿 */
  skipEnterAnimation?: boolean;
  /** 滚动记忆键；默认用标题，同层切换请传稳定 key */
  scrollKey?: string;
  /**
   * restore：返回时恢复滚动（列表页）
   * top：每次进入置顶（详情页，避免真机落在中部）
   */
  scrollMode?: 'restore' | 'top';
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [{ restoreScrollOnBack }] = useUiPreferences();
  const memoryKey = (scrollKey || `push:${title}`).trim();
  const pinTop = scrollMode === 'top';

  // iOS 边缘侧滑返回手势
  useEdgeSwipeBack({ containerRef: rootRef, onBack });

  // 动画结束后去掉 transform，避免 iOS 键盘 + visualViewport 跟残留 transform 打架。
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    if (skipEnterAnimation) {
      el.classList.add('app-push--settled');
      return;
    }
    const clear = () => {
      el.classList.add('app-push--settled');
    };
    el.addEventListener('animationend', clear, { once: true });
    const fallback = window.setTimeout(clear, 400);
    return () => {
      el.removeEventListener('animationend', clear);
      window.clearTimeout(fallback);
    };
  }, [skipEnterAnimation]);

  // 滚动时持续写入记忆（切页后 DOM scrollTop 已是 0，不能在 layout 里再抓）
  useEffect(() => {
    if (!restoreScrollOnBack || pinTop) return;
    return watchScrollMemory(bodyRef.current, memoryKey);
  }, [memoryKey, restoreScrollOnBack, pinTop]);

  // 进入：详情置顶 / 列表恢复；短窗口内跟随内容撑高再贴
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;

    if (pinTop) {
      clearScrollPosition(memoryKey);
      el.scrollTop = 0;
      let alive = true;
      const deadline = Date.now() + 480;
      const pin = () => {
        if (!alive || Date.now() > deadline) return;
        if (el.scrollTop !== 0) el.scrollTop = 0;
      };
      const raf1 = requestAnimationFrame(pin);
      const raf2 = requestAnimationFrame(() => requestAnimationFrame(pin));
      const t1 = window.setTimeout(pin, 50);
      const t2 = window.setTimeout(pin, 200);
      let ro: ResizeObserver | null = null;
      if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(pin);
        ro.observe(el);
        if (el.firstElementChild) ro.observe(el.firstElementChild);
      }
      return () => {
        alive = false;
        cancelAnimationFrame(raf1);
        cancelAnimationFrame(raf2);
        window.clearTimeout(t1);
        window.clearTimeout(t2);
        ro?.disconnect();
      };
    }

    if (!restoreScrollOnBack) return;

    restoreScrollPosition(el, memoryKey);

    let alive = true;
    const deadline = Date.now() + 400;
    const reapply = () => {
      if (!alive || Date.now() > deadline) return;
      restoreScrollPosition(el, memoryKey);
    };
    const raf1 = requestAnimationFrame(reapply);
    const raf2 = requestAnimationFrame(() => requestAnimationFrame(reapply));
    const t1 = window.setTimeout(reapply, 50);
    const t2 = window.setTimeout(reapply, 180);

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(reapply);
      ro.observe(el);
    }

    return () => {
      alive = false;
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      ro?.disconnect();
      if (el.scrollTop > 0) saveScrollPosition(memoryKey, el.scrollTop);
    };
  }, [memoryKey, restoreScrollOnBack, pinTop]);

  return (
    <div
      ref={rootRef}
      className={
        skipEnterAnimation ? 'app-push app-push--settled' : 'app-push'
      }
      role="region"
      aria-label={title}
    >
      <header className="app-push__bar">
        <button type="button" className="app-push__back" onClick={onBack}>
          <ChevronLeft size={26} strokeWidth={2} aria-hidden />
          <span>返回</span>
        </button>
        <h1 className="app-push__title">{title}</h1>
        <div className="app-push__right">
          {right ?? <span className="app-push__spacer" aria-hidden />}
        </div>
      </header>
      <div
        ref={bodyRef}
        className={
          bodyClassName ? `app-push__body ${bodyClassName}` : 'app-push__body'
        }
      >
        {children}
      </div>
    </div>
  );
}
