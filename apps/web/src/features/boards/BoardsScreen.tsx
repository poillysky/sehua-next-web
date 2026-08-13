'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import {
  SEHUATANG_FORUM,
  type ShtForumBoard,
  type ShtForumCategory,
} from '@/config/sehuatangForum';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import { fetchBrowse } from '@/lib/api';
import type { ResourceItem } from '@/types/resource';
import { AppPush } from '@/components/ui/AppPush';
import { useTabNavigation } from '@/shell';
import { ResourceCard } from '@/features/home/ResourceCard';
import { ResourceDetailBody } from '@/features/home/ResourceDetailBody';

type BoardView = {
  kind: 'board';
  category: ShtForumCategory;
  board: ShtForumBoard;
};

type ListView = {
  kind: 'list';
  title: string;
  boardFid: string;
  boardName: string;
  /** 从 board 页进列表时返回 board；从 hub 直进则回 hub */
  returnTo: 'hub' | BoardView;
};

type View = { kind: 'hub' } | BoardView | ListView;

const PAGE_SIZE = 15;

function BoardCard({
  name,
  meta,
  tone = 0,
  onClick,
}: {
  name: string;
  meta: string;
  tone?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="sht-board-card"
      data-tone={tone % 3}
      onClick={onClick}
    >
      <span className="sht-board-card__mark" aria-hidden>
        {name.slice(0, 1)}
      </span>
      <span className="sht-board-card__title">{name}</span>
      <span className="sht-board-card__meta">{meta}</span>
    </button>
  );
}

/**
 * 色花堂：Hub（两大分区 · 14 板）→ 子分类 → 最新资源列表
 */
