'use client';

import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

function resolveSheetRoot(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  return (
    (document.querySelector('.device-content') as HTMLElement | null) ||
    (document.querySelector('.app-shell') as HTMLElement | null) ||
    document.body
  );
}

interface ContextAction {
  label: string;
  onSelect: () => void;
  /** destructive / 危险操作标红 */
  destructive?: boolean;
  icon?: ReactNode;
}

/**
 * iOS 风格底部上下文菜单（长按呼出）。
 * 半透明遮罩 + 底部 sheet，操作项竖向排列，点遮罩/取消关闭。
 */
export function ContextMenu({
  open,
  title,
  actions,
  onClose,
}: {
  open: boolean;
  title?: string;
  actions: ContextAction[];
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  const root = resolveSheetRoot();
  if (!root) return null;

  return createPortal(
    <div
      className="ctx-menu-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="ctx-menu"
        role="menu"
        aria-label={title || '操作'}
        onClick={(e) => e.stopPropagation()}
      >
        {title ? (
          <p className="ctx-menu__title">{title}</p>
        ) : null}
        <div className="ctx-menu__group">
          {actions.map((a, i) => (
            <button
              key={i}
              type="button"
              role="menuitem"
              className={
                a.destructive
                  ? 'ctx-menu__item ctx-menu__item--destructive'
                  : 'ctx-menu__item'
              }
              onClick={() => {
                onClose();
                a.onSelect();
              }}
            >
              {a.icon ? (
                <span className="ctx-menu__ico" aria-hidden>
                  {a.icon}
                </span>
              ) : null}
              <span>{a.label}</span>
            </button>
          ))}
        </div>
        <div className="ctx-menu__group">
          <button
            type="button"
            className="ctx-menu__item ctx-menu__item--cancel"
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </div>,
    root,
  );
}
