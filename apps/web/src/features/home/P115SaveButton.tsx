'use client';

import { useState } from 'react';
import type { ResourceItem } from '@/types/resource';
import {
  getExtractPassword,
  hasArchiveEd2k,
  isArchiveDownloadLink,
  linkKindOf,
  linksForResource,
  normalizeLinkKind,
} from '@/lib/detailResource';
import { runP115Save } from '@/lib/p115SaveClient';
import type { P115SaveSource } from '@/lib/api';
import { P115_SOURCE_LABEL, resolveP115SaveSource } from '@/lib/p115Source';
import { useTabNavigation } from '@/shell';

type ItemPick = Pick<
  ResourceItem,
  | 'hash'
  | 'ed2k_link'
  | 'ed2k_links'
  | 'extract_password'
  | 'description'
  | 'name'
  | 'title'
  | 'link_kind'
>;

export function P115SaveButton({
  item,
  compact = false,
  onToast,
  source,
}: {
  item: ItemPick;
  compact?: boolean;
  onToast?: (msg: string) => void;
  /** 覆盖入口目录；默认读影视/片商跳转上下文 */
  source?: P115SaveSource;
}) {
  const tabCtx = useTabNavigation();
  const [loading, setLoading] = useState(false);

  const urls = linksForResource(item);
  const password = getExtractPassword(item);
  const titleHint = (item.title || item.name || '').trim();
  const shareUrls = urls.filter((u) => linkKindOf(u) === '115share');
  const offlineUrls = urls.filter((u) => linkKindOf(u) !== '115share');
  const isShareOnly = shareUrls.length > 0 && offlineUrls.length === 0;
  const isArchive = hasArchiveEd2k(item)
    ? true
    : offlineUrls.some((u) => isArchiveDownloadLink(u));
  const wantExtract = !isShareOnly && (Boolean(password) || isArchive);
  const kind = normalizeLinkKind(item.link_kind || linkKindOf(urls[0]));

  if (!urls.length) return null;

  const onSave = async () => {
    if (loading) return;
    setLoading(true);
    try {
      // 点击时解析，避免渲染时 session 尚未写入 / 已被清掉
      const saveSource = resolveP115SaveSource(source);
      const result = await runP115Save({
        urls,
        password,
        titleHint,
        source: saveSource,
      });
      if (!result.ok) {
        onToast?.(result.message);
        if (result.needConfig) {
          window.setTimeout(() => tabCtx?.scrollToTab('/settings'), 600);
        }
        return;
      }
      const destHint =
        saveSource !== 'warehouse'
          ? ` → ${P115_SOURCE_LABEL[saveSource]}`
          : '';
      const tip = wantExtract
        ? result.extractScheduled
          ? `已转存${destHint}，云解压已安排`
          : result.message || `已转存${destHint}`
        : kind === '115share'
          ? `115 分享已接收${destHint}`
          : `已加入离线下载${destHint}`;
      onToast?.(tip);
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : '转存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      className={compact ? 'detail-compact-btn' : 'app-btn-primary'}
      disabled={loading}
      onClick={() => void onSave()}
    >
      {loading ? '转存中…' : '转存 115'}
    </button>
  );
}