export function BoardsScreen() {
  const tabCtx = useTabNavigation();
  const [view, setView] = useState<View>({ kind: 'hub' });
  const [detailHash, setDetailHash] = useState<string | null>(null);

  const [items, setItems] = useState<ResourceItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [boardDraft, setBoardDraft] = useState('');
  const [boardQuery, setBoardQuery] = useState('');
  const [listHint, setListHint] = useState('');
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const listKeyRef = useRef('');

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/boards') return;
    if (tabCtx.tabReselect > 0) {
      setView({ kind: 'hub' });
      setDetailHash(null);
      setBoardDraft('');
      setBoardQuery('');
      setListHint('');
    }
  }, [tabCtx?.tabReselect, tabCtx?.activeTab]);

  const openBoard = useCallback((category: ShtForumCategory, board: ShtForumBoard) => {
    setBoardDraft('');
    setBoardQuery('');
    setListHint('');
    if (board.types.length) {
      setView({ kind: 'board', category, board });
      return;
    }
    setView({
      kind: 'list',
      title: board.name,
      boardFid: board.fid,
      boardName: board.name,
      returnTo: 'hub',
    });
  }, []);

  const openList = useCallback(
    (opts: {
      title: string;
      boardFid: string;
      boardName: string;
      returnTo: ListView['returnTo'];
    }) => {
      setBoardDraft('');
      setBoardQuery('');
      setListHint('');
      setView({
        kind: 'list',
        title: opts.title,
        boardFid: opts.boardFid,
        boardName: opts.boardName,
        returnTo: opts.returnTo,
      });
    },
    [],
  );

  const submitBoardSearch = useCallback(() => {
    const q = boardDraft.trim();
    if (!q) {
      setListHint('');
      setBoardQuery('');
      return;
    }
    if (q.length < SEARCH_KEYWORD_LENGTH_MIN) {
      setListHint(`请输入至少 ${SEARCH_KEYWORD_LENGTH_MIN} 个字符`);
      return;
    }
    setListHint('');
    setBoardQuery(q);
  }, [boardDraft]);

  // 列表拉取（含板内搜索）
  useEffect(() => {
    if (view.kind !== 'list') {
      setItems([]);
      setPage(1);
      setHasMore(false);
      setError('');
      listKeyRef.current = '';
      return;
    }
    const kw = boardQuery.trim();
    const key = `${view.boardFid}|${view.title}|${kw}`;
    listKeyRef.current = key;
    const ac = new AbortController();
    setLoading(true);
    setError('');
    setItems([]);
    setPage(1);
    setHasMore(false);
    void (async () => {
      try {
        const data = await fetchBrowse({
          page: 1,
          pageSize: PAGE_SIZE,
          boardFid: view.boardFid,
          board: view.boardName,
          keyword: kw || undefined,
          signal: ac.signal,
        });
        if (listKeyRef.current !== key) return;
        setItems(data.resources || []);
        setHasMore(Boolean(data.has_more));
        setPage(1);
      } catch (e) {
        if (ac.signal.aborted) return;
        if (listKeyRef.current !== key) return;
        setError(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (!ac.signal.aborted && listKeyRef.current === key) setLoading(false);
      }
    })();
    return () => ac.abort();
  }, [view, boardQuery]);

  const loadMore = useCallback(async () => {
    if (view.kind !== 'list' || loading || loadingMore || !hasMore) return;
    const next = page + 1;
    const key = listKeyRef.current;
    const kw = boardQuery.trim();
    setLoadingMore(true);
    try {
      const data = await fetchBrowse({
        page: next,
        pageSize: PAGE_SIZE,
        boardFid: view.boardFid,
        board: view.boardName,
        keyword: kw || undefined,
      });
      if (listKeyRef.current !== key) return;
      setItems((prev) => [...prev, ...(data.resources || [])]);
      setHasMore(Boolean(data.has_more));
      setPage(next);
    } catch (e) {
      if (listKeyRef.current !== key) return;
      setError(e instanceof Error ? e.message : '加载更多失败');
    } finally {
      setLoadingMore(false);
    }
  }, [view, loading, loadingMore, hasMore, page, boardQuery]);

  useEffect(() => {
    if (view.kind !== 'list' || detailHash) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void loadMore();
      },
      { root: el.closest('.app-push__body') || null, rootMargin: '120px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [view, detailHash, loadMore, items.length]);

  return (
    <div className="app-stack-root">
      <div className="app-hub" aria-hidden={view.kind !== 'hub'}>
        <div className="app-hub__scroll sht-hub">
          <h1 className="app-hub__title">色花堂</h1>

          {SEHUATANG_FORUM.map((cat, catIdx) => (
            <section key={cat.category} className="sht-section">
              <p className="sht-section__label">
                {cat.category}
                <span className="sht-section__count">{cat.boards.length}</span>
              </p>
              <div className="sht-board-grid">
                {cat.boards.map((b, i) => (
                  <BoardCard
                    key={b.fid}
                    name={b.name}
                    meta={b.types.length ? `${b.types.length} 子板` : '最新'}
                    tone={catIdx * 3 + i}
                    onClick={() => openBoard(cat, b)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

      {view.kind === 'board' ? (
        <AppPush
          title={view.board.name}
          onBack={() => setView({ kind: 'hub' })}
        >
          <div className="sht-board-grid sht-board-grid--push">
            <BoardCard
              name="全部最新"
              meta="整板"
              tone={0}
              onClick={() =>
                openList({
                  title: view.board.name,
                  boardFid: view.board.fid,
                  boardName: view.board.name,
                  returnTo: view,
                })
              }
            />
            {view.board.types.map((t, i) => (
              <BoardCard
                key={t.key}
                name={t.type_name}
                meta={t.board_name}
                tone={i + 1}
                onClick={() =>
                  openList({
                    title: t.name,
                    boardFid: t.key,
                    boardName: t.board_name,
                    returnTo: view,
                  })
                }
              />
            ))}
          </div>
        </AppPush>
      ) : null}

      {view.kind === 'list' ? (
        <AppPush
          title={view.title}
          onBack={() => {
            setBoardDraft('');
            setBoardQuery('');
            setListHint('');
            if (view.returnTo === 'hub') setView({ kind: 'hub' });
            else setView(view.returnTo);
          }}
        >
          <div aria-hidden={detailHash != null}>
            <div className="sht-list-search">
              <div className="home-search__control home-search__control--compact">
                <label className="home-search__label">
                  <span className="sr-only">在本板搜索</span>
                  <input
                    className="home-search__input"
                    type="search"
                    enterKeyHint="search"
                    autoComplete="off"
                    autoCorrect="off"
                    spellCheck={false}
                    placeholder={`在「${view.title}」中搜索`}
                    value={boardDraft}
                    onChange={(e) => {
                      setBoardDraft(e.target.value);
                      if (listHint) setListHint('');
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        (e.target as HTMLInputElement).blur();
                        submitBoardSearch();
                      }
                    }}
                  />
                </label>
                <div className="home-search__actions">
                  {boardDraft ? (
                    <button
                      type="button"
                      className="home-search__clear"
                      aria-label="清除"
                      onClick={() => {
                        setBoardDraft('');
                        setListHint('');
                        if (boardQuery) setBoardQuery('');
                      }}
                    >
                      <X size={16} strokeWidth={2.25} />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="home-search__go"
                    aria-label="搜索"
                    onClick={() => submitBoardSearch()}
                  >
                    <Search size={16} strokeWidth={2.25} />
                  </button>
                </div>
              </div>
              {listHint ? <p className="sht-list-search__hint">{listHint}</p> : null}
              {boardQuery ? (
                <p className="sht-list-search__hint sht-list-search__hint--ok">
                  筛选：{boardQuery}
                </p>
              ) : null}
            </div>

            {loading ? (
              <p className="app-loading">加载中…</p>
            ) : error ? (
              <div className="app-error">{error}</div>
            ) : items.length === 0 ? (
              <p className="app-empty">
                {boardQuery ? '本板无匹配结果' : '暂无资源'}
              </p>
            ) : (
              <div className="resource-list">
                {items.map((item) => (
                  <ResourceCard
                    key={item.hash}
                    item={item}
                    keywords={boardQuery ? [boardQuery] : []}
                    onOpen={(hash) => setDetailHash(hash)}
                  />
                ))}
                <div className="home-infinite">
                  <div ref={sentinelRef} className="home-infinite__sentinel" aria-hidden />
                  {loadingMore ? <p className="app-loading">加载更多…</p> : null}
                  {!hasMore && items.length > 0 ? (
                    <p className="home-infinite__end">已全部加载</p>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </AppPush>
      ) : null}

      {detailHash ? (
        <AppPush title="详情" onBack={() => setDetailHash(null)}>
          <ResourceDetailBody hash={detailHash} />
        </AppPush>
      ) : null}
    </div>
  );
}
