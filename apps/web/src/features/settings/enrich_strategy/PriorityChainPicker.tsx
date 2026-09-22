import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';

export type PriorityChainSource = {
  id: string;
  label: string;
  enabled?: boolean;
};

export function PriorityChainPicker({
  rowId,
  label,
  chain,
  open,
  busy,
  sources,
  dataAttr,
  emptyLabel,
  menuHint,
  excludeIds,
  onToggleOpen,
  onToggle,
  onMove,
}: {
  rowId: string;
  label: string;
  chain: string[];
  open: boolean;
  busy: boolean;
  sources: PriorityChainSource[];
  dataAttr: 'data-enrich-rs-box' | 'data-enrich-fp-box';
  emptyLabel: string;
  menuHint: string;
  excludeIds?: Set<string>;
  onToggleOpen: () => void;
  onToggle: (sourceId: string) => void;
  onMove: (sourceId: string, dir: -1 | 1) => void;
}) {
  const labelOf = (sid: string) =>
    sources.find((s) => s.id === sid)?.label || sid;
  const isOn = (sid: string) =>
    sources.find((s) => s.id === sid)?.enabled !== false;
  const dataProps =
    dataAttr === 'data-enrich-rs-box'
      ? { 'data-enrich-rs-box': rowId }
      : { 'data-enrich-fp-box': rowId };

  return (
    <li className="enrich-strategy__rs-row">
      <span className="enrich-strategy__rs-label">{label}</span>
      <div
        className={cn(
          'enrich-strategy__rs-box',
          open && 'enrich-strategy__rs-box--open',
        )}
        {...dataProps}
      >
        <button
          type="button"
          className="enrich-strategy__rs-trigger"
          disabled={busy}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-label={`${label} 源优先级`}
          onClick={onToggleOpen}
        >
          <span className="enrich-strategy__rs-tags">
            {chain.length === 0 ? (
              <span className="enrich-strategy__rs-empty">{emptyLabel}</span>
            ) : (
              chain.map((sid, idx) => (
                <span
                  key={`${rowId}-tag-${sid}`}
                  className={cn(
                    'enrich-strategy__rs-tag',
                    !isOn(sid) && 'enrich-strategy__rs-tag--off',
                  )}
                  title={
                    isOn(sid)
                      ? `${idx + 1}. ${labelOf(sid)}`
                      : `${labelOf(sid)} · 已关总开关，不参与`
                  }
                >
                  <span className="enrich-strategy__rs-tag-text">
                    {labelOf(sid)}
                  </span>
                  <span
                    role="button"
                    tabIndex={-1}
                    className="enrich-strategy__rs-tag-x"
                    aria-label={`移除 ${labelOf(sid)}`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onToggle(sid);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        e.stopPropagation();
                        onToggle(sid);
                      }
                    }}
                  >
                    <X size={12} strokeWidth={2.4} aria-hidden />
                  </span>
                </span>
              ))
            )}
          </span>
          <ChevronDown
            className={cn(
              'enrich-strategy__rs-chev',
              open && 'enrich-strategy__rs-chev--open',
            )}
            size={16}
            strokeWidth={2.4}
            aria-hidden
          />
        </button>
        {open ? (
          <div
            className="enrich-strategy__rs-menu"
            role="listbox"
            aria-multiselectable
            aria-label={`${label} 可选源`}
          >
            {chain.length > 1 ? (
              <div className="enrich-strategy__rs-menu-hint">{menuHint}</div>
            ) : null}
            {chain.map((sid, idx) => (
              <div
                key={`${rowId}-sel-${sid}`}
                className={cn(
                  'enrich-strategy__rs-menu-row enrich-strategy__rs-menu-row--on',
                  !isOn(sid) && 'enrich-strategy__rs-menu-row--off',
                )}
              >
                <button
                  type="button"
                  className="enrich-strategy__rs-menu-main"
                  disabled={busy}
                  onClick={() => onToggle(sid)}
                >
                  <Check
                    className="enrich-strategy__rs-menu-check"
                    size={15}
                    strokeWidth={2.6}
                    aria-hidden
                  />
                  <span>
                    {idx + 1}. {labelOf(sid)}
                    {!isOn(sid) ? ' · 已关' : ''}
                  </span>
                </button>
                <span className="enrich-strategy__rs-menu-move">
                  <button
                    type="button"
                    disabled={busy || idx === 0}
                    aria-label="前移"
                    onClick={() => onMove(sid, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={busy || idx >= chain.length - 1}
                    aria-label="后移"
                    onClick={() => onMove(sid, 1)}
                  >
                    ↓
                  </button>
                </span>
              </div>
            ))}
            {sources
              .filter(
                (s) =>
                  !chain.includes(s.id) && !(excludeIds?.has(s.id) ?? false),
              )
              .map((src) => (
                <button
                  key={`${rowId}-opt-${src.id}`}
                  type="button"
                  className={cn(
                    'enrich-strategy__rs-menu-row',
                    src.enabled === false && 'enrich-strategy__rs-menu-row--off',
                  )}
                  role="option"
                  aria-selected={false}
                  disabled={busy}
                  onClick={() => onToggle(src.id)}
                >
                  <span className="enrich-strategy__rs-menu-check enrich-strategy__rs-menu-check--off" />
                  <span>
                    {src.label}
                    {src.enabled === false ? ' · 已关' : ''}
                  </span>
                </button>
              ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}
