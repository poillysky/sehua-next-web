/**
 * 色花堂子板地区：只认论坛管理已保存的配置（无代码内默认推断）。
 */

import type {
  ForumRegionId,
  ShtForumBoard,
  ShtForumType,
} from '@/config/sehuatangForum';

export type { ForumRegionId };

export const FORUM_REGION_OPTIONS: {
  id: ForumRegionId;
  label: string;
}[] = [
  { id: 'japan', label: '日本' },
  { id: 'china', label: '国产' },
  { id: 'western', label: '欧美' },
  { id: 'mixed', label: '混合' },
  { id: 'other', label: '其他' },
];

const FORUM_REGION_IDS = new Set<ForumRegionId>(
  FORUM_REGION_OPTIONS.map((o) => o.id),
);

export function isForumRegionId(v: string | undefined | null): v is ForumRegionId {
  return Boolean(v && FORUM_REGION_IDS.has(v as ForumRegionId));
}

export function forumRegionLabel(id: ForumRegionId | undefined): string {
  if (!id) return '未设';
  return FORUM_REGION_OPTIONS.find((o) => o.id === id)?.label || '未设';
}

/** 整板无子类时用 fid: 作稳定 key */
export function forumTypeKey(fid: string, typeid = ''): string {
  const f = String(fid || '').trim();
  const t = String(typeid || '').trim();
  return t ? `${f}:${t}` : `${f}:`;
}

/** 板块下可配置叶子（有 types 用子板；否则整板一条） */
export function boardLeafTypes(board: ShtForumBoard): ShtForumType[] {
  if (board.types.length > 0) return board.types;
  return [
    {
      key: forumTypeKey(board.fid),
      fid: board.fid,
      typeid: '',
      name: board.name,
      type_name: board.name,
      board_name: board.name,
    },
  ];
}

/** 只读已保存配置；未设返回 undefined（不参与索引） */
export function resolveForumTypeRegion(
  leaf: Pick<ShtForumType, 'key' | 'fid' | 'typeid' | 'type_name' | 'board_name'>,
  overrides: Record<string, ForumRegionId> | undefined,
): ForumRegionId | undefined {
  const key = leaf.key || forumTypeKey(leaf.fid, leaf.typeid);
  const hit = overrides?.[key];
  if (isForumRegionId(hit)) return hit;
  const parent = forumTypeKey(leaf.fid, '');
  if (parent !== key) {
    const ph = overrides?.[parent];
    if (isForumRegionId(ph)) return ph;
  }
  return undefined;
}

/** 板块内地区摘要 */
export function boardRegionSummary(
  board: ShtForumBoard,
  overrides: Record<string, ForumRegionId> | undefined,
): string {
  const leaves = boardLeafTypes(board);
  const set = new Set(
    leaves
      .map((t) => resolveForumTypeRegion(t, overrides))
      .filter((x): x is ForumRegionId => Boolean(x)),
  );
  if (set.size === 0) return '未设';
  if (set.size === 1) return forumRegionLabel([...set][0]);
  if (set.size < leaves.length) return '多区';
  return '多区';
}
