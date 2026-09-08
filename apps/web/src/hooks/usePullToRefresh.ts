'use client';

import { useEffect, useRef, type RefObject } from 'react';

/**
 * iOS 风格下拉刷新。
 *
 * 作用于滚动容器：当容器已在顶部（scrollTop <= 0）且继续下拉时，
 * 用橡皮筋位移 + 顶部旋转指示器反馈，松手超过阈值触发 onRefresh。
 *
 * 仅「touch」指针参与，避免桌面鼠标拖拽误触。
 */
const THRESHOLD = 64; // px，松手超过该位移即触发刷新
const MAX_PULL = 96; // px，最大橡皮筋位移
const RESIST = 0.45; // 阻尼系数（越拉越「重」）

interface UsePullToRefreshOptions {
  /** 滚动容器 ref */
  scrollRef: RefObject<HTMLElement | null>;
  /** 触发刷新（调用方重置分页/重拉数据） */
  onRefresh: () => void;
  /** 禁用（如非列表态） */
  disabled?: boolean;
}

export function usePullToRefresh({
  scrollRef,
  onRefresh,
  disabled = false,
}: UsePullToRefreshOptions) {
  const onRefreshRef = useRef(onRefresh);

  useEffect(() => {
    onRefreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    if (disabled) return;
    const el = scrollRef.current;
    if (!el) return;
    if (typeof window === 'undefined' || !('PointerEvent' in window)) return;

    const reduceMotion = window.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;

    let pointerId: number | null = null;
    let startY = 0;
    let pulling = false;
    let indicator: HTMLDivElement | null = null;
    let pull = 0;

    const ensureIndicator = () => {
      if (indicator) return indicator;
      const host = el.querySelector('.ptr-host') as HTMLDivElement | null;
      if (host) {
        indicator = host;
        return indicator;
      }
      const div = document.createElement('div');
      div.className = 'ptr-host';
      div.setAttribute('aria-hidden', 'true');
      const spin = document.createElement('span');
      spin.className = 'ptr-spinner';
      div.appendChild(spin);
      el.insertBefore(div, el.firstChild);
      indicator = div;
      return indicator;
    };

    const setPull = (px: number) => {
      pull = px;
      const ind = ensureIndicator();
      const progress = Math.min(1, px / THRESHOLD);
      if (reduceMotion) return;
      ind.style.transform = `translateY(${Math.min(px, MAX_PULL)}px)`;
      ind.style.opacity = String(progress);
      ind.style.setProperty('--ptr-progress', String(progress));
      ind.classList.toggle('ptr--ready', px >= THRESHOLD);
    };

    const reset = () => {
      pull = 0;
      pointerId = null;
      pulling = false;
      if (!indicator) return;
      indicator.classList.remove('ptr--ready', 'ptr--spinning');
      if (reduceMotion) {
        indicator.style.transform = '';
        indicator.style.opacity = '';
        return;
      }
      indicator.style.transition =
        'transform 0.28s var(--ease-ios), opacity 0.28s var(--ease-ios)';
      indicator.style.transform = '';
      indicator.style.opacity = '';
      window.setTimeout(() => {
        if (indicator) {
          indicator.style.transition = '';
        }
      }, 300);
    };

    const commit = () => {
      if (!indicator) return;
      indicator.classList.remove('ptr--ready');
      indicator.classList.add('ptr--spinning');
      if (!reduceMotion) {
        indicator.style.transition = 'transform 0.2s var(--ease-ios)';
        indicator.style.transform = 'translateY(52px)';
        indicator.style.opacity = '1';
      }
      onRefreshRef.current();
      // 调用方刷新期间保持指示器，等下一次 reset 收起（组件卸载/刷新完成时调用）
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== 'touch') return;
      if (pulling || pointerId !== null) return;
      // 仅当容器已到顶才可能进入下拉
      if (el.scrollTop > 0) return;
      pointerId = e.pointerId;
      startY = e.clientY;
      pulling = false;
    };

    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerType !== 'touch' || pointerId === null) return;
      if (e.pointerId !== pointerId) return;
      const dy = e.clientY - startY;
      if (!pulling) {
        if (dy > 8 && el.scrollTop <= 0) {
          pulling = true;
        } else if (dy < -8) {
          pointerId = null;
        }
        return;
      }
      if (dy <= 0) {
        setPull(0);
        return;
      }
      e.preventDefault();
      // 阻尼：越拉越重
      const resisted = dy * RESIST;
      setPull(resisted);
    };

    const onPointerUp = (e: PointerEvent) => {
      if (e.pointerType !== 'touch' || pointerId === null) return;
      if (e.pointerId !== pointerId) return;
      pointerId = null;
      if (!pulling) return;
      if (pull >= THRESHOLD) {
        commit();
      } else {
        reset();
      }
    };

    const onPointerCancel = () => {
      if (pointerId === null) return;
      pointerId = null;
      if (pulling) reset();
    };

    el.addEventListener('pointerdown', onPointerDown, { passive: true });
    el.addEventListener('pointermove', onPointerMove, { passive: false });
    el.addEventListener('pointerup', onPointerUp, { passive: true });
    el.addEventListener('pointercancel', onPointerCancel, { passive: true });

    return () => {
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerCancel);
      if (indicator) indicator.remove();
    };
  }, [scrollRef, disabled]);
}

/** 调用方在刷新完成后收起指示器 */
export function finishPullToRefresh(scrollRef: RefObject<HTMLElement | null>) {
  const el = scrollRef.current;
  if (!el) return;
  const host = el.querySelector('.ptr-host') as HTMLDivElement | null;
  if (!host) return;
  host.classList.remove('ptr--spinning', 'ptr--ready');
  host.style.transition =
    'transform 0.28s var(--ease-ios), opacity 0.28s var(--ease-ios)';
  host.style.transform = '';
  host.style.opacity = '';
  window.setTimeout(() => {
    host.style.transition = '';
  }, 300);
}
