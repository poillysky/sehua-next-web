'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

function resolveModalRoot(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  return (
    (document.querySelector('.device-content') as HTMLElement | null) ||
    (document.querySelector('.app-shell') as HTMLElement | null) ||
    document.body
  );
}

/** 轻量居中弹层 — portal 到 device-content，避免被 Tab transform / overflow 裁切 */
export function AppCenterModal({
  open,
  title,
  onClose,
  children,
  footer,
  cardClassName,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  cardClassName?: string;
}) {
  const [root, setRoot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setRoot(resolveModalRoot());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !root) return null;

  const overlayClass =
    root === document.body
      ? 'app-modal-overlay app-modal-overlay--viewport'
      : 'app-modal-overlay';

  return createPortal(
    <div className={overlayClass} role="presentation" onClick={onClose}>
      <div
        className={['app-modal-card', 'modal-card', cardClassName].filter(Boolean).join(' ')}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="app-modal-card__head modal-header">
          <h2 className="app-modal-card__title modal-title">{title}</h2>
          <button
            type="button"
            className="app-modal-card__close modal-close"
            aria-label="关闭"
            onClick={onClose}
          >
            <X size={18} strokeWidth={2.25} aria-hidden />
          </button>
        </header>
        <div className="app-modal-card__body modal-body">{children}</div>
        {footer ? (
          <footer className="app-modal-card__foot modal-footer">{footer}</footer>
        ) : null}
      </div>
    </div>,
    root,
  );
}
