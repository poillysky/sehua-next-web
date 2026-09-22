'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function FormCard({ children }: { children: ReactNode }) {
  return <section className="ai-card">{children}</section>;
}

export function SettingRow({
  label,
  children,
  stack,
}: {
  label: string;
  children: ReactNode;
  stack?: boolean;
}) {
  return (
    <div className={cn('ai-row', stack && 'ai-row--stack')}>
      <span className="ai-row__label">{label}</span>
      <div className="ai-row__control">{children}</div>
    </div>
  );
}
