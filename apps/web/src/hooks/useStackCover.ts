'use client';

import { useEffect, useLayoutEffect, useRef } from 'react';
import { useUiPreferences } from '@/hooks/useUiPreferences';
import {
  captureScrollElement,
  findHubScroller,
  restoreScrollPosition,
  watchScrollMemory,
} from '@/lib/scrollMemory';
import { cn } from '@/lib/utils';
import { blurFocusedDescendant } from '@/lib/blurFocus';

/** 盖住下层前移走焦点，避免 aria-hidden 祖先下仍有 focused 后代的控制台警告 */
function blurIfInside(root: HTMLElement | null) {
  blurFocusedDescendant(root);
}

/**
 * Hub / 下层页面被 AppPush 盖住时：
 * - 开启「返回恢复滚动」：不用 HTML hidden（会丢 scrollTop），改用 .app-stack-covered
 * - 关闭时：沿用 hidden，返回后回到顶部
 */
export function useStackCover(
  covered: boolean,
  scrollKey: string,
  className?: string,
) {
  const [{ restoreScrollOnBack }] = useUiPreferences();
  const rootRef = useRef<HTMLDivElement>(null);
  const coveredRef = useRef(covered);

  useEffect(() => {
    if (!restoreScrollOnBack || covered) return;
    const scroller = findHubScroller(rootRef.current);
    return watchScrollMemory(scroller, scrollKey);
  }, [covered, restoreScrollOnBack, scrollKey]);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const scroller = findHubScroller(root);
    if (!scroller || !scrollKey) return;

    const wasCovered = coveredRef.current;
    coveredRef.current = covered;

    if (!restoreScrollOnBack) return;

    if (covered && !wasCovered) {
      captureScrollElement(scroller, scrollKey);
      return;
    }
    if (!covered && wasCovered) {
      restoreScrollPosition(scroller, scrollKey);
      requestAnimationFrame(() => {
        restoreScrollPosition(scroller, scrollKey);
      });
      const t1 = window.setTimeout(() => {
        restoreScrollPosition(scroller, scrollKey);
      }, 50);
      const t2 = window.setTimeout(() => {
        restoreScrollPosition(scroller, scrollKey);
      }, 120);
      const t3 = window.setTimeout(() => {
        restoreScrollPosition(scroller, scrollKey);
      }, 280);
      return () => {
        window.clearTimeout(t1);
        window.clearTimeout(t2);
        window.clearTimeout(t3);
      };
    }
  }, [covered, restoreScrollOnBack, scrollKey]);

  // 盖住瞬间 blur 内部焦点（须在 aria-hidden / inert 生效同帧）
  useLayoutEffect(() => {
    if (!covered) return;
    blurIfInside(rootRef.current);
  }, [covered]);

  return {
    ref: rootRef,
    'aria-hidden': covered || undefined,
    hidden: restoreScrollOnBack ? undefined : covered || undefined,
    className: cn(
      className,
      restoreScrollOnBack && covered && 'app-stack-covered',
    ),
    ...(covered ? ({ inert: true } as Record<string, boolean>) : {}),
  };
}
