'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useRef, useEffect, type MouseEvent } from 'react';
import {
  Search,
  Film,
  LayoutGrid,
  Settings,
  ChevronLeft,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { startViewTransition } from '@/lib/pwa';
import { HapticsProvider, useHaptics } from './HapticsProvider';
import { useTabNavigation, type TabRoute } from './TabContext';

const NAV_ITEMS: { tab: TabRoute; label: string; icon: typeof Search }[] = [
  { tab: '/', label: '仓库', icon: Search },
  { tab: '/makers', label: '片商', icon: Film },
  { tab: '/boards', label: '板块', icon: LayoutGrid },
  { tab: '/settings', label: '设置', icon: Settings },
];


export function AppShell({ children }: { children: React.ReactNode }) {
  const tabCtx = useTabNavigation();
  const router = useRouter();

  // Tabbed mode: inside TabProvider (main app)
  // Standalone mode: export/settings pages (no tab context)
  const isTabbed = !!tabCtx;

  /** Navigate back with View Transition animation (reverse pop) */
  const handleBackClick = (e: MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    document.documentElement.classList.add('vt-back');
    startViewTransition(() => {
      router.push('/');
    });
  };

  return (
    <HapticsProvider>
    {/* 
      IMPORTANT: The nav MUST be inside this h-dvh flex-col container as a 
      normal flex child (shrink-0), NOT position:fixed. On iOS standalone PWAs,
      position:fixed bottom-0 does not reach the actual screen bottom — it 
      floats above the home indicator. Normal flex flow inside h-dvh pushes 
      the nav to the true screen bottom. See notes/ios-pwa-layout.md.
    */}
    <div
      className={cn(
        'app-shell flex flex-col overflow-hidden',
        isTabbed ? 'h-dvh' : 'min-h-dvh',
      )}
      style={{
        background: 'var(--app-bg)',
        height: isTabbed ? 'var(--app-height, 100vh)' : undefined,
        maxHeight: isTabbed ? 'var(--app-height, 100vh)' : undefined,
      }}
    >
      {isTabbed ? (
        <div
          ref={tabCtx.containerRef}
          className="app-tab-viewport flex-1 min-h-0 w-full"
        >
          <div
            className="app-tab-track"
            style={{
              transform:
                tabCtx.paneWidth > 0
                  ? `translate3d(-${tabCtx.scrollProgress * tabCtx.paneWidth}px, 0, 0)`
                  : `translate3d(-${(tabCtx.scrollProgress / NAV_ITEMS.length) * 100}%, 0, 0)`,
            }}
          >
            {children}
          </div>
        </div>
      ) : (
        <>
          <header
            className="sticky top-0 z-40"
            style={{
              paddingTop: 'var(--nav-safe-top)',
              background: 'rgba(247, 250, 255, 0.88)',
              WebkitBackdropFilter: 'saturate(180%) blur(16px)',
              backdropFilter: 'saturate(180%) blur(16px)',
              borderBottom: '0.5px solid var(--hairline)',
            }}
          >
            <div className="mx-auto flex h-12 max-w-2xl items-center px-1">
              <Link
                href="/"
                onClick={handleBackClick}
                className="app-back"
              >
                <ChevronLeft className="h-5 w-5" />
                <span>返回</span>
              </Link>
            </div>
          </header>
          <main className="mx-auto w-full max-w-2xl flex-1 px-0 pb-4 pt-0">
            <div className="animate-fade-in-up h-full">
              {children}
            </div>
          </main>
        </>
      )}
      {/* Nav is a flex child (shrink-0) INSIDE the h-dvh container — not fixed */}
      <BottomNav
        navItems={NAV_ITEMS}
        isTabbed={isTabbed}
        tabCtx={tabCtx}
      />
    </div>
    </HapticsProvider>
  );
}

/* ─────────────────────────────────────────────
   Bottom nav — tap only, no swipe / drag switch
   
   CRITICAL: Uses shrink-0 in normal flex flow,
   NOT position:fixed. See notes/ios-pwa-layout.md
   ───────────────────────────────────────────── */

interface BottomNavProps {
  navItems: typeof NAV_ITEMS;
  isTabbed: boolean;
  tabCtx: ReturnType<typeof useTabNavigation>;
}

function BottomNav({ navItems, isTabbed, tabCtx }: BottomNavProps) {
  const navRef = useRef<HTMLElement>(null);
  const haptics = useHaptics();
  const prevActiveTab = useRef(tabCtx?.activeTab);

  const progress = tabCtx?.scrollProgress ?? 0;
  const tabCount = navItems.length;

  useEffect(() => {
    if (!isTabbed || !tabCtx) return;
    if (tabCtx.activeTab !== prevActiveTab.current) {
      prevActiveTab.current = tabCtx.activeTab;
      haptics.trigger('selection');
    }
  }, [tabCtx?.activeTab, isTabbed, haptics, tabCtx]);

  return (
    <nav
      ref={navRef}
      className="app-tabbar"
      role="navigation"
      aria-label="主导航"
      style={{
        paddingLeft: 'env(safe-area-inset-left)',
        paddingRight: 'env(safe-area-inset-right)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
    >
      <div className="relative mx-auto flex max-w-2xl items-stretch justify-around px-0.5 pt-1 pb-1">
        {isTabbed && (
          <span
            className="app-tabbar-indicator"
            style={{
              width: `${100 / tabCount}%`,
              left: `${(progress / tabCount) * 100}%`,
              transition: 'left 120ms var(--ease-ios)',
            }}
            aria-hidden
          />
        )}

        {navItems.map(({ tab, label, icon: Icon }, index) => {
          const distance = isTabbed ? Math.abs(progress - index) : Infinity;
          const activity = isTabbed ? Math.max(0, 1 - distance) : 0;
          const isNearest = isTabbed ? tabCtx?.activeTab === tab : false;
          const opacity = 0.45 + activity * 0.55;
          const scale = 1 + activity * 0.06;
          const stroke = 1.75 + activity * 0.5;

          if (isTabbed) {
            return (
              <button
                key={tab}
                type="button"
                data-tab-index={index}
                onClick={() => tabCtx?.scrollToTab(tab)}
                className={cn(
                  'app-tab-item',
                  activity > 0.5 && 'app-tab-item--active',
                )}
                style={{ opacity }}
                aria-current={isNearest ? 'page' : undefined}
              >
                <Icon
                  aria-hidden
                  style={{ transform: `scale(${scale})` }}
                  strokeWidth={stroke}
                />
                <span className="leading-none">{label}</span>
              </button>
            );
          }

          return (
            <Link
              key={tab}
              href={tab === '/' ? '/' : `/#${tab.slice(1)}`}
              data-tab-index={index}
              className="app-tab-item"
            >
              <Icon aria-hidden strokeWidth={1.75} />
              <span className="leading-none">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
