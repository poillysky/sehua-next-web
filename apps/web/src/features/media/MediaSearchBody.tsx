'use client';

import { useCallback, useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import {
  fetchMediaSearch,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import { MediaPosterCard } from './MediaPosterCard';

export function MediaSearchBody({
  source,
  initialQuery = '',
  onOpen,
}: {
  source: MediaSourceId;
  initialQuery?: string;
  onOpen: (item: MediaItem) => void;
}) {
  const [draft, setDraft] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery.trim());
  const [items, setItems] = useState<MediaItem[]>([]);
  const [terms, setTerms] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    const q = query.trim();
    if (q.length < SEARCH_KEYWORD_LENGTH_MIN) {
      setItems([]);
      setTerms([]);
      setErr('');
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr('');
    try {
      const data = await fetchMediaSearch({ source, q, page });
      setItems(data.items || []);
      setTerms(Array.isArray(data.terms) ? data.terms : []);
      setTotalPages(Math.max(1, Number(data.totalPages || 1)));
    } catch (e) {
      setItems([]);
      setTerms([]);
      setErr(e instanceof Error ? e.message : '搜索失败');
    } finally {
      setLoading(false);
    }
  }, [source, query, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function submit() {
    const next = draft.trim();
    if (next.length < SEARCH_KEYWORD_LENGTH_MIN) {
      setErr(`请输入至少 ${SEARCH_KEYWORD_LENGTH_MIN} 个字`);
      return;
    }
    setPage(1);
    setQuery(next);
  }

  const multi = terms.length > 1;

  return (
    <div className="media-search">
      <form
        className="media-search__bar"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="media-search__field">
          <Search
            className="media-search__field-icon"
            size={16}
            strokeWidth={2.25}
            aria-hidden
          />
          <input
            className="media-search__input allow-select"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="片名… 多部用逗号/顿号分隔"
            enterKeyHint="search"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <button type="submit" className="media-search__go">
          搜索
        </button>
      </form>

      {!query ? (
        <div className="media-empty">
          输入片名、演员或关键词
          <p className="media-empty__hint">
            多片名请用逗号、顿号分隔；英文片名含空格时也请用逗号
          </p>
        </div>
      ) : null}

      {!loading && !err && multi ? (
        <p className="media-empty__hint media-search__terms allow-select">
          已按 {terms.length} 个片名分别搜索并合并
        </p>
      ) : null}

      {loading ? (
        <div className="media-wall media-wall--skel" aria-hidden>
          {Array.from({ length: 9 }).map((_, i) => (
            <span key={i} className="media-poster-skel media-poster-skel--wall" />
          ))}
        </div>
      ) : null}

      {!loading && err ? (
        <p className="media-empty allow-select">{err}</p>
      ) : null}
      {!loading && !err && query && items.length === 0 ? (
        <p className="media-empty">没有匹配结果</p>
      ) : null}

      {!loading && !err && items.length > 0 ? (
        <div className="media-wall">
          {items.map((it) => (
            <MediaPosterCard
              key={`${it.source}-${it.id}`}
              item={it}
              size="md"
              onClick={() => onOpen(it)}
            />
          ))}
        </div>
      ) : null}

      {!loading && !err && !multi && totalPages > 1 ? (
        <div className="media-chart__pager">
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span className="media-chart__page-meta">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
