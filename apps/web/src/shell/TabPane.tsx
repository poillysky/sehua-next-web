'use client';

import {
  createContext,
  useContext,
  type ReactNode,
} from 'react';
import { useTabNavigation, TAB_ROUTES, type TabRoute } from './TabContext';

const TabPaneVisibleContext = createContext(true);

/** 当前组件是否落在「可见/邻近」的主 Tab 里（远离时停封面请求）。 */
export function useTabPaneVisible() {
  return useContext(TabPaneVisibleContext);
}

export function TabPane({
  tab,
  children,
}: {
  tab: TabRoute;
  children: ReactNode;
}) {
  const tabCtx = useTabNavigation();
  const h = tabCtx?.paneHeight;
  const w = tabCtx?.paneWidth;
  const index = TAB_ROUTES.indexOf(tab);
  // 滑动动画需要邻页仍渲染；远离超过约一屏则停媒体请求
  const progress = tabCtx?.scrollProgress ?? index;
  const visible = index < 0 || Math.abs(progress - index) < 0.92;

  return (
    <div
      className="overflow-hidden app-tab-pane"
      data-tab={tab}
      data-tab-visible={visible ? '1' : '0'}
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
      <TabPaneVisibleContext.Provider value={visible}>
        <div className="app-tab-pane__inner mx-auto h-full w-full max-w-2xl">
          {children}
        </div>
      </TabPaneVisibleContext.Provider>
    </div>
  );
}
