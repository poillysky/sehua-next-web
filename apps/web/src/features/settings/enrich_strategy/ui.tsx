import { cn } from '@/lib/utils';

export function SegTwo({
  value,
  left,
  right,
  disabled,
  onChange,
  ariaLabel,
}: {
  value: string;
  left: { id: string; label: string };
  right: { id: string; label: string };
  disabled?: boolean;
  onChange: (id: string) => void;
  ariaLabel: string;
}) {
  return (
    <div className="app-seg enrich-strategy__seg" role="radiogroup" aria-label={ariaLabel}>
      {[left, right].map((opt) => (
        <button
          key={opt.id}
          type="button"
          className={cn(
            'app-seg__btn',
            value === opt.id && 'app-seg__btn--active',
          )}
          disabled={disabled}
          role="radio"
          aria-checked={value === opt.id}
          onClick={() => onChange(opt.id)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
