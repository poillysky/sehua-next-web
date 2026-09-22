'use client';

import { Search, X } from 'lucide-react';

export function EnrichLiveSearchBar({
  codeQuery,
  onCodeQueryChange,
  searchActive,
  searching,
  clearing,
  onSubmit,
  onClear,
}: {
  codeQuery: string;
  onCodeQueryChange: (v: string) => void;
  searchActive: boolean;
  searching: boolean;
  clearing: boolean;
  onSubmit: () => void;
  onClear: () => void;
}) {
  return (
    <form
      className="app-search-row enrich-live__search"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label className="app-search enrich-live__search-field">
        <Search
          className="app-search-icon enrich-live__search-icon"
          size={16}
          strokeWidth={2.2}
          aria-hidden
        />
        <input
          type="search"
          enterKeyHint="search"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          placeholder="全局搜索番号"
          value={codeQuery}
          disabled={clearing}
          onChange={(e) => onCodeQueryChange(e.target.value)}
          aria-label="全局搜索番号"
        />
        {searchActive || codeQuery ? (
          <button
            type="button"
            className="enrich-live__search-clear"
            aria-label="清除搜索"
            onClick={onClear}
          >
            <X size={15} strokeWidth={2.4} aria-hidden />
          </button>
        ) : null}
      </label>
      <button
        type="submit"
        className="app-search-btn enrich-live__search-btn"
        disabled={searching || !codeQuery.trim()}
      >
        {searching ? '…' : '搜索'}
      </button>
    </form>
  );
}
