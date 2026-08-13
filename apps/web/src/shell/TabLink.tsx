'use client';

import { type ReactNode, type MouseEvent } from 'react';
import { useTabNavigation, TAB_ROUTES, type TabRoute } from './TabContext';

interface TabLinkProps {
  href: string;
  children: ReactNode;
  className?: string;
  'aria-label'?: string;
}

export function TabLink({ href, children, className, ...rest }: TabLinkProps) {
  const tabCtx = useTabNavigation();

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!tabCtx) return;
    const [path] = href.split('?');
    const tabRoute = path as TabRoute;
    if (TAB_ROUTES.includes(tabRoute)) {
      e.preventDefault();
      tabCtx.scrollToTab(tabRoute);
    }
  };

  return (
    <a href={href} className={className} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}
