'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function EnrichTabIdle({
  tone = 'neutral',
  waiting = false,
  title,
  desc,
  icon,
}: {
  tone?: 'neutral' | 'ok' | 'fail';
  waiting?: boolean;
  title: string;
  desc: string;
  icon: ReactNode;
}) {
  return (
    <div
      className={cn(
        'enrich-live__idle',
        waiting && 'enrich-live__idle--wait',
        tone === 'ok' && 'enrich-live__idle--ok',
        tone === 'fail' && 'enrich-live__idle--fail',
      )}
    >
      <span className="enrich-live__idle-mark" aria-hidden>
        {icon}
      </span>
      <p className="enrich-live__idle-title">{title}</p>
      <p className="enrich-live__idle-desc">{desc}</p>
    </div>
  );
}
