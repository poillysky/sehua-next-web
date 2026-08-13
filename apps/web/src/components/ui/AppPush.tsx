'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';

/** 原生 push 子页：顶栏返回 + 正文，非弹窗 */
export function AppPush({
  title,
  onBack,
  children,
  right,
}: {
  title: string;
  onBack: () => void;
  children: ReactNode;
  right?: ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  // 动画结束后去掉 transform，避免 iOS 键盘 + visualViewport 跟残留 transform 打架。
  // 用 class 一次性切到 settled，避免先清 animation 再清 transform 时闪一帧。
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const clear = () => {
      el.classList.add('app-push--settled');
    };
    el.addEventListener('animationend', clear, { once: true });
    const fallback = window.setTimeout(clear, 400);
    return () => {
      el.removeEventListener('animationend', clear);
      window.clearTimeout(fallback);
    };
  }, []);

  // 用 region 而非 dialog/aria-modal，避免拦截底栏 Tab 点击
  return (
    <div ref={rootRef} className="app-push" role="region" aria-label={title}>
      <header className="app-push__bar">
        <button type="button" className="app-push__back" onClick={onBack}>
          <ChevronLeft size={26} strokeWidth={2} aria-hidden />
          <span>返回</span>
        </button>
        <h1 className="app-push__title">{title}</h1>
        <div className="app-push__right">{right ?? <span className="app-push__spacer" aria-hidden />}</div>
      </header>
      <div className="app-push__body">{children}</div>
    </div>
  );
}
