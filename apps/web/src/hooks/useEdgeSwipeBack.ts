'use client';

import { useEffect, useRef, type RefObject } from 'react';

/**
 * iOS 边缘侧滑返回手势。
 *
 * 只在屏幕左缘（clientX < EDGE）按下并向右滑动时触发；
 * 位移跟随整层覆盖层，左缘拖出阴影，松手超过阈值则回调 onBack。
 *
 * 与列表横向滚动 / Tab 横向滑动天然隔离：起点必须落在左缘窄区。
 */
const EDGE = 24; // px，左缘触发区宽度
const COMMIT = 0.32; // 位移超过容器宽度该比例即提交返回
const CANCEL = 0.16; // 低于该比例且速度不足则回弹

interface UseEdgeSwipeBackOptions {
  /** 容器 ref（覆盖层根节点，跟随位移） */
  containerRef: RefObject<HTMLElement | null>;
  /** 松手后确认返回（阈值通过） */
  onBack: () => void;
  /** 关闭手势（例如详情内嵌了横向滚动区域时临时禁用） */
  disabled?: boolean;
}

export function useEdgeSwipeBack({
  containerRef,
  onBack,
  disabled = false,
}: UseEdgeSwipeBackOptions) {
  const onBackRef = useRef(onBack);

  useEffect(() => {
    onBackRef.current = onBack;
  }, [onBack]);

  useEffect(() => {
    if (disabled) return;

    const el = containerRef.current;
    if (!el) return;

    // 指针事件不可用（极老环境）则直接降级为无手势
    if (typeof window === 'undefined' || !('PointerEvent' in window)) return;

    const reduceMotion = window.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;

    let pointerId: number | null = null;
    let startX = 0;
    let startY = 0;
    let dragging = false;
    let active = false; // 已进入「边缘右滑」意图
    let width = 0;
    let raf = 0;

    const applyTransform = (dx: number) => {
      if (reduceMotion) return;
      const clamped = Math.max(0, dx);
      el.style.transform = `translate3d(${clamped}px, 0, 0)`;
      el.style.boxShadow = `-${Math.max(0, 8 - clamped * 0.02)}px 0 24px rgba(var(--shadow-color, 0, 0, 0), ${Math.min(
        0.18,
        (clamped / Math.max(1, width)) * 0.22,
      )})`;
    };

    const settle = (commit: boolean) => {
      active = false;
      dragging = false;
      pointerId = null;

      if (reduceMotion) {
        el.style.transform = '';
        el.style.boxShadow = '';
        if (commit) onBackRef.current();
        return;
      }

      el.style.transition =
        'transform 0.26s var(--ease-spring, cubic-bezier(0.34,1.56,0.64,1)), box-shadow 0.26s var(--ease-ios)';
      el.style.transform = commit ? `translate3d(${width}px, 0, 0)` : '';
      el.style.boxShadow = commit
        ? '0 0 0 rgba(0,0,0,0)'
        : '';

      const clear = () => {
        el.style.transition = '';
        el.style.transform = '';
        el.style.boxShadow = '';
        el.removeEventListener('transitionend', clear);
      };
      el.addEventListener('transitionend', clear, { once: true });
      // 兜底（transitionend 可能不触发）
      window.setTimeout(clear, 320);

      if (commit) {
        // 提交：等位移动画过半再回调，避免突兀
        window.setTimeout(() => onBackRef.current(), reduceMotion ? 0 : 180);
      }
    };

    const onPointerDown = (e: PointerEvent) => {
      if (dragging || e.pointerType === 'mouse' && e.button !== 0) return;
      // 只有左缘按下才进入意图
      if (e.clientX > EDGE) return;
      // 忽略落在可交互元素上的（按钮/输入框/可滚动横向区域）
      const target = e.target as HTMLElement | null;
      if (target?.closest('button, a, input, textarea, select, [data-no-swipe]')) {
        return;
      }
      pointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      width = el.clientWidth || window.innerWidth;
      active = false;
    };

    const onPointerMove = (e: PointerEvent) => {
      if (pointerId === null || e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

      if (!active) {
        // 需明显右滑且以横向为主才激活，避免误触纵向滚动
        if (dx > 12 && Math.abs(dx) > Math.abs(dy) * 1.4) {
          active = true;
          dragging = true;
          if (el.setPointerCapture) {
            try {
              el.setPointerCapture(pointerId);
            } catch {
              /* ignore */
            }
          }
        } else if (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx)) {
          // 纵向滚动意图，放弃
          pointerId = null;
          return;
        }
        return;
      }

      e.preventDefault();
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => applyTransform(dx));
    };

    const onPointerUp = (e: PointerEvent) => {
      if (pointerId === null || e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      pointerId = null;
      if (!active) return;
      const ratio = dx / Math.max(1, width);
      const commit = ratio >= COMMIT;
      if (ratio >= CANCEL || commit) {
        settle(commit);
      } else {
        settle(false);
      }
    };

    const onPointerCancel = () => {
      if (pointerId === null) return;
      pointerId = null;
      if (active) settle(false);
    };

    el.addEventListener('pointerdown', onPointerDown, { passive: true });
    el.addEventListener('pointermove', onPointerMove, { passive: false });
    el.addEventListener('pointerup', onPointerUp, { passive: true });
    el.addEventListener('pointercancel', onPointerCancel, { passive: true });

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerCancel);
      el.style.transform = '';
      el.style.boxShadow = '';
      el.style.transition = '';
    };
  }, [containerRef, disabled]);
}
