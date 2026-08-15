'use client';

import {
  createContext,
  useContext,
  useCallback,
  useRef,
  useState,
  useEffect,
  type ReactNode,
  type RefObject,
} from 'react';
import { unlockPinnedPage, pinDocumentScroll } from '@/lib/iosKeyboard';

/** 主 Tab：仓库 / 影视 / 片商 / 板块 / 设置 */
export const TAB_ROUTES = ['/', '/media', '/makers', '/boards', '/settings'] as const;
export type TabRoute = (typeof TAB_ROUTES)[number];

// 保持 pathname=/，只用 hash，避免命中 app/*/page 的 redirect
function tabToUrl(tab: TabRoute): string {
  if (tab === '/') return '/';
  return `/#${tab.slice(1)}`;
}

function readTabFromLocation(): TabRoute | null {
  const path = window.location.pathname;
  const hash = window.location.hash.replace(/^#/, '');
  const HASH_TO_TAB: Record<string, TabRoute> = {
    media: '/media',
    makers: '/makers',
    boards: '/boards',
    settings: '/settings',
  };
  if (TAB_ROUTES.includes(path as TabRoute) && path !== '/') {
    return path as TabRoute;
  }
  if (hash && HASH_TO_TAB[hash]) return HASH_TO_TAB[hash];
  return null;
}

interface TabContextValue {
  activeTab: TabRoute;
  /** 当前 Tab 索引（指示条 / 轨道位移） */
  scrollProgress: number;
  scrollToTab: (tab: TabRoute) => void;
  containerRef: RefObject<HTMLDivElement | null>;
  paneHeight: number;
  /** 相对滚动容器宽度（预览框内 ≠ 100vw） */
  paneWidth: number;
  /** 再次点击当前 Tab：子页应回到 Hub */
  tabReselect: number;
}

const TabCtx = createContext<TabContextValue | null>(null);

export function useTabNavigation() {
  return useContext(TabCtx);
}

export function TabProvider({ children }: { children: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<TabRoute>('/');
  const [scrollProgress, setScrollProgress] = useState(0);
  const [paneHeight, setPaneHeight] = useState(0);
  const [paneWidth, setPaneWidth] = useState(0);
  const [tabReselect, setTabReselect] = useState(0);
  const activeTabRef = useRef<TabRoute>('/');

  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  const prepareTabSwitch = useCallback(() => {
    const root = document.documentElement;
    const active = document.activeElement;
    if (active instanceof HTMLElement) {
      try {
        active.blur();
      } catch {
        /* ignore */
      }
    }
    root.dataset.keyboard = '0';
    root.style.setProperty('--keyboard-inset', '0px');
    delete root.dataset.pageLock;
    delete root.dataset.scrollLock;
    try {
      unlockPinnedPage();
      pinDocumentScroll();
    } catch {
      /* ignore */
    }
  }, []);

  const scrollToTab = useCallback(
    (tab: TabRoute) => {
      const index = TAB_ROUTES.indexOf(tab);
      if (index === -1) return;

      prepareTabSwitch();

      // 再次点当前 Tab → 通知子页回到 Hub（iOS 习惯）
      if (tab === activeTabRef.current) {
        setTabReselect((n) => n + 1);
        return;
      }

      setActiveTab(tab);
      setScrollProgress(index);

      const url = tabToUrl(tab);
      if (`${window.location.pathname}${window.location.hash}` !== url) {
        window.history.replaceState(null, '', url);
      }
    },
    [prepareTabSwitch],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setPaneHeight(height);
      setPaneWidth(width);
    });
    ro.observe(container);
    setPaneHeight(container.clientHeight);
    setPaneWidth(container.clientWidth);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const tab = readTabFromLocation();
    if (!tab) return;
    const index = TAB_ROUTES.indexOf(tab);
    setActiveTab(tab);
    setScrollProgress(index);
    window.history.replaceState(null, '', tabToUrl(tab));
  }, []);

  return (
    <TabCtx.Provider
      value={{
        activeTab,
        scrollProgress,
        scrollToTab,
        containerRef,
        paneHeight,
        paneWidth,
        tabReselect,
      }}
    >
      {children}
    </TabCtx.Provider>
  );
}
