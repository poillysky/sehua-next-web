'use client';

import { ChevronLeft } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

type Props = {
  label?: string;
  iconOnly?: boolean;
  onClick: () => void;
  className?: string;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick' | 'type' | 'className'>;

export function BackButton({
  label = '返回',
  iconOnly = false,
  onClick,
  className = '',
  ...rest
}: Props) {
  return (
    <button
      type="button"
      className={`app-back${iconOnly ? ' app-back--icon' : ''}${className ? ` ${className}` : ''}`}
      onClick={onClick}
      aria-label={rest['aria-label'] || label}
      {...rest}
    >
      <ChevronLeft size={28} strokeWidth={2.25} aria-hidden className="app-back__icon" />
      {!iconOnly ? <span className="app-back__label">{label}</span> : null}
    </button>
  );
}
