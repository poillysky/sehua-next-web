'use client';

export type SearchSource = 'sehua' | 'bitmagnet';

const OPTIONS: { id: SearchSource; label: string }[] = [
  { id: 'sehua', label: '色花堂' },
  { id: 'bitmagnet', label: 'Bitmagnet' },
];

/** 嵌在搜索框左侧的来源切换 */
export function SourceSwitch({
  value,
  onChange,
}: {
  value: SearchSource;
  onChange: (v: SearchSource) => void;
}) {
  return (
    <div className="home-search__source" role="tablist" aria-label="搜索来源">
      {OPTIONS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={value === id}
          className={`home-search__source-btn${value === id ? ' is-active' : ''}`}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
