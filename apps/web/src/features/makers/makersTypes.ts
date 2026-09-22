import type { ScrapLibraryEmbedItem } from '@/lib/api';

export type DrillStack =
  | { kind: 'hub' }
  | { kind: 'search' }
  /** 文件夹：厂牌 → 前缀 → 番号 */
  | { kind: 'folderStudio'; studio: string }
  | { kind: 'folderPrefix'; studio: string; prefix: string }
  | {
      kind: 'facet';
      facet: 'genre' | 'tag' | 'actress';
      value: string;
      /** 从详情芯片跳转时，返回可回到该条目 */
      fromDetail?: ScrapLibraryEmbedItem;
      /** 女优入口预填（减少头闪烁） */
      posterApi?: string;
      count?: number;
    };

export type Stack =
  | DrillStack
  | { kind: 'detail'; item: ScrapLibraryEmbedItem; from: DrillStack };

/** 女优墙 4 列、文件夹/合集 3 列：用 48 避免满页末行空格 */
export const MAKERS_PAGE_SIZE = 48;
