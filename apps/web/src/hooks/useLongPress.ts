'use client';

import { useEffect, useRef } from 'react';

/**
 * 长按手势。长按 duration 后触发 onLongPress，并在触发时提供可选触觉反馈。
 *
 * 依赖触摸/鼠标长按，通过定时器 + 位移容差判定；轻微移动或提前抬起则取消。
 */
const LONG_PRESS_MS = 480;
const MOVE_TOLERANCE = 10; // px

export function useLongPress<T extends HTMLElement>(
  onLongPress: (e: { clientX: number; clientY: number }) => void,
  opts?: { delay?: number; onHaptic?: () => void },
) {
  const ref = useRef<T | null>(null);
  const onLongPressRef = useRef(onLongPress);
  const optsRef = useRef(opts);

  useEffect(() => {
    onLongPressRef.current = onLongPress;
    optsRef.current = opts;
  }, [onLongPress, opts]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let timer = 0;
    let startX = 0;
    let startY = 0;
    let fired = false;

    const clear = () => {
      window.clearTimeout(timer);
      timer = 0;
    };

    const onStart = (x: number, y: number) => {
      startX = x;
      startY = y;
      fired = false;
      clear();
      const delay = optsRef.current?.delay ?? LONG_PRESS_MS;
      timer = window.setTimeout(() => {
        fired = true;
        optsRef.current?.onHaptic?.();
        onLongPressRef.current({ clientX: startX, clientY: startY });
      }, delay);
    };

    const onMove = (x: number, y: number) => {
      if (fired) return;
      if (
        Math.abs(x - startX) > MOVE_TOLERANCE ||
        Math.abs(y - startY) > MOVE_TOLERANCE
      ) {
        clear();
      }
    };

    const onEnd = () => {
      clear();
      if (fired) suppressNextClick();
    };

    // 长按触发后，抑制紧随其后的 click（防止同时「打开详情」+「呼出菜单」）
    let suppressTimer = 0;
    const suppressNextClick = () => {
      window.clearTimeout(suppressTimer);
      const onClickCapture = (e: MouseEvent) => {
        e.stopPropagation();
        e.preventDefault();
        el.removeEventListener('click', onClickCapture, true);
      };
      el.addEventListener('click', onClickCapture, true);
      suppressTimer = window.setTimeout(() => {
        el.removeEventListener('click', onClickCapture, true);
      }, 700);
    };

    const handleTouchStart = (e: TouchEvent) => {
      const t = e.touches[0];
      if (t) onStart(t.clientX, t.clientY);
    };
    const handleTouchMove = (e: TouchEvent) => {
      const t = e.touches[0];
      if (t) onMove(t.clientX, t.clientY);
    };
    const handleMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      onStart(e.clientX, e.clientY);
    };
    const handleMouseMove = (e: MouseEvent) => {
      onMove(e.clientX, e.clientY);
    };

    el.addEventListener('touchstart', handleTouchStart, { passive: true });
    el.addEventListener('touchmove', handleTouchMove, { passive: true });
    el.addEventListener('touchend', onEnd, { passive: true });
    el.addEventListener('touchcancel', onEnd, { passive: true });
    el.addEventListener('mousedown', handleMouseDown);
    el.addEventListener('mousemove', handleMouseMove);
    el.addEventListener('mouseup', onEnd);
    el.addEventListener('mouseleave', onEnd);
    const onContextMenu = (e: Event) => e.preventDefault();
    el.addEventListener('contextmenu', onContextMenu);

    return () => {
      clear();
      window.clearTimeout(suppressTimer);
      el.removeEventListener('touchstart', handleTouchStart);
      el.removeEventListener('touchmove', handleTouchMove);
      el.removeEventListener('touchend', onEnd);
      el.removeEventListener('touchcancel', onEnd);
      el.removeEventListener('mousedown', handleMouseDown);
      el.removeEventListener('mousemove', handleMouseMove);
      el.removeEventListener('mouseup', onEnd);
      el.removeEventListener('mouseleave', onEnd);
      el.removeEventListener('contextmenu', onContextMenu);
    };
  }, []);

  return ref;
}
