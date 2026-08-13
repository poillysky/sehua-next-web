'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronRight, MessagesSquare } from 'lucide-react';
import {
  getSehuatangForumSettings,
  putSehuatangForumSettings,
} from '@/lib/api';
import {
  SEHUATANG_FORUM,
  type ForumRegionId,
  type ShtForumBoard,
  type ShtForumCategory,
  type ShtForumType,
} from '@/config/sehuatangForum';
import {
  boardLeafTypes,
  boardRegionSummary,
  FORUM_REGION_OPTIONS,
  forumRegionLabel,
  resolveForumTypeRegion,
} from '@/lib/forumRegionDefaults';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

type Stack =
  | { kind: 'hub' }
  | { kind: 'forum' }
  | { kind: 'category'; category: ShtForumCategory }
  | { kind: 'board'; category: ShtForumCategory; board: ShtForumBoard }
  | {
      kind: 'type';
      category: ShtForumCategory;
      board: ShtForumBoard;
      leaf: ShtForumType;
    };

export function ForumManagePanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [overrides, setOverrides] = useState<Record<string, ForumRegionId>>({});
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await getSehuatangForumSettings();
      setOverrides(d.regionByKey || {});
      setLoaded(true);
      onStatus('色花堂', 'ok');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取失败');
      onStatus('异常', 'warn');
    }
  }, [onStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveRegion(key: string, region: ForumRegionId) {
    setBusy(true);
    setMsg('');
    const next = { ...overrides, [key]: region };
    try {
      const saved = await putSehuatangForumSettings({ regionByKey: next });
      setOverrides(saved.regionByKey || next);
      onStatus('色花堂', 'ok');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
      onStatus('异常', 'warn');
    } finally {
      setBusy(false);
    }
  }

  const boardCount = useMemo(
    () => SEHUATANG_FORUM.reduce((n, c) => n + c.boards.length, 0),
    [],
  );

  if (stack.kind === 'forum') {
    return (
      <AppPush title="色花堂" onBack={() => setStack({ kind: 'hub' })}>
        <ul className="settings-group">
          {SEHUATANG_FORUM.map((cat) => (
            <li key={cat.category}>
              <button
                type="button"
                className="settings-nav"
                onClick={() => setStack({ kind: 'category', category: cat })}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">{cat.category}</span>
                  <span className="settings-nav__desc">
                    {cat.boards.length} 个板块
                  </span>
                </span>
                <ChevronRight className="settings-nav__chev" size={18} strokeWidth={2.25} />
              </button>
            </li>
          ))}
        </ul>
        <AppMsg>{msg}</AppMsg>
      </AppPush>
    );
  }

  if (stack.kind === 'category') {
    const cat = stack.category;
    return (
      <AppPush title={cat.category} onBack={() => setStack({ kind: 'forum' })}>
        <ul className="settings-group">
          {cat.boards.map((board) => {
            const leaves = boardLeafTypes(board);
            return (
              <li key={board.fid}>
                <button
                  type="button"
                  className="settings-nav"
                  onClick={() =>
                    setStack({ kind: 'board', category: cat, board })
                  }
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{board.name}</span>
                    <span className="settings-nav__desc">
                      {leaves.length} 子板
                    </span>
                  </span>
                  <span className="settings-nav__status">
                    {boardRegionSummary(board, overrides)}
                  </span>
                  <ChevronRight className="settings-nav__chev" size={18} strokeWidth={2.25} />
                </button>
              </li>
            );
          })}
        </ul>
        <AppMsg>{msg}</AppMsg>
      </AppPush>
    );
  }

  if (stack.kind === 'board') {
    const { category, board } = stack;
    const leaves = boardLeafTypes(board);
    return (
      <AppPush
        title={board.name}
        onBack={() => setStack({ kind: 'category', category })}
      >
        <ul className="settings-group">
          {leaves.map((leaf) => {
            const region = resolveForumTypeRegion(leaf, overrides);
            return (
              <li key={leaf.key}>
                <button
                  type="button"
                  className="settings-nav"
                  onClick={() =>
                    setStack({
                      kind: 'type',
                      category,
                      board,
                      leaf,
                    })
                  }
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{leaf.type_name}</span>
                    <span className="settings-nav__desc">
                      {leaf.typeid ? `${leaf.fid}:${leaf.typeid}` : leaf.fid}
                    </span>
                  </span>
                  <span className="settings-nav__status">
                    {forumRegionLabel(region)}
                  </span>
                  <ChevronRight className="settings-nav__chev" size={18} strokeWidth={2.25} />
                </button>
              </li>
            );
          })}
        </ul>
        <AppMsg>{msg}</AppMsg>
      </AppPush>
    );
  }

  if (stack.kind === 'type') {
    const { category, board, leaf } = stack;
    const current = resolveForumTypeRegion(leaf, overrides);
    return (
      <AppPush
        title={leaf.type_name}
        onBack={() => setStack({ kind: 'board', category, board })}
      >
        <p className="settings-group-label">地区</p>
        <ul className="settings-group">
          {FORUM_REGION_OPTIONS.map((opt) => {
            const selected = current === opt.id;
            return (
              <li key={opt.id}>
                <button
                  type="button"
                  className="settings-nav"
                  disabled={busy || !loaded}
                  onClick={() => void saveRegion(leaf.key, opt.id)}
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{opt.label}</span>
                  </span>
                  {selected ? (
                    <Check
                      size={18}
                      strokeWidth={2.5}
                      color="#007aff"
                      aria-label="已选"
                    />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
        <AppMsg>{msg}</AppMsg>
      </AppPush>
    );
  }

  return (
    <AppPush title="论坛管理" onBack={onBack}>
      <ul className="settings-group">
        <li>
          <button
            type="button"
            className="settings-nav"
            onClick={() => setStack({ kind: 'forum' })}
          >
            <span
              className="settings-nav__icon settings-nav__icon--blue"
              aria-hidden
            >
              <MessagesSquare size={16} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">色花堂</span>
              <span className="settings-nav__desc">
                {SEHUATANG_FORUM.length} 大区 · {boardCount} 板块
              </span>
            </span>
            <span
              className={cn(
                'settings-nav__status',
                loaded ? 'settings-nav__status--ok' : undefined,
              )}
            >
              {loaded ? '已就绪' : '…'}
            </span>
            <ChevronRight className="settings-nav__chev" size={18} strokeWidth={2.25} />
          </button>
        </li>
      </ul>
      <AppMsg>{msg}</AppMsg>
    </AppPush>
  );
}
