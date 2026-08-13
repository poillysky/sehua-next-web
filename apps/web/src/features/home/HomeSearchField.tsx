'use client';

import { Languages, Search, X } from 'lucide-react';
import { useState } from 'react';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { fetchTranslate } from '@/lib/api';
import { SourceSwitch, type SearchSource } from './SourceSwitch';

/** 色花一体式搜索框：hero 居中 / compact 顶栏 + 译英 */
export function HomeSearchField({
  draft,
  size,
  busy,
  source,
  onSourceChange,
  showSource = false,
  onDraftChange,
  onSubmit,
  onClear,
}: {
  draft: string;
  size: 'hero' | 'compact';
  busy?: boolean;
  source?: SearchSource;
  onSourceChange?: (v: SearchSource) => void;
  showSource?: boolean;
  onDraftChange: (v: string) => void;
  onSubmit: () => void;
  onClear: () => void;
}) {
  const { toast } = useOverlay();
  const [translating, setTranslating] = useState(false);
  const sourceVisible =
    showSource && source != null && typeof onSourceChange === 'function';

  async function handleTranslate() {
    const text = draft.trim();
    if (!text) {
      toast('请输入要翻译的文字', 'info');
      return;
    }
    if (text.length < 2) {
      toast('请输入至少 2 个字符', 'info');
      return;
    }
    setTranslating(true);
    try {
      const data = await fetchTranslate(text);
      onDraftChange(String(data.text || text));
      if (data.alreadyEnglish) {
        toast('内容已是英文', 'info');
      } else if (data.engine === 'tmdb') {
        toast('已匹配 TMDB 英文片名，请点击搜索', 'success');
      } else {
        toast('已翻译为英文，请点击搜索', 'success');
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '翻译失败，请稍后重试', 'error');
    } finally {
      setTranslating(false);
    }
  }

  return (
    <div
      className={
        size === 'hero'
          ? 'home-search__field home-search__field--hero'
          : 'home-search__field'
      }
    >
      <div
        className={[
          'home-search__control',
          size === 'hero' ? 'home-search__control--hero' : 'home-search__control--compact',
          sourceVisible ? 'home-search__control--with-source' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {sourceVisible ? (
          <>
            <SourceSwitch value={source} onChange={onSourceChange} />
            <span className="home-search__split" aria-hidden />
          </>
        ) : null}
        <label className="home-search__label">
          <span className="sr-only">搜索</span>
          <input
            className="home-search__input"
            type="search"
            enterKeyHint="search"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder="搜索片名、番号或关键词"
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                (e.target as HTMLInputElement).blur();
                onSubmit();
              }
            }}
          />
        </label>
        <div className="home-search__actions">
          {draft ? (
            <button
              type="button"
              className="home-search__clear"
              aria-label="清除"
              onClick={onClear}
            >
              <X size={16} strokeWidth={2.25} aria-hidden />
            </button>
          ) : null}
          <button
            type="button"
            className="home-search__translate"
            title="翻译为英文"
            aria-label="翻译为英文"
            disabled={translating || !draft.trim()}
            onClick={() => void handleTranslate()}
          >
            {translating ? (
              <span className="home-search__translate-spin" aria-hidden />
            ) : (
              <Languages size={17} strokeWidth={2} aria-hidden />
            )}
          </button>
          <button
            type="button"
            className="home-search__go"
            aria-label="搜索"
            aria-busy={busy || undefined}
            disabled={busy}
            onClick={onSubmit}
          >
            {busy ? (
              <span className="home-search__spinner" aria-hidden />
            ) : (
              <Search size={18} strokeWidth={2.25} aria-hidden />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
