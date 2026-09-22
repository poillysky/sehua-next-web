'use client';

import { ArrowDown, ArrowUp, Check } from 'lucide-react';

type SortOpt = { id: string; label: string };

/** 排序按钮 + 下拉；外层 ref / toolbar 由调用方包裹 */
export function MakersSortBar({
  showButton,
  buttonClassName = 'makers-view-switch__sort',
  ghostWhenHidden = false,
  sortLabel,
  sortOrder,
  menuOpen,
  onToggleMenu,
  sortOpts,
  activeSortId,
  onPickSort,
}: {
  showButton: boolean;
  buttonClassName?: string;
  /** Hub：隐藏排序时仍占位，避免布局跳动 */
  ghostWhenHidden?: boolean;
  sortLabel: string;
  sortOrder: 'asc' | 'desc';
  menuOpen: boolean;
  onToggleMenu: () => void;
  sortOpts: readonly SortOpt[];
  activeSortId: string;
  onPickSort: (id: string) => void;
}) {
  const OrderIcon = sortOrder === 'asc' ? ArrowUp : ArrowDown;

  const button = showButton ? (
    <button
      type="button"
      className={buttonClassName}
      aria-label={`排序：${sortLabel}${sortOrder === 'asc' ? '升序' : '降序'}`}
      aria-expanded={menuOpen}
      aria-haspopup="listbox"
      onClick={onToggleMenu}
    >
      <span>{sortLabel}</span>
      <OrderIcon size={14} strokeWidth={2.4} aria-hidden />
    </button>
  ) : ghostWhenHidden ? (
    <span
      className={`${buttonClassName} ${buttonClassName}--ghost`}
      aria-hidden
    >
      <span>名称</span>
      <OrderIcon size={14} strokeWidth={2.4} />
    </span>
  ) : null;

  const dropdown =
    showButton && menuOpen ? (
      <div className="makers-sort-dropdown" role="listbox" aria-label="排序">
        {sortOpts.map((opt) => {
          const active = activeSortId === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="option"
              aria-selected={active}
              className={
                active
                  ? 'makers-sort-dropdown__btn is-active'
                  : 'makers-sort-dropdown__btn'
              }
              onClick={() => onPickSort(opt.id)}
            >
              <span className="makers-sort-dropdown__check" aria-hidden>
                {active ? <Check size={15} strokeWidth={2.5} /> : null}
              </span>
              <span className="makers-sort-dropdown__label">{opt.label}</span>
              {active ? (
                <OrderIcon
                  className="makers-sort-dropdown__dir"
                  size={15}
                  strokeWidth={2.4}
                  aria-hidden
                />
              ) : (
                <span className="makers-sort-dropdown__dir" aria-hidden />
              )}
            </button>
          );
        })}
      </div>
    ) : null;

  return (
    <>
      {button}
      {dropdown}
    </>
  );
}
