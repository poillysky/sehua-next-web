'use client';

import { type ReactNode } from 'react';
import { useTabNavigation } from './TabContext';

export function TabPane({ children }: { children: ReactNode }) {
  const tabCtx = useTabNavigation();
  const h = tabCtx?.paneHeight;
  const w = tabCtx?.paneWidth;

  return (
    <div
      className="overflow-hidden"
      style={{
        height: h ? `${h}px` : '100%',
        /* 必须等于滚动容器 clientWidth；禁止 100vw（桌面预览会撑破） */
        width: w && w > 0 ? `${w}px` : '100%',
        flexGrow: 0,
        flexShrink: 0,
        flexBasis: w && w > 0 ? `${w}px` : '100%',
        maxWidth: w && w > 0 ? `${w}px` : '100%',
        boxSizing: 'border-box',
      }}
    >
      <div className="mx-auto h-full w-full max-w-2xl">{children}</div>
    </div>
  );
}
